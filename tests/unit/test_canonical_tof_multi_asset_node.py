from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import zarr

from battery_workbench.features_physical import canonical_tof
from battery_workbench.orchestrator.nodes import CanonicalTofNode


def test_canonical_tof_node_loads_each_assets_waveform_locator(
    tmp_path, monkeypatch
) -> None:
    processed = tmp_path / "processed"
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    feature_dir = processed / "features" / battery_id / experiment_id / "AS::SLICE" / "FS::SET"
    feature_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::U1::0", "ME::U2::0"],
            "ultrasound_asset_id": ["U001", "U002"],
            "frame_index_raw": [0, 0],
            "event_order_index": [0, 1],
            "waveform_group": ["U001/waveform", "U002/waveform"],
            "waveform_row_index": [0, 0],
        }
    ).to_parquet(feature_dir / "ultrasound_features.parquet", index=False)
    waveform_path = processed / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    waveform_path.parent.mkdir(parents=True)
    store = zarr.open_group(str(waveform_path), mode="w")
    store.create_array("U001/waveform", data=np.asarray([[1, 2, 3]], dtype=np.int32))
    store.create_array("U002/waveform", data=np.asarray([[7, 8, 9]], dtype=np.int32))

    captured: dict[str, object] = {}

    def fake_compute(frames, event_ids, **kwargs):
        captured["frames"] = np.asarray(frames).tolist()
        captured["event_ids"] = list(event_ids)
        return pd.DataFrame(
            {
                "measurement_event_id": event_ids,
                "tof_status": ["VALID"] * len(event_ids),
                "tof_samples": [10.0] * len(event_ids),
                "tof_us": [2.0] * len(event_ids),
                "surface_peak_sample_index": [2] * len(event_ids),
                "bottom_peak_sample_index": [12] * len(event_ids),
            }
        )

    monkeypatch.setattr(canonical_tof, "compute_canonical_tof_series", fake_compute)
    monkeypatch.setattr(
        "battery_workbench.features.gate_calibration.resolve_tof_gate_calibration",
        lambda *_args, **_kwargs: {
            "surface_gate_id": "SURFACE",
            "bottom_gate_id": "BOTTOM",
            "surface_start": 0,
            "surface_end_exclusive": 8,
            "bottom_start": 8,
            "bottom_end_exclusive": 16,
            "gate_calibration_id": "GC::TEST",
            "source": "EXPERIMENT_CONFIRMED",
            "version": 1,
        },
    )
    node = CanonicalTofNode()
    monkeypatch.setattr(
        node,
        "_load_effective_parameters",
        lambda _inputs: {
            "ultrasound.sampling_rate_hz": {
                "value": 5.0e7,
                "status": "RESOLVED",
                "verification_status": "VERIFIED",
            }
        },
    )
    plan = SimpleNamespace(project=SimpleNamespace(battery_id=battery_id, experiment_id=experiment_id))
    ctx = SimpleNamespace(processed_root=processed)

    node.run(plan, {}, ctx)

    assert captured["event_ids"] == ["ME::U1::0", "ME::U2::0"]
    assert captured["frames"] == [[1, 2, 3], [7, 8, 9]]
    output = pd.read_parquet(
        processed / "features_physical" / battery_id / experiment_id / "canonical_tof.parquet"
    )
    assert list(zip(output["ultrasound_asset_id"], output["frame_index_raw"], strict=True)) == [
        ("U001", 0), ("U002", 0)
    ]
    assert "frame_index_raw_x" not in output.columns
    assert "frame_index_raw_y" not in output.columns

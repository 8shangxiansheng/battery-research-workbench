from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import zarr

from battery_workbench.api.errors import APIError
from battery_workbench.api.integrity import assert_canonical_tof_integrity
from battery_workbench.features_physical import canonical_tof
from battery_workbench.orchestrator.nodes import CanonicalTofNode
from battery_workbench.orchestrator.schemas import AnalysisPlan, ArtifactRef, PlanProject
from battery_workbench.reporting.collector import _canonical_tof_active


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
    (feature_dir / "feature_set_manifest.json").write_text("{}\n", encoding="utf-8")
    slice_dir = processed / "analysis_slices" / battery_id / experiment_id / "AS::SLICE"
    slice_dir.mkdir(parents=True)
    (slice_dir / "analysis_slice.parquet").write_bytes(b"analysis-slice")
    events_dir = processed / "multimodal" / battery_id / experiment_id
    events_dir.mkdir(parents=True)
    (events_dir / "measurement_events.parquet").write_bytes(b"measurement-events")
    waveform_path = processed / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    waveform_path.parent.mkdir(parents=True)
    store = zarr.open_group(str(waveform_path), mode="w")
    store.create_array("U001/waveform", data=np.asarray([[1, 2, 3]], dtype=np.int32))
    store.create_array("U002/waveform", data=np.asarray([[7, 8, 9]], dtype=np.int32))
    parameter_dir = processed / "parameters" / battery_id / experiment_id / "PS::TEST"
    parameter_dir.mkdir(parents=True)
    (parameter_dir / "effective_parameters.json").write_text("{}\n", encoding="utf-8")
    (parameter_dir / "parameter_set_manifest.json").write_text("{}\n", encoding="utf-8")
    calibration_dir = processed / "gate_calibrations" / battery_id / experiment_id
    calibration_dir.mkdir(parents=True)
    (calibration_dir / "GC::TEST.json").write_text('{"gate_calibration_id":"GC::TEST"}\n')

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
    monkeypatch.setattr(
        "battery_workbench.orchestrator.nodes.resolve_tof_gate_calibration",
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
    feature_ref = ArtifactRef(
        artifact_type="ULTRASOUND_FEATURE_SET",
        artifact_id="FS::SET",
        path=str(feature_dir),
        manifest_path=str(feature_dir / "feature_set_manifest.json"),
        producer_version="0.2.0",
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    parameter_ref = ArtifactRef(
        artifact_type="PARAMETER_SET",
        artifact_id="PS::TEST",
        path=str(parameter_dir),
        manifest_path=str(parameter_dir / "parameter_set_manifest.json"),
        producer_version="0.1.0",
        battery_id=battery_id,
        experiment_id=experiment_id,
    )

    node.run(
        plan,
        {"PARAMETER_SET": parameter_ref, "ULTRASOUND_FEATURES": feature_ref},
        ctx,
    )

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
    manifest = json.loads(
        (
            processed
            / "features_physical"
            / battery_id
            / experiment_id
            / "canonical_tof_manifest.json"
        ).read_text()
    )
    assert manifest["parameter_set_id"]
    assert manifest["gate_calibration_id"] == "GC::TEST"
    assert manifest["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"
    assert manifest["gate_calibration_version"] == 1
    assert manifest["output_checksums"]["canonical_tof"]
    assert manifest["input_checksums"]["waveform_store"]
    assert manifest["input_checksums"]["analysis_slice"]
    assert manifest["input_paths"]["effective_parameters"] == str(
        parameter_dir / "effective_parameters.json"
    )
    assert manifest["input_paths"]["parameter_set_manifest"] == str(
        parameter_dir / "parameter_set_manifest.json"
    )

    reuse_plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
    )
    reused, reason = node.resolve_existing_output(
        reuse_plan,
        {"PARAMETER_SET": parameter_ref, "ULTRASOUND_FEATURES": feature_ref},
        processed,
    )
    assert reused is not None, reason
    assert_canonical_tof_integrity(
        processed, battery_id=battery_id, experiment_id=experiment_id
    )
    assert _canonical_tof_active(processed, battery_id, experiment_id)
    output_path = processed / "features_physical" / battery_id / experiment_id / "canonical_tof.parquet"
    output_bytes = output_path.read_bytes()
    output_path.write_bytes(b"tampered")
    rejected, reason = node.resolve_existing_output(
        reuse_plan,
        {"PARAMETER_SET": parameter_ref, "ULTRASOUND_FEATURES": feature_ref},
        processed,
    )
    assert rejected is None
    assert "OUTPUT_CHECKSUM_MISMATCH:canonical_tof" in reason
    with pytest.raises(APIError, match="canonical TOF is stale or unverifiable"):
        assert_canonical_tof_integrity(
            processed, battery_id=battery_id, experiment_id=experiment_id
        )
    assert not _canonical_tof_active(processed, battery_id, experiment_id)

    output_path.write_bytes(output_bytes)
    store = zarr.open_group(str(waveform_path), mode="a")
    store["U001/waveform"][0, 0] = 99
    rejected, reason = node.resolve_existing_output(
        reuse_plan,
        {"PARAMETER_SET": parameter_ref, "ULTRASOUND_FEATURES": feature_ref},
        processed,
    )
    assert rejected is None
    assert "waveform_store' changed since the artifact was produced" in reason


def test_canonical_tof_readiness_loads_reused_parameter_set_output(tmp_path) -> None:
    processed = tmp_path / "processed"
    parameter_set_dir = (
        processed / "parameters" / "CELL_TEST" / "EXP_TEST" / "PS::TEST"
    )
    parameter_set_dir.mkdir(parents=True)
    effective_parameters = {
        "ultrasound.sampling_rate_hz": {
            "value": 50_000_000.0,
            "status": "RESOLVED",
            "verification_status": "VERIFIED",
        }
    }
    (parameter_set_dir / "effective_parameters.json").write_text(
        json.dumps(effective_parameters), encoding="utf-8"
    )
    manifest_path = parameter_set_dir / "parameter_set_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_paths": {
                    "effective_parameters": (
                        "data/processed/parameters/CELL_TEST/EXP_TEST/"
                        "PS::TEST/effective_parameters.json"
                    )
                }
            }
        ),
        encoding="utf-8",
    )
    # The resolver returns the experiment-level directory for a reused set;
    # its manifest and files remain nested under the concrete set ID.
    parameter_ref = ArtifactRef(
        artifact_type="PARAMETER_SET",
        artifact_id="PS::TEST",
        path=str(parameter_set_dir.parent),
        manifest_path=str(manifest_path),
        producer_version="0.1.0",
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
    )

    effective = CanonicalTofNode()._load_effective_parameters(
        {"PARAMETER_SET": parameter_ref}
    )

    assert effective == effective_parameters
    from battery_workbench.features_physical.canonical_tof import effective_fs

    assert effective_fs(effective, require_verified=True) == (50_000_000.0, True)

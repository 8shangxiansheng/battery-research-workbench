from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.routes import features_v2


def test_feature_label_preview_preserves_same_local_frame_per_asset(
    tmp_path, monkeypatch
) -> None:
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    monkeypatch.setattr(features_v2, "_load_frames", lambda *_args: np.ones((2, 4)))
    monkeypatch.setattr(
        features_v2,
        "_experiment_gate_context",
        lambda *_args: {"gate_calibration_id": None, "gate_bounds": {}},
    )
    monkeypatch.setattr(features_v2, "_validate_experiment_gate_context", lambda *_args: None)
    monkeypatch.setattr(
        features_v2,
        "selected_feature_series",
        lambda _frames, codes, **_kwargs: {
            code: np.asarray([10.0, 20.0]) for code in codes
        },
    )
    monkeypatch.setattr(
        features_v2,
        "_catalogue_feature_series",
        lambda _frames, codes, _gate_bounds: {
            code: np.asarray([10.0, 20.0]) for code in codes
        },
    )
    events = pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_X::EXP_X::U001::0", "ME::CELL_X::EXP_X::U002::0"],
            "ultrasound_asset_id": ["U001", "U002"],
            "frame_index_raw": [0, 0],
            "cycle_index_raw": [1, 1],
            "step_type": ["恒流充电", "恒流放电"],
            "analysis_eligible": [True, True],
            "sync_error_s": [0.01, 0.02],
            "electrical_asset_id": ["E001", "E002"],
            "electrical_record_locator": ["1", "1"],
            "electrical_row_index": [1, 1],
            "electrical_timestamp": ["2024-01-01T00:00:00", "2024-01-01T00:00:01"],
            "match_status": ["MATCHED_UNIQUE", "MATCHED_UNIQUE"],
            "candidate_record_count": [1, 1],
        }
    )
    labels = pd.DataFrame(
        {
            "measurement_event_id": events["measurement_event_id"],
            "soc_reference_percent": [25.0, 75.0],
        }
    )
    monkeypatch.setattr(features_v2, "_load_events_labels", lambda *_args: (events, labels))
    monkeypatch.setattr(
        features_v2,
        "list_targets",
        lambda *_args: {
            "data": {
                "targets": [
                    {
                        "target_id": "reference_soc_percent",
                        "source": "REFERENCE",
                        "readiness": "READY",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "battery_workbench.features.gate_calibration.resolve_tof_gate_calibration",
        lambda *_args: {
            "gate_calibration_id": None,
            "source": "SOURCE_TEMPLATE",
            "version": 1,
            "surface_gate_id": "SURFACE",
            "bottom_gate_id": "BOTTOM",
            "surface_start": 0,
            "surface_end_exclusive": 1,
            "bottom_start": 2,
            "bottom_end_exclusive": 3,
        },
    )

    response = TestClient(app).post(
        "/api/v1/experiments/CELL_X/EXP_X/feature-label-preview",
        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10},
    )

    assert response.status_code == 200, response.text
    rows = response.json()["data"]["rows"]
    assert [(row["ultrasound_asset_id"], row["frame_index_raw"]) for row in rows] == [
        ("U001", 0),
        ("U002", 0),
    ]
    assert [row["measurement_event_id"] for row in rows] == events["measurement_event_id"].tolist()
    assert [row["values"]["SWA"] for row in rows] == [10.0, 20.0]
    assert [row["target"] for row in rows] == [25.0, 75.0]

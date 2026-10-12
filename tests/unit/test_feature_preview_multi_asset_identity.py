from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.routes import features_v2


def test_current_sampling_rate_resolution_binds_parameter_set_identity(tmp_path) -> None:
    parameter_root = tmp_path / "parameters/CELL_X/EXP_X"
    for parameter_set_id, fs_hz, verification_status in (
        ("PS::a", 50_000_000.0, "VERIFIED"),
        ("PS::b", 80_000_000.0, "VERIFIED"),
    ):
        output = parameter_root / parameter_set_id
        output.mkdir(parents=True)
        (output / "parameter_set_manifest.json").write_text(
            json.dumps({
                "parameter_set_id": parameter_set_id,
                "sampling_rate_status": "RESOLVED",
            }),
            encoding="utf-8",
        )
        (output / "effective_parameters.json").write_text(
            json.dumps({
                "ultrasound.sampling_rate_hz": {
                    "value": fs_hz,
                    "status": "RESOLVED",
                    "verification_status": verification_status,
                }
            }),
            encoding="utf-8",
        )

    current = features_v2._resolved_sampling_rate(tmp_path, "CELL_X", "EXP_X")
    assert current == (50_000_000.0, True, "PS::a")
    assert features_v2._canonical_tof_sampling_rate_matches(
        {
            "sampling_rate_hz": 50_000_000.0,
            "sampling_rate_verified": True,
            "parameter_set_id": "PS::a",
        },
        current,
    )
    assert not features_v2._canonical_tof_sampling_rate_matches(
        {
            "sampling_rate_hz": 50_000_000.0,
            "sampling_rate_verified": True,
            "parameter_set_id": "PS::b",
        },
        current,
    )
    assert not features_v2._canonical_tof_sampling_rate_matches(
        {
            "sampling_rate_hz": 40_000_000.0,
            "sampling_rate_verified": True,
            "parameter_set_id": "PS::a",
        },
        current,
    )


def test_missing_label_artifact_returns_recovery_action(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    events_dir = tmp_path / "multimodal" / "CELL_X" / "EXP_X"
    events_dir.mkdir(parents=True)
    pd.DataFrame({"measurement_event_id": ["ME::1"]}).to_parquet(
        events_dir / "measurement_events.parquet", index=False
    )
    (events_dir / "measurement_event_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(features_v2, "assert_processed_artifact_integrity", lambda *_args, **_kwargs: {})
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                workbench_service=SimpleNamespace(
                    raw_root=tmp_path / "raw",
                    processed_root=tmp_path,
                )
            )
        )
    )

    with pytest.raises(APIError) as exc_info:
        features_v2._load_events_labels(request, "CELL_X", "EXP_X")

    assert exc_info.value.code == ErrorCode.SCIENTIFIC_READINESS_BLOCKED
    assert exc_info.value.details == {
        "target_id": "reference_soc_percent",
        "recovery_action": "RUN_LABEL_GENERATION",
        "recommended_profile": "FULL_PRE_MODEL",
    }
    assert "标签生成流程" in exc_info.value.message


def test_feature_label_preview_preserves_same_local_frame_per_asset(
    tmp_path, monkeypatch
) -> None:
    processed = tmp_path / "processed"
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=processed,
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
    frames_dir = processed / "ultrasound" / "CELL_X" / "EXP_X"
    frames_dir.mkdir(parents=True)
    events[["ultrasound_asset_id", "frame_index_raw"]].to_parquet(
        frames_dir / "frames.parquet", index=False
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


@pytest.mark.parametrize(
    ("events_ids", "label_ids", "artifact"),
    [
        (["ME::1", "ME::1"], ["ME::1"], "MeasurementEvent"),
        (["ME::1", "ME::2"], ["ME::1", "ME::1"], "event labels"),
    ],
)
def test_correlation_join_rejects_duplicate_event_identity(
    events_ids, label_ids, artifact, monkeypatch
) -> None:
    from types import SimpleNamespace

    events = pd.DataFrame(
        {
            "measurement_event_id": events_ids,
            "cycle_index_raw": [1, 1],
            "step_index_raw": [1, 1],
            "step_type": ["恒流充电", "恒流充电"],
            "analysis_eligible": [True, True],
        }
    )
    labels = pd.DataFrame(
        {
            "measurement_event_id": label_ids,
            "soc_reference_percent": [50.0] * len(label_ids),
        }
    )
    monkeypatch.setattr(
        features_v2, "_load_events_labels", lambda *_args: (events, labels)
    )
    request = SimpleNamespace()

    with pytest.raises(APIError) as exc_info:
        features_v2._correlation_rows(
            request, "CELL_X", "EXP_X", np.asarray([1.0, 2.0]), "SWA"
        )

    assert exc_info.value.code == ErrorCode.INTEGRITY_ERROR
    assert exc_info.value.details["artifact"] == artifact
    assert exc_info.value.details["integrity_reasons"] == ["MEASUREMENT_EVENT_ID_DUPLICATE"]


@pytest.mark.parametrize(
    ("events_ids", "label_ids", "artifact", "reason"),
    [
        (["ME::1", "ME::1"], ["ME::1"], "MeasurementEvent", "MEASUREMENT_EVENT_ID_DUPLICATE"),
        (["  "], ["  "], "MeasurementEvent", "MEASUREMENT_EVENT_ID_INVALID"),
        (["ME::1", "ME::2"], ["ME::1", "ME::1"], "event labels", "MEASUREMENT_EVENT_ID_DUPLICATE"),
        (["ME::1"], [" ME::1 "], "event labels", "MEASUREMENT_EVENT_ID_INVALID"),
    ],
)
def test_shared_event_label_join_rejects_duplicate_identity(
    events_ids, label_ids, artifact, reason
) -> None:
    events = pd.DataFrame({"measurement_event_id": events_ids, "value": [1] * len(events_ids)})
    labels = pd.DataFrame(
        {"measurement_event_id": label_ids, "soc_reference_percent": [50.0] * len(label_ids)}
    )

    with pytest.raises(APIError) as exc_info:
        features_v2._merge_event_labels(events, labels)

    assert exc_info.value.code == ErrorCode.INTEGRITY_ERROR
    assert exc_info.value.details["artifact"] == artifact
    assert exc_info.value.details["integrity_reasons"] == [reason]


def test_shared_event_label_join_preserves_event_rows_and_missing_labels() -> None:
    events = pd.DataFrame({"measurement_event_id": ["ME::1", "ME::2"], "value": [1, 2]})
    labels = pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "soc_reference_percent": [50.0]}
    )

    joined = features_v2._merge_event_labels(events, labels)

    assert joined["measurement_event_id"].tolist() == ["ME::1", "ME::2"]
    assert joined["value"].tolist() == [1, 2]
    assert joined["soc_reference_percent"].iloc[0] == 50.0
    assert pd.isna(joined["soc_reference_percent"].iloc[1])

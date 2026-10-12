from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.routes.features_v2 import _declared_condition_analysis
from battery_workbench.features.state_correlation import FeatureStateRow
from battery_workbench.multimodal.event_id import build_measurement_event_id


def _prepare_roots(
    root: Path,
    *,
    event_asset_id: str = "U001",
    segment_asset_id: str = "U001",
    include_segment: bool = True,
) -> tuple[SimpleNamespace, list[FeatureStateRow]]:
    raw_root = root / "raw"
    manifests = raw_root / "manifests"
    evidence = raw_root / "evidence" / "condition-log.txt"
    annotations = root / "annotations" / "CELL_A" / "EXP_01"
    processed_root = root / "processed"
    events_dir = processed_root / "multimodal" / "CELL_A" / "EXP_01"
    manifests.mkdir(parents=True)
    evidence.parent.mkdir(parents=True)
    events_dir.mkdir(parents=True)
    annotations.mkdir(parents=True)
    evidence.write_text("operator-declared condition log\n", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    asset_ids = {event_asset_id, segment_asset_id}
    with (manifests / "data_assets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "asset_id", "battery_id", "experiment_id", "modality", "relative_path",
                "file_start_time", "file_end_time",
            ],
        )
        writer.writeheader()
        for asset_id in sorted(asset_ids):
            writer.writerow(
                {
                    "asset_id": asset_id,
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_01",
                    "modality": "ultrasound",
                    "relative_path": f"batteries/CELL_A/EXP_01/ultrasound/{asset_id}.txt",
                    "file_start_time": "2026-01-01T00:00:00+00:00",
                    "file_end_time": "2026-01-01T01:00:00+00:00",
                }
            )

    if include_segment:
        with (annotations / "condition_segments.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "segment_id", "battery_id", "experiment_id", "condition_axis_id",
                    "condition_value", "unit", "time_reference_asset_id", "start_time",
                    "end_time", "evidence_relative_path", "evidence_sha256", "declared_by",
                    "declared_at",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "segment_id": "SEG_25C",
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_01",
                    "condition_axis_id": "temperature_setpoint",
                    "condition_value": "25",
                    "unit": "degC",
                    "time_reference_asset_id": segment_asset_id,
                    "start_time": "2026-01-01T00:00:00+00:00",
                    "end_time": "2026-01-01T00:10:00+00:00",
                    "evidence_relative_path": "evidence/condition-log.txt",
                    "evidence_sha256": digest,
                    "declared_by": "operator-1",
                    "declared_at": "2026-01-02T00:00:00+00:00",
                }
            )

    event_rows = [
        {
            "measurement_event_id": build_measurement_event_id(
                "CELL_A", "EXP_01", event_asset_id, i
            ),
            "battery_id": "CELL_A",
            "experiment_id": "EXP_01",
            "ultrasound_asset_id": event_asset_id,
            "frame_index_raw": i,
            "event_order_index": i,
            "provisional_absolute_timestamp": datetime(2026, 1, 1, 0, i, tzinfo=UTC),
            "match_status": "MATCHED_UNIQUE",
            "event_quality_status": "READY",
            "analysis_eligible": True,
        }
        for i in range(1, 4)
    ]
    events_path = events_dir / "measurement_events.parquet"
    candidates_path = events_dir / "measurement_event_candidates.parquet"
    event_frame = pd.DataFrame(event_rows)
    event_frame.to_parquet(events_path, index=False)
    pd.DataFrame(columns=["measurement_event_id", "electrical_record_locator"]).to_parquet(
        candidates_path, index=False
    )
    source_dir = processed_root / "fixture_sources"
    source_dir.mkdir()
    source_paths = {
        name: source_dir / f"{name}.bin"
        for name in ("aligned", "sync_candidates", "electrical_records")
    }
    for path in source_paths.values():
        path.write_bytes(path.name.encode("utf-8"))
    (events_dir / "measurement_event_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_01",
                "builder_version": "test",
                "input_paths": {
                    name: str(path.relative_to(processed_root))
                    for name, path in source_paths.items()
                },
                "input_checksums": {
                    name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in source_paths.items()
                },
                "output_paths": {
                    "events": str(events_path.relative_to(processed_root)),
                    "candidates": str(candidates_path.relative_to(processed_root)),
                },
                "output_checksums": {
                    "events": hashlib.sha256(events_path.read_bytes()).hexdigest(),
                    "candidates": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                workbench_service=SimpleNamespace(raw_root=raw_root, processed_root=processed_root)
            )
        )
    )
    rows = [
        FeatureStateRow(
            measurement_event_id=build_measurement_event_id(
                "CELL_A", "EXP_01", event_asset_id, i
            ),
            battery_id="CELL_A",
            experiment_id="EXP_01",
            cycle=1,
            step=1,
            state="charge",
            timestamp_s=float(i * 60),
            feature_code="SWA",
            value=float(i),
            reference_soc_percent=float(i * 10),
        )
        for i in range(1, 4)
    ]
    return request, rows


def test_condition_analysis_api_helper_returns_audited_same_asset_slices(tmp_path: Path) -> None:
    request, rows = _prepare_roots(tmp_path)

    result = _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert result["status"] == "AVAILABLE"
    assert result["declaration_status"] == "OPERATOR_DECLARED"
    assert result["absolute_timebase_status"] == "NOT_ASSESSED"
    assert result["synchronization_status"] == "NOT_ASSESSED"
    assert result["segment_count"] == 1
    assert result["events_assessed"] == 3
    assert result["assignment_status_counts"] == {
        "ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK": 3
    }
    assert len(result["results"]) == 2
    pearson = next(row for row in result["results"] if row["method"] == "pearson")
    assert pearson["coefficient"] == pytest.approx(1.0)
    assert pearson["n_valid_pairs"] == 3
    assert pearson["group_count_semantics"] == "DECLARED_BATTERY_ID"
    assert pearson["battery_identity_status"] == "NOT_ASSESSED"
    assert pearson["physical_battery_count"] is None
    assert pearson["segment_ids"] == ["SEG_25C"]


def test_condition_analysis_api_helper_blocks_cross_asset_clock_transfer(tmp_path: Path) -> None:
    request, rows = _prepare_roots(
        tmp_path,
        event_asset_id="U001",
        segment_asset_id="U002",
    )

    result = _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert result["status"] == "AVAILABLE"
    assert result["assignment_status_counts"] == {"BLOCKED_CROSS_ASSET_TIMEBASE": 3}
    assert result["results"] == []


def test_condition_analysis_api_helper_blocks_tampered_measurement_events(
    tmp_path: Path,
) -> None:
    request, rows = _prepare_roots(tmp_path)
    events_path = (
        request.app.state.workbench_service.processed_root
        / "multimodal"
        / "CELL_A"
        / "EXP_01"
        / "measurement_events.parquet"
    )
    events_path.write_bytes(events_path.read_bytes() + b"tampered")

    with pytest.raises(APIError) as exc_info:
        _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert exc_info.value.details.get("integrity_reasons") == [
        "OUTPUT_CHECKSUM_MISMATCH:events"
    ]


@pytest.mark.parametrize("invalid_id", [None, "", " ME1 "])
def test_condition_analysis_api_helper_rejects_invalid_event_identity(
    tmp_path: Path, invalid_id: str | None,
) -> None:
    request, rows = _prepare_roots(tmp_path)
    processed_root = request.app.state.workbench_service.processed_root
    events_dir = processed_root / "multimodal" / "CELL_A" / "EXP_01"
    events_path = events_dir / "measurement_events.parquet"
    events = pd.read_parquet(events_path)
    events.loc[events.index[0], "measurement_event_id"] = invalid_id
    events.to_parquet(events_path, index=False)

    manifest_path = events_dir / "measurement_event_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_checksums"]["events"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(APIError) as exc_info:
        _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert "measurement_event_id" in exc_info.value.details["reason"]


def test_condition_analysis_api_helper_rejects_feature_rows_without_canonical_event(
    tmp_path: Path,
) -> None:
    request, rows = _prepare_roots(tmp_path)
    rows.append(
        rows[0].model_copy(
            update={
                "measurement_event_id": "ME_NOT_IN_CANONICAL_EVENTS",
                "value": 99.0,
            }
        )
    )

    with pytest.raises(APIError) as exc_info:
        _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert "feature rows reference unknown MeasurementEvent identities" in exc_info.value.details[
        "reason"
    ]


def test_condition_analysis_api_helper_rejects_event_id_asset_frame_mismatch(
    tmp_path: Path,
) -> None:
    request, rows = _prepare_roots(tmp_path, segment_asset_id="U002")
    processed_root = request.app.state.workbench_service.processed_root
    events_dir = processed_root / "multimodal" / "CELL_A" / "EXP_01"
    events_path = events_dir / "measurement_events.parquet"
    events = pd.read_parquet(events_path)
    events.loc[events.index[0], "ultrasound_asset_id"] = "U002"
    events.to_parquet(events_path, index=False)

    manifest_path = events_dir / "measurement_event_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_checksums"]["events"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(APIError) as exc_info:
        _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert "does not match its composite frame identity" in exc_info.value.details["reason"]


def test_condition_analysis_api_helper_marks_missing_manifest_not_configured(
    tmp_path: Path,
) -> None:
    request, rows = _prepare_roots(tmp_path, include_segment=False)
    legacy_raw_manifest = (
        request.app.state.workbench_service.raw_root
        / "manifests"
        / "condition_segments.csv"
    )
    legacy_raw_manifest.write_text("must not be treated as writable annotations\n", encoding="utf-8")

    result = _declared_condition_analysis(request, "CELL_A", "EXP_01", rows)

    assert result["status"] == "NOT_CONFIGURED"
    assert result["declaration_status"] == "NOT_CONFIGURED"
    assert result["results"] == []

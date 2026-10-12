from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from battery_workbench.conditions.assignment import assign_condition_segments_to_events
from battery_workbench.conditions.segments import (
    ConditionSegment,
    ConditionSegmentValidation,
    load_condition_segments,
)
from battery_workbench.domain.asset import DataAsset
from battery_workbench.multimodal.schemas import CanonicalMeasurementEvent

FIELDS = [
    "segment_id",
    "battery_id",
    "experiment_id",
    "condition_axis_id",
    "condition_value",
    "unit",
    "time_reference_asset_id",
    "start_time",
    "end_time",
    "evidence_relative_path",
    "evidence_sha256",
    "declared_by",
    "declared_at",
]


def _asset(
    *,
    battery_id: str = "CELL_A",
    start_time: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    end_time: datetime = datetime(2026, 1, 1, 1, tzinfo=UTC),
) -> DataAsset:
    return DataAsset(
        asset_id="U001",
        battery_id=battery_id,
        experiment_id="EXP_01",
        modality="ultrasound",
        relative_path=Path("batteries/CELL_A/EXP_01/ultrasound/wave.txt"),
        file_start_time=start_time,
        file_end_time=end_time,
    )


def _row(
    raw_root: Path,
    *,
    segment_id: str = "S1",
    start: str = "2026-01-01T00:00:00+00:00",
    end: str = "2026-01-01T00:10:00+00:00",
    axis: str = "temperature_setpoint",
    battery_id: str = "CELL_A",
    asset_id: str = "U001",
    unit: str = "degC",
    evidence_path: str = "evidence/run-log.txt",
    evidence_sha256: str | None = None,
) -> dict[str, str]:
    evidence = raw_root / evidence_path
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("operator log\n", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    return {
        "segment_id": segment_id,
        "battery_id": battery_id,
        "experiment_id": "EXP_01",
        "condition_axis_id": axis,
        "condition_value": "25",
        "unit": unit,
        "time_reference_asset_id": asset_id,
        "start_time": start,
        "end_time": end,
        "evidence_relative_path": evidence_path,
        "evidence_sha256": evidence_sha256 or digest,
        "declared_by": "operator-1",
        "declared_at": "2026-01-02T00:00:00+00:00",
    }


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_condition_segments_accept_adjacent_explicit_intervals_and_keep_declared_status(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    first = _row(raw_root)
    second = _row(
        raw_root,
        segment_id="S2",
        start="2026-01-01T00:10:00+00:00",
        end="2026-01-01T00:20:00+00:00",
    )
    manifest = _write_manifest(tmp_path / "condition_segments.csv", [first, second])

    result = load_condition_segments(
        manifest,
        raw_root=raw_root,
        data_assets=[_asset()],
    )

    assert [item.segment.segment_id for item in result] == ["S1", "S2"]
    assert all(item.segment.declaration_status == "OPERATOR_DECLARED" for item in result)
    assert all(item.segment.time_reference_asset_id == "U001" for item in result)
    assert all(item.asset_window_status == "WITHIN_DECLARED_ASSET_WINDOW" for item in result)
    assert all(item.absolute_timebase_status == "NOT_ASSESSED" for item in result)
    assert all(item.synchronization_status == "NOT_ASSESSED" for item in result)
    assert all(item.measurement_event_assignment_status == "NOT_IMPLEMENTED" for item in result)

    blank_unit = _write_manifest(
        tmp_path / "condition_segments_no_unit.csv",
        [_row(raw_root, segment_id="S3", unit="")],
    )
    without_unit = load_condition_segments(blank_unit, raw_root=raw_root, data_assets=[_asset()])
    assert without_unit[0].segment.unit is None


def test_condition_segments_reject_overlapping_intervals_for_same_axis(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    rows = [
        _row(raw_root, segment_id="S1", start="2026-01-01T00:00:00+00:00", end="2026-01-01T00:20:00+00:00"),
        _row(raw_root, segment_id="S2", start="2026-01-01T00:10:00+00:00", end="2026-01-01T00:30:00+00:00"),
    ]
    manifest = _write_manifest(tmp_path / "condition_segments.csv", rows)

    with pytest.raises(ValueError, match="overlapping condition segments"):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[_asset()])


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2025-12-31T23:59:00+00:00", "2026-01-01T00:10:00+00:00", "outside DataAsset"),
        ("2026-01-01T00:10:00+00:00", "2026-01-01T01:01:00+00:00", "outside DataAsset"),
        ("2026-01-01T00:10:00", "2026-01-01T00:20:00", "explicit UTC offset"),
    ],
)
def test_condition_segments_reject_unbounded_or_timezone_naive_ranges(
    tmp_path: Path,
    start: str,
    end: str,
    message: str,
) -> None:
    raw_root = tmp_path / "raw"
    manifest = _write_manifest(
        tmp_path / "condition_segments.csv",
        [_row(raw_root, start=start, end=end)],
    )

    with pytest.raises(ValueError, match=message):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[_asset()])


def test_condition_segments_require_matching_composite_asset_identity(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = _write_manifest(
        tmp_path / "condition_segments.csv",
        [_row(raw_root, battery_id="CELL_B")],
    )

    with pytest.raises(ValueError, match="same Battery/Experiment identity"):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[_asset()])


def test_condition_segments_reject_invalid_reference_asset_time_bounds(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = _write_manifest(
        tmp_path / "condition_segments.csv",
        [_row(raw_root)],
    )
    invalid_asset = _asset(
        start_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="has invalid time bounds"):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[invalid_asset])


def test_condition_segments_verify_evidence_hash_and_confine_paths_to_raw_root(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    mismatch = _row(raw_root, evidence_sha256="0" * 64)
    manifest = _write_manifest(tmp_path / "condition_segments.csv", [mismatch])
    with pytest.raises(ValueError, match="evidence checksum mismatch"):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[_asset()])

    unsafe_root = tmp_path / "raw_unsafe"
    unsafe = _row(unsafe_root, evidence_path="../outside.txt")
    unsafe_manifest = _write_manifest(tmp_path / "unsafe_condition_segments.csv", [unsafe])
    with pytest.raises(ValueError, match="must be relative to raw_root"):
        load_condition_segments(unsafe_manifest, raw_root=unsafe_root, data_assets=[_asset()])


def test_condition_segments_require_unique_ids_within_experiment(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    rows = [_row(raw_root, segment_id="S1"), _row(raw_root, segment_id="S1", axis="rate")]
    manifest = _write_manifest(tmp_path / "condition_segments.csv", rows)

    with pytest.raises(ValueError, match="segment_id must be unique"):
        load_condition_segments(manifest, raw_root=raw_root, data_assets=[_asset()])


def _validated_segment(
    *, segment_id: str, asset_id: str, start: datetime, end: datetime, value: str
) -> ConditionSegmentValidation:
    segment = ConditionSegment(
        segment_id=segment_id,
        battery_id="CELL_A",
        experiment_id="EXP_01",
        condition_axis_id="temperature_setpoint",
        condition_value=value,
        unit="degC",
        time_reference_asset_id=asset_id,
        start_time=start,
        end_time=end,
        evidence_relative_path="evidence/run-log.txt",
        evidence_sha256="a" * 64,
        declared_by="operator-1",
        declared_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    return ConditionSegmentValidation(
        segment=segment,
        asset_window_status="WITHIN_DECLARED_ASSET_WINDOW",
    )


def _event(
    *, asset_id: str = "U001", timestamp: datetime | None
) -> CanonicalMeasurementEvent:
    return CanonicalMeasurementEvent(
        measurement_event_id="EVT_001",
        battery_id="CELL_A",
        experiment_id="EXP_01",
        ultrasound_asset_id=asset_id,
        frame_index_raw=1,
        event_order_index=0,
        provisional_absolute_timestamp=timestamp,
        match_status="MATCHED_AMBIGUOUS",
        event_quality_status="AMBIGUOUS_SYNC",
    )


def test_condition_assignment_requires_same_asset_clock_and_preserves_unverified_status() -> None:
    item = _validated_segment(
        segment_id="S1",
        asset_id="U001",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        value="25",
    )
    event = _event(timestamp=datetime(2026, 1, 1, 0, 5, tzinfo=UTC))

    result = assign_condition_segments_to_events([item], [event])

    assert len(result) == 1
    assert result[0].status == "ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK"
    assert result[0].condition_value == "25"
    assert result[0].segment_id == "S1"
    assert result[0].absolute_timebase_status == "NOT_ASSESSED"
    assert result[0].synchronization_status == "NOT_ASSESSED"
    assert event.analysis_eligible is False
    assert event.match_status == "MATCHED_AMBIGUOUS"


def test_condition_assignment_blocks_cross_asset_clock_even_for_overlapping_values() -> None:
    item = _validated_segment(
        segment_id="S1",
        asset_id="U002",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        value="25",
    )
    event = _event(asset_id="U001", timestamp=datetime(2026, 1, 1, 0, 5, tzinfo=UTC))

    result = assign_condition_segments_to_events([item], [event])

    assert len(result) == 1
    assert result[0].status == "BLOCKED_CROSS_ASSET_TIMEBASE"
    assert result[0].condition_value is None
    assert result[0].time_reference_asset_id == "U002"


def test_condition_assignment_uses_half_open_boundaries_and_leaves_gaps_unclassified() -> None:
    first = _validated_segment(
        segment_id="S1",
        asset_id="U001",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        value="25",
    )
    second = _validated_segment(
        segment_id="S2",
        asset_id="U001",
        start=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 20, tzinfo=UTC),
        value="30",
    )
    boundary_event = _event(timestamp=datetime(2026, 1, 1, 0, 10, tzinfo=UTC))
    gap_event = _event(timestamp=datetime(2026, 1, 1, 0, 30, tzinfo=UTC))

    boundary, gap = assign_condition_segments_to_events(
        [first, second], [boundary_event, gap_event]
    )

    assert boundary.segment_id == "S2"
    assert boundary.condition_value == "30"
    assert gap.status == "UNCLASSIFIED_NO_SEGMENT"


def test_condition_assignment_rejects_naive_event_time_and_detects_conflicting_input() -> None:
    segment = _validated_segment(
        segment_id="S1",
        asset_id="U001",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        value="25",
    )
    conflict = _validated_segment(
        segment_id="S2",
        asset_id="U001",
        start=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 15, tzinfo=UTC),
        value="30",
    )
    naive_event = _event(timestamp=datetime(2026, 1, 1, 0, 6))
    missing_event = _event(timestamp=None)
    aware_event = _event(timestamp=datetime(2026, 1, 1, 0, 6, tzinfo=UTC))

    naive, missing, ambiguous = assign_condition_segments_to_events(
        [segment, conflict], [naive_event, missing_event, aware_event]
    )

    assert naive.status == "BLOCKED_TIMESTAMP_UNAVAILABLE"
    assert missing.status == "BLOCKED_TIMESTAMP_UNAVAILABLE"
    assert ambiguous.status == "CONFLICTING_SEGMENTS"

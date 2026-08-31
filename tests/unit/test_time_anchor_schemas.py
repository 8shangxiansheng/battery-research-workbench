from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from battery_workbench.synchronization.schemas import (
    AssetAnchorAssessment,
    CoverageDiagnostics,
    ExperimentTimeReference,
    TimeAnchorCandidate,
    TimeAnchorEvidence,
    TimeAnchorReport,
    TimeAnchorState,
)


def test_naive_datetime_stays_naive() -> None:
    """T01: a naive input datetime is preserved without attaching timezone."""
    candidate = TimeAnchorCandidate(
        anchor_id="a1",
        asset_id="U001",
        anchor_datetime=datetime(2024, 1, 6, 9, 52, 31),
        elapsed_time_s_at_anchor=0.0,
        source_type="MANIFEST_FILE_START",
        source_ref="data_assets.csv",
        status="PROVISIONAL",
    )
    assert candidate.anchor_datetime.tzinfo is None
    assert candidate.timezone_known is False
    assert candidate.timezone_name is None


def test_candidate_status_enum_values() -> None:
    """Candidate status must be one of the allowed statuses."""
    valid = {"UNVERIFIED", "PROVISIONAL", "CONFLICTING", "MANUALLY_ACCEPTED", "REJECTED"}
    for value in valid:
        candidate = TimeAnchorCandidate(
            anchor_id="a1",
            asset_id="U001",
            anchor_datetime=datetime(2024, 1, 6, 9, 52, 31),
            elapsed_time_s_at_anchor=0.0,
            source_type="MANIFEST_FILE_START",
            source_ref="data_assets.csv",
            status=value,  # type: ignore[arg-type]
        )
        assert candidate.status == value


def test_invalid_candidate_status_rejected() -> None:
    with pytest.raises(ValidationError):
        TimeAnchorCandidate(
            anchor_id="a1",
            asset_id="U001",
            anchor_datetime=datetime(2024, 1, 6, 9, 52, 31),
            elapsed_time_s_at_anchor=0.0,
            source_type="MANIFEST_FILE_START",
            source_ref="data_assets.csv",
            status="SYNC_VERIFIED",  # type: ignore[arg-type]
        )


def test_report_status_literal() -> None:
    for value in ("PASS", "PASS_WITH_WARNINGS", "FAIL"):
        report = TimeAnchorReport(
            battery_id="CELL_001",
            experiment_id="EXP_001",
            anchor_version="0.1.0",
            status=value,  # type: ignore[arg-type]
            assets=[],
            warnings=[],
            limitations=[],
            validated_sync=False,
        )
        assert report.status == value


def test_reference_timezone_defaults_unknown() -> None:
    reference = ExperimentTimeReference(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        experiment_start_time=datetime(2024, 1, 6, 9, 52, 31),
        experiment_end_time=datetime(2024, 1, 6, 20, 58, 54),
    )
    assert reference.timezone_known is False
    assert reference.timezone_name is None
    assert reference.electrical_start_time is None
    assert reference.electrical_end_time is None


def test_coverage_diagnostics_fields() -> None:
    coverage = CoverageDiagnostics(
        candidate_start=datetime(2024, 1, 6, 9, 52, 31, 31217),
        candidate_end=datetime(2024, 1, 6, 20, 58, 51),
        start_residual_s=0.031217,
        end_residual_s=-2.97,
        duration_residual_s=-3.001217,
        overlap_duration_s=39979.998783,
        coverage_overlap_fraction=1.0,
    )
    assert coverage.coverage_overlap_fraction == 1.0


def test_evidence_expression() -> None:
    evidence = TimeAnchorEvidence(
        evidence_id="e1",
        asset_id="U001",
        source_type="MANIFEST_FILE_START",
        source_ref="data_assets.csv",
        raw_value="2024-01-06 09:52:31",
        parsed_value=datetime(2024, 1, 6, 9, 52, 31),
        message="manifest file_start_time",
    )
    assert evidence.source_type == "MANIFEST_FILE_START"
    assert evidence.parsed_value is not None


def test_asset_assessment_defaults_validated_false() -> None:
    assessment = AssetAnchorAssessment(
        asset_id="U001",
        modality="ultrasound",
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        candidates=[],
        selected_anchor_id=None,
        anchor_status=None,
        coverage=None,
        conflicts=[],
    )
    assert assessment.validated_sync is False


def test_canonical_state_minimal_contract() -> None:
    """T17: the canonical time_anchors.json structure has the required keys."""
    state = TimeAnchorState(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        anchor_version="0.1.0",
        experiment_reference={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "experiment_start_time": None,
            "experiment_end_time": None,
        },
        assets=[
            AssetAnchorAssessment(
                asset_id="U001",
                modality="ultrasound",
                elapsed_min_s=0.031217,
                elapsed_max_s=39980.03,
            )
        ],
        warnings=[],
        limitations=[],
        validated_sync=False,
    )
    payload = state.model_dump(mode="json")
    assert set(payload) == {
        "battery_id",
        "experiment_id",
        "anchor_version",
        "experiment_reference",
        "assets",
        "warnings",
        "limitations",
        "validated_sync",
    }
    assert payload["validated_sync"] is False

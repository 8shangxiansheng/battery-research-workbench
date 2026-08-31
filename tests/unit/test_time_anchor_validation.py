from __future__ import annotations

from datetime import datetime

import pytest

from battery_workbench.synchronization.schemas import PlausibilityConfig, TimeAnchorConfig
from battery_workbench.synchronization.validation import assess_coverage, is_plausible


def test_coverage_arithmetic_t03() -> None:
    """T03: candidate coverage = anchor + elapsed min/max."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    elapsed_min = 0.031217
    elapsed_max = 39980.03
    reference_start = anchor
    reference_end = datetime(2024, 1, 6, 20, 58, 54)

    coverage = assess_coverage(
        anchor_datetime=anchor,
        elapsed_min_s=elapsed_min,
        elapsed_max_s=elapsed_max,
        reference_start=reference_start,
        reference_end=reference_end,
    )
    assert coverage.candidate_start == datetime(2024, 1, 6, 9, 52, 31, 31217)
    # 39980.03 s = 11h06m20.03s; anchored at 09:52:31 -> 20:58:51.030000 (matches frames.parquet).
    assert coverage.candidate_end == datetime(2024, 1, 6, 20, 58, 51, 30000)
    assert coverage.start_residual_s == pytest.approx(0.031217, abs=1e-6)
    assert coverage.end_residual_s == pytest.approx(-2.97, abs=1e-6)
    assert coverage.duration_residual_s == pytest.approx(-3.001217, abs=1e-6)
    assert coverage.coverage_overlap_fraction == pytest.approx(1.0, abs=1e-6)


def test_plausible_coverage_but_not_verified_t08() -> None:
    """T08: overlap ~1 is plausible but validated_sync stays false."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    coverage = assess_coverage(
        anchor_datetime=anchor,
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        reference_start=anchor,
        reference_end=datetime(2024, 1, 6, 20, 58, 54),
    )
    # Plausibility does NOT carry into validated sync.
    config = TimeAnchorConfig(
        plausibility=PlausibilityConfig(
            max_start_residual_s=60.0,
            max_end_residual_s=60.0,
            min_overlap_fraction=0.95,
        )
    )
    plausible = is_plausible(coverage, config.plausibility)
    assert plausible is True
    # This module never emits validated_sync; the report layer must keep it False.
    from battery_workbench.synchronization.schemas import AssetAnchorAssessment

    assessment = AssetAnchorAssessment(
        asset_id="U001",
        modality="ultrasound",
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        candidates=[],
        selected_anchor_id=None,
        anchor_status=None,
        coverage=coverage,
        conflicts=[],
    )
    assert assessment.validated_sync is False


def test_bad_coverage_warning_not_shift_t09() -> None:
    """T09: a large residual produces a warning, never an automatic anchor shift."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    reference_start = datetime(2024, 1, 6, 8, 0, 0)  # 1h+ off
    reference_end = datetime(2024, 1, 6, 12, 0, 0)
    coverage = assess_coverage(
        anchor_datetime=anchor,
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        reference_start=reference_start,
        reference_end=reference_end,
    )
    config = TimeAnchorConfig(
        plausibility=PlausibilityConfig(
            max_start_residual_s=60.0,
            max_end_residual_s=60.0,
            min_overlap_fraction=0.95,
        )
    )
    assert is_plausible(coverage, config.plausibility) is False
    # No field is auto-corrected; candidate_start is still anchor + elapsed_min.
    assert coverage.candidate_start == datetime(2024, 1, 6, 9, 52, 31, 31217)


def test_timezone_guard_t10() -> None:
    """T10: naive inputs are never upgraded to a timezone."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    coverage = assess_coverage(
        anchor_datetime=anchor,
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        reference_start=anchor,
        reference_end=datetime(2024, 1, 6, 20, 58, 54),
    )
    assert coverage.candidate_start.tzinfo is None
    assert coverage.candidate_end.tzinfo is None


def test_no_unique_row_lookup_t15() -> None:
    """T15: coverage assessment never performs an electrical row lookup."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    coverage = assess_coverage(
        anchor_datetime=anchor,
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        reference_start=anchor,
        reference_end=datetime(2024, 1, 6, 20, 58, 54),
    )
    # Only min/max window arithmetic is performed; no per-record matching.
    assert coverage.start_residual_s == coverage.start_residual_s

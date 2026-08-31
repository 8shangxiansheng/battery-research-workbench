"""Coverage plausibility diagnostics & timezone guard for BRW-008.

Computes the *mechanical* candidate coverage ``anchor + elapsed`` and compares
it to a reference window. Plausibility is a diagnostic only — it never marks an
anchor as verified synchronization.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from battery_workbench.synchronization.schemas import (
    CoverageDiagnostics,
    PlausibilityConfig,
)


def assess_coverage(
    *,
    anchor_datetime: datetime,
    elapsed_min_s: float,
    elapsed_max_s: float,
    reference_start: datetime,
    reference_end: datetime,
) -> CoverageDiagnostics:
    """Compute candidate coverage and its residuals vs. a reference window.

    Definitions:
      candidate_start = anchor + elapsed_min_s
      candidate_end   = anchor + elapsed_max_s
      start_residual_s     = candidate_start - reference_start
      end_residual_s       = candidate_end - reference_end
      duration_residual_s  = candidate_duration - reference_duration
      overlap_duration_s   = len([candidate ∩ reference])
      coverage_overlap_fraction = overlap_duration / candidate_duration

    Datetimes stay naive; no timezone is attached.
    """
    candidate_start = anchor_datetime + timedelta(seconds=elapsed_min_s)
    candidate_end = anchor_datetime + timedelta(seconds=elapsed_max_s)
    candidate_duration = max(0.0, (candidate_end - candidate_start).total_seconds())
    reference_duration = max(0.0, (reference_end - reference_start).total_seconds())

    overlap_start = max(candidate_start, reference_start)
    overlap_end = min(candidate_end, reference_end)
    overlap_duration = max(0.0, (overlap_end - overlap_start).total_seconds())
    overlap_fraction = (overlap_duration / candidate_duration) if candidate_duration > 0 else 0.0

    return CoverageDiagnostics(
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        start_residual_s=(candidate_start - reference_start).total_seconds(),
        end_residual_s=(candidate_end - reference_end).total_seconds(),
        duration_residual_s=candidate_duration - reference_duration,
        overlap_duration_s=overlap_duration,
        coverage_overlap_fraction=overlap_fraction,
    )


def is_plausible(coverage: CoverageDiagnostics, config: PlausibilityConfig) -> bool:
    """Threshold-only diagnostic. Plausible !== verified synchronization."""
    within_start = abs(coverage.start_residual_s) <= config.max_start_residual_s
    within_end = abs(coverage.end_residual_s) <= config.max_end_residual_s
    enough_overlap = coverage.coverage_overlap_fraction >= config.min_overlap_fraction
    return within_start and within_end and enough_overlap

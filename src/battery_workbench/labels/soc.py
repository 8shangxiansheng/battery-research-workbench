"""SOC reference label V2 (BRW-014 remediation).

V2 contract — protocol-anchored, direction-specific segment normalization:

    CHARGE:    SOC = 100 * Q_charged_since_empty   / Q_charge_segment_total
    DISCHARGE: SOC = 100 * (1 - Q_discharged_since_full / Q_discharge_segment_total)
    REST:      SOC = previous valid segment-end SOC (propagated, same cycle only)

Both directions share one physical semantic: 0 = empty, 100 = full. Because
each segment is normalized by its OWN measured segment total, the definition
is self-bounded to [0, 100] — no clipping. The V1-style integral (charge
normalized by the *discharge* capacity, implying CE=1) is preserved only as
``soc_integral_unbounded_percent`` — a diagnostic, never a target.

Temporality: ``RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE`` — denominators are
segment totals known only after the segment completes.
"""

from __future__ import annotations

from dataclasses import dataclass

# Documented numerical tolerance: a value mathematically at a segment boundary
# may overshoot by float noise; within this tolerance it is snapped to the
# boundary (this is float correction, not clipping of genuinely bad values).
BOUNDARY_TOLERANCE_PCT = 1e-6

_RETROSPECTIVE_V2 = "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"


@dataclass
class SocLabelResult:
    soc_reference_percent: float | None
    soc_reference_quality: str
    soc_label_temporality: str
    soc_label_eligible: bool
    soc_integral_unbounded_percent: float | None = None
    soc_anchor_quality: str | None = None


def _result(
    soc: float | None,
    quality: str,
    *,
    eligible: bool,
    temporality: str = _RETROSPECTIVE_V2,
    unbounded: float | None = None,
    anchor_quality: str | None = None,
) -> SocLabelResult:
    return SocLabelResult(
        soc_reference_percent=soc,
        soc_reference_quality=quality,
        soc_label_temporality=temporality,
        soc_label_eligible=eligible,
        soc_integral_unbounded_percent=unbounded,
        soc_anchor_quality=anchor_quality,
    )


def _snap_to_bounds(soc: float) -> tuple[float, bool]:
    """Snap float noise at the [0, 100] boundary; flag genuine overshoot."""
    if -BOUNDARY_TOLERANCE_PCT <= soc < 0.0:
        return 0.0, True
    if 100.0 < soc <= 100.0 + BOUNDARY_TOLERANCE_PCT:
        return 100.0, True
    if soc < 0.0 or soc > 100.0:
        return soc, False
    return soc, True


def compute_soc_reference(
    *,
    direction: str,
    q_progress_ah: float | None = None,
    q_segment_total_ah: float | None = None,
    prev_valid_soc: float | None = None,
    cycle_complete: bool = True,
    anchor_available: bool = True,
    anchor_quality: str | None = "REFERENCE_PROTOCOL_ANCHOR",
    diagnostic_unbounded_percent: float | None = None,
) -> SocLabelResult:
    """Compute one V2 SOC reference label.

    ``q_progress_ah``  — cumulative capacity within the active segment
                         (charged-since-empty for CHARGE, discharged-since-full
                         for DISCHARGE).
    ``q_segment_total_ah`` — the segment's own measured total (its denominator).
    ``prev_valid_soc`` — the segment-end SOC used for REST propagation.
    ``anchor_quality`` — caller-assigned context (ASSUMED_INITIAL_ANCHOR for the
                         experiment's first charge start, etc.).
    ``diagnostic_unbounded_percent`` — caller-computed V1-style integral,
                         preserved verbatim for audit; never drives eligibility.
    """
    if not cycle_complete:
        return _result(
            None,
            "INCOMPLETE_CYCLE",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )
    if not anchor_available:
        return _result(
            None,
            "ANCHOR_UNAVAILABLE",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )

    if direction == "REST":
        if prev_valid_soc is None:
            return _result(
                None,
                "ANCHOR_UNAVAILABLE",
                eligible=False,
                unbounded=diagnostic_unbounded_percent,
                anchor_quality="ANCHOR_UNAVAILABLE",
            )
        return _result(
            float(prev_valid_soc),
            "VALID_REFERENCE",
            eligible=True,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality="PROPAGATED_REST_ANCHOR",
        )

    if direction not in ("CHARGE", "DISCHARGE"):
        return _result(
            None,
            "AMBIGUOUS_PROTOCOL",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )

    if q_segment_total_ah is None or q_segment_total_ah <= 0:
        return _result(
            None,
            "REFERENCE_CAPACITY_UNAVAILABLE",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )
    if q_progress_ah is None:
        return _result(
            None,
            "ANCHOR_UNAVAILABLE",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )

    if direction == "CHARGE":
        soc_raw = 100.0 * q_progress_ah / q_segment_total_ah
    else:
        soc_raw = 100.0 * (1.0 - q_progress_ah / q_segment_total_ah)

    soc, in_bounds = _snap_to_bounds(soc_raw)
    if not in_bounds:
        return _result(
            soc,
            "OUT_OF_RANGE_REFERENCE",
            eligible=False,
            unbounded=diagnostic_unbounded_percent,
            anchor_quality=anchor_quality,
        )

    return _result(
        soc,
        "VALID_REFERENCE",
        eligible=True,
        unbounded=diagnostic_unbounded_percent,
        anchor_quality=anchor_quality,
    )

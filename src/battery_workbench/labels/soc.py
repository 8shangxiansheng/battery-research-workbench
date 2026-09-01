"""SOC reference label (COULOMB_COUNTING_PROTOCOL_ANCHORED).

V1 discharge formula:  ``SOC_ref = 100 * (1 - Q_discharged_since_full / Q_ref)``
V1 charge formula:     ``SOC_ref = 100 * Q_charged_since_empty / Q_ref``

No silent clipping: values outside [0, 100] are preserved and flagged
``OUT_OF_RANGE_REFERENCE``. Q_ref comes from the same cycle's measured
discharge capacity, which makes every label
``RETROSPECTIVE_FULL_CYCLE_REFERENCE`` (never online-causal).

The vendor ``soc_dod_percent`` field is never promoted here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SocLabelResult:
    soc_reference_percent: float | None
    soc_reference_quality: str
    soc_label_temporality: str
    soc_label_eligible: bool


_RETROSPECTIVE = "RETROSPECTIVE_FULL_CYCLE_REFERENCE"


def _result(
    soc: float | None,
    quality: str,
    *,
    eligible: bool,
    temporality: str = _RETROSPECTIVE,
) -> SocLabelResult:
    return SocLabelResult(
        soc_reference_percent=soc,
        soc_reference_quality=quality,
        soc_label_temporality=temporality,
        soc_label_eligible=eligible,
    )


def compute_soc_reference(
    *,
    direction: str,
    discharged_since_full_ah: float | None,
    charged_since_empty_ah: float | None,
    q_ref_ah: float | None,
    cycle_complete: bool,
    anchor_available: bool,
) -> SocLabelResult:
    """Compute one SOC reference label from protocol-anchored coulomb counting.

    ``direction`` is ``DISCHARGE`` / ``CHARGE`` / ``REST``. A zero or missing
    Q_ref is unusable. Missing anchors, incomplete cycles, and out-of-range
    results are explicit quality outcomes — never silently repaired.
    """
    if not cycle_complete:
        return _result(None, "INCOMPLETE_CYCLE", eligible=False)
    if not anchor_available:
        return _result(None, "ANCHOR_UNAVAILABLE", eligible=False)
    if q_ref_ah is None or q_ref_ah <= 0:
        return _result(None, "REFERENCE_CAPACITY_UNAVAILABLE", eligible=False)

    if direction == "REST":
        # Rest has no new charge throughput; SOC is carried by the neighbouring
        # active steps, not recomputed here.
        return _result(None, "ANCHOR_UNAVAILABLE", eligible=False)

    if direction == "DISCHARGE":
        if discharged_since_full_ah is None:
            return _result(None, "ANCHOR_UNAVAILABLE", eligible=False)
        soc = 100.0 * (1.0 - discharged_since_full_ah / q_ref_ah)
    elif direction == "CHARGE":
        if not anchor_available:
            return _result(None, "ANCHOR_UNAVAILABLE", eligible=False)
        if charged_since_empty_ah is None:
            return _result(None, "ANCHOR_UNAVAILABLE", eligible=False)
        soc = 100.0 * (charged_since_empty_ah / q_ref_ah)
    else:
        return _result(None, "AMBIGUOUS_PROTOCOL", eligible=False)

    if soc > 100.0 or soc < 0.0:
        return _result(soc, "OUT_OF_RANGE_REFERENCE", eligible=False)

    return _result(soc, "VALID_REFERENCE", eligible=True)

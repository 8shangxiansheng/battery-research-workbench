from __future__ import annotations

import pytest

from battery_workbench.labels.soc import (
    SocLabelResult,
    compute_soc_reference,
)


def _dis(**kw) -> SocLabelResult:
    """Discharge-direction helper: Q_ref = 11.0441 (real baseline)."""
    base = {
        "direction": "DISCHARGE",
        "discharged_since_full_ah": 0.0,
        "charged_since_empty_ah": None,
        "q_ref_ah": 11.0441,
        "cycle_complete": True,
        "anchor_available": True,
    }
    base.update(kw)
    return compute_soc_reference(**base)


def test_discharge_start_soc_100_t02() -> None:
    """T02: at discharge start (0 Ah discharged), SOC = 100."""
    r = _dis(discharged_since_full_ah=0.0)
    assert r.soc_reference_percent == pytest.approx(100.0)
    assert r.soc_reference_quality == "VALID_REFERENCE"


def test_discharge_formula_t03() -> None:
    """T03: SOC = 100 * (1 - Q_dis / Q_ref)."""
    r = _dis(discharged_since_full_ah=11.0441 / 2)
    assert r.soc_reference_percent == pytest.approx(50.0)


def test_discharge_endpoint_t04() -> None:
    """T04: full discharge endpoint -> SOC = 0."""
    r = _dis(discharged_since_full_ah=11.0441)
    assert r.soc_reference_percent == pytest.approx(0.0)


def test_no_silent_clip_above_100_t05() -> None:
    """T05: overshoot beyond 100 is NOT clipped to 100."""
    r = _dis(discharged_since_full_ah=-1.0)  # negative discharge -> SOC > 100
    assert r.soc_reference_percent == pytest.approx(100 * (1 + 1.0 / 11.0441))
    assert r.soc_reference_percent > 100.0
    assert r.soc_reference_quality == "OUT_OF_RANGE_REFERENCE"


def test_no_silent_clip_below_0_t06() -> None:
    """T06: discharge beyond Q_ref is NOT clipped to 0."""
    r = _dis(discharged_since_full_ah=12.0)
    assert r.soc_reference_percent == pytest.approx(100 * (1 - 12.0 / 11.0441))
    assert r.soc_reference_percent < 0.0
    assert r.soc_reference_quality == "OUT_OF_RANGE_REFERENCE"


def test_charge_requires_valid_empty_anchor_t11() -> None:
    """T11: charge direction requires a trusted empty anchor."""
    r = compute_soc_reference(
        direction="CHARGE",
        discharged_since_full_ah=None,
        charged_since_empty_ah=5.0,
        q_ref_ah=11.0441,
        cycle_complete=True,
        anchor_available=False,  # no trusted empty anchor
    )
    assert r.soc_reference_percent is None
    assert r.soc_reference_quality == "ANCHOR_UNAVAILABLE"
    assert r.soc_label_eligible is False


def test_charge_formula_with_anchor() -> None:
    r = compute_soc_reference(
        direction="CHARGE",
        discharged_since_full_ah=None,
        charged_since_empty_ah=11.0441 / 2,
        q_ref_ah=11.0441,
        cycle_complete=True,
        anchor_available=True,
    )
    assert r.soc_reference_percent == pytest.approx(50.0)


def test_rest_no_new_capacity() -> None:
    """Rest events carry null capacity inputs -> SOC not computable directly."""
    r = _dis(direction="REST", discharged_since_full_ah=None)
    assert r.soc_reference_percent is None


def test_incomplete_cycle_t07() -> None:
    """T07: incomplete cycle -> INCOMPLETE_CYCLE, ineligible."""
    r = _dis(cycle_complete=False)
    assert r.soc_reference_quality == "INCOMPLETE_CYCLE"
    assert r.soc_label_eligible is False


def test_missing_anchor_t08() -> None:
    r = _dis(anchor_available=False)
    assert r.soc_reference_quality == "ANCHOR_UNAVAILABLE"
    assert r.soc_reference_percent is None


def test_missing_qref_t09() -> None:
    r = _dis(q_ref_ah=None)
    assert r.soc_reference_quality == "REFERENCE_CAPACITY_UNAVAILABLE"
    assert r.soc_reference_percent is None
    assert r.soc_label_eligible is False


def test_vendor_soc_dod_not_promoted_t14() -> None:
    """T14: the vendor soc_dod_percent field is NEVER the reference output.

    The formula output must differ from the vendor field for the same event,
    proving no silent pass-through. (Vendor behavior: 0->100 in BOTH directions.)
    """
    # Discharge at 50%: formula gives 50; vendor field at mid-discharge is 50 too,
    # but at discharge START the vendor field reads 0 while the formula reads 100.
    r = _dis(discharged_since_full_ah=0.0)
    assert r.soc_reference_percent == pytest.approx(100.0)  # formula, not vendor 0
    # And the result struct never echoes the vendor value.
    assert not hasattr(r, "soc_dod_percent")


def test_retrospective_temporality_t15() -> None:
    """T15: Q_ref from same-cycle endpoint -> RETROSPECTIVE temporality."""
    r = _dis()
    assert r.soc_label_temporality == "RETROSPECTIVE_FULL_CYCLE_REFERENCE"
    assert r.soc_label_temporality != "ONLINE_CAUSAL_REFERENCE"


def test_deterministic_soc_t16() -> None:
    """T16: identical inputs yield identical SOC."""
    a = _dis(discharged_since_full_ah=2.5)
    b = _dis(discharged_since_full_ah=2.5)
    assert a.soc_reference_percent == b.soc_reference_percent
    assert a.soc_reference_quality == b.soc_reference_quality


def test_zero_qref_unusable() -> None:
    r = _dis(q_ref_ah=0.0)
    assert r.soc_reference_percent is None
    assert r.soc_reference_quality == "REFERENCE_CAPACITY_UNAVAILABLE"

"""BRW-014 V2 SOC contract tests (segment-normalized reference + rest propagation)."""

from __future__ import annotations

import pytest

from battery_workbench.labels.soc import SocLabelResult, compute_soc_reference

TOL = 1e-6


def _charge(**kw) -> SocLabelResult:
    base = {
        "direction": "CHARGE",
        "q_progress_ah": 0.0,
        "q_segment_total_ah": 11.0959,
        "prev_valid_soc": None,
        "cycle_complete": True,
        "anchor_available": True,
        "anchor_quality": "REFERENCE_PROTOCOL_ANCHOR",
    }
    base.update(kw)
    return compute_soc_reference(**base)


def _discharge(**kw) -> SocLabelResult:
    base = {
        "direction": "DISCHARGE",
        "q_progress_ah": 0.0,
        "q_segment_total_ah": 11.0441,
        "prev_valid_soc": None,
        "cycle_complete": True,
        "anchor_available": True,
        "anchor_quality": "REFERENCE_PROTOCOL_ANCHOR",
    }
    base.update(kw)
    return compute_soc_reference(**base)


# --- Charge direction (segment-normalized) ---


def test_charge_start_zero_t01() -> None:
    r = _charge(q_progress_ah=0.0)
    assert r.soc_reference_percent == pytest.approx(0.0, abs=TOL)
    assert r.soc_reference_quality == "VALID_REFERENCE"


def test_charge_end_exactly_100_t02() -> None:
    r = _charge(q_progress_ah=11.0959)
    assert r.soc_reference_percent == pytest.approx(100.0, abs=TOL)
    assert r.soc_reference_quality == "VALID_REFERENCE"


def test_cv_end_no_over_100_t03() -> None:
    """The old V1 failure: Q_charge total > Q_discharge produced 100.475%.
    V2 normalizes by the charge segment total, so CV end == 100 exactly."""
    r = _charge(q_progress_ah=11.0959)  # full CC+CV charge
    assert r.soc_reference_percent <= 100.0 + TOL
    assert r.soc_reference_quality == "VALID_REFERENCE"


def test_charge_midpoint() -> None:
    r = _charge(q_progress_ah=11.0959 / 2)
    assert r.soc_reference_percent == pytest.approx(50.0, abs=TOL)


def test_charge_monotonic_by_construction_t04() -> None:
    """SOC is a linear function of cumulative charge — monotonic input gives
    monotonic output; no sorting/repair applied anywhere."""
    s1 = _charge(q_progress_ah=2.0).soc_reference_percent
    s2 = _charge(q_progress_ah=5.0).soc_reference_percent
    s3 = _charge(q_progress_ah=9.0).soc_reference_percent
    assert s1 < s2 < s3


# --- Discharge direction ---


def test_discharge_start_100_t05() -> None:
    r = _discharge(q_progress_ah=0.0)
    assert r.soc_reference_percent == pytest.approx(100.0, abs=TOL)


def test_discharge_end_zero_t06() -> None:
    r = _discharge(q_progress_ah=11.0441)
    assert r.soc_reference_percent == pytest.approx(0.0, abs=TOL)


def test_discharge_monotonic_decreasing_t07() -> None:
    s1 = _discharge(q_progress_ah=1.0).soc_reference_percent
    s2 = _discharge(q_progress_ah=5.0).soc_reference_percent
    s3 = _discharge(q_progress_ah=9.0).soc_reference_percent
    assert s1 > s2 > s3


# --- Floating tolerance, not silent clipping ---


def test_tolerance_snap_not_clip() -> None:
    """A mathematically-exact-100 value with float noise snaps within the
    documented tolerance; a genuinely out-of-range value stays flagged."""
    r = _charge(q_progress_ah=11.0959 * (1 + 1e-13))  # float noise at segment end
    assert r.soc_reference_percent == pytest.approx(100.0, abs=TOL)
    assert r.soc_reference_quality == "VALID_REFERENCE"
    # Genuine overshoot beyond tolerance is NOT silently accepted.
    bad = _charge(q_progress_ah=11.0959 * 1.01)
    assert bad.soc_reference_quality == "OUT_OF_RANGE_REFERENCE"
    assert bad.soc_label_eligible is False


# --- Rest propagation (Sec 9/10) ---


def test_rest_propagates_previous_soc() -> None:
    r = _charge(direction="REST", prev_valid_soc=100.0, anchor_quality="PROPAGATED_REST_ANCHOR")
    assert r.soc_reference_percent == pytest.approx(100.0)
    assert r.soc_reference_quality == "VALID_REFERENCE"


def test_rest_after_discharge_propagates_zero() -> None:
    r = _discharge(direction="REST", prev_valid_soc=0.0, anchor_quality="PROPAGATED_REST_ANCHOR")
    assert r.soc_reference_percent == pytest.approx(0.0)


def test_rest_without_previous_null() -> None:
    r = _charge(direction="REST", prev_valid_soc=None)
    assert r.soc_reference_percent is None
    assert r.soc_reference_quality == "ANCHOR_UNAVAILABLE"
    assert r.soc_label_eligible is False


def test_rest_ignores_capacity_inputs() -> None:
    """Rest propagation must not re-integrate capacity."""
    r = _charge(direction="REST", prev_valid_soc=100.0, q_progress_ah=99.0, q_segment_total_ah=11.0)
    assert r.soc_reference_percent == pytest.approx(100.0)


# --- Missing inputs ---


def test_missing_segment_total_t09_style() -> None:
    r = _charge(q_segment_total_ah=None)
    assert r.soc_reference_percent is None
    assert r.soc_reference_quality == "REFERENCE_CAPACITY_UNAVAILABLE"


def test_incomplete_cycle() -> None:
    r = _charge(cycle_complete=False)
    assert r.soc_reference_quality == "INCOMPLETE_CYCLE"
    assert r.soc_label_eligible is False


def test_missing_anchor() -> None:
    r = _charge(anchor_available=False)
    assert r.soc_reference_quality == "ANCHOR_UNAVAILABLE"


# --- Anchor quality (Sec 11/12) ---


def test_assumed_initial_anchor_preserved_t16() -> None:
    """Cycle-1 charge start has no independent empty evidence -> the caller
    marks it ASSUMED_INITIAL_ANCHOR and V2 carries it verbatim."""
    r = _charge(q_progress_ah=0.0, anchor_quality="ASSUMED_INITIAL_ANCHOR")
    assert r.soc_anchor_quality == "ASSUMED_INITIAL_ANCHOR"
    assert r.soc_reference_quality == "VALID_REFERENCE"  # value valid, anchor quality separate


# --- Diagnostic unbounded SOC (Sec 8) ---


def test_diagnostic_unbounded_preserved_t17() -> None:
    """The V1-style integral (charge / discharge-capacity denominator) is kept
    as a diagnostic: at CV end it reads >100 — the apparent-CE artifact."""
    r = _charge(
        q_progress_ah=11.0959,
        diagnostic_unbounded_percent=100.475,
    )
    assert r.soc_integral_unbounded_percent == pytest.approx(100.475)
    assert r.soc_reference_percent == pytest.approx(100.0)  # canonical stays bounded


def test_diagnostic_not_eligible_t18() -> None:
    """The diagnostic field must never drive eligibility (structural check)."""
    import dataclasses

    from battery_workbench.labels.soc import SocLabelResult as S

    field_names = {f.name for f in dataclasses.fields(S)}
    assert "soc_integral_unbounded_percent" in field_names
    # Eligibility computed from bounded reference, not the diagnostic.
    r = _charge(q_progress_ah=11.0959, diagnostic_unbounded_percent=100.475)
    assert r.soc_label_eligible is True  # canonical SOC=100 is valid
    assert r.soc_integral_unbounded_percent == pytest.approx(100.475)  # diagnostic kept


# --- Vendor isolation (Sec 13) ---


def test_vendor_soc_dod_not_used_t19() -> None:
    """compute_soc_reference has no vendor input at all."""
    import inspect

    sig = inspect.signature(compute_soc_reference)
    assert "vendor_soc_dod_percent" not in sig.parameters


# --- Temporality (Sec 4/5/20) ---


def test_retrospective_segment_flag_t20() -> None:
    r = _charge()
    assert r.soc_label_temporality == "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"


# --- Determinism ---


def test_deterministic() -> None:
    a = _charge(q_progress_ah=3.3)
    b = _charge(q_progress_ah=3.3)
    assert a == b

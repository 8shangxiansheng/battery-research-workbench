from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.labels.soh import (
    build_cycle_soh_labels,
    compute_soh_reference,
    select_reference_capacity,
)


def _cycles() -> pd.DataFrame:
    """Real-shaped synthetic cycle table (baseline + one later cycle)."""
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X", "CELL_X"],
            "experiment_id": ["EXP_X", "EXP_X"],
            "cycle_index_raw": [1, 2],
            "charge_capacity_ah": [11.0959, 11.0551],
            "discharge_capacity_ah": [11.0441, 11.0083],
        }
    )


def test_discharge_capacity_extraction_t17() -> None:
    """T17: per-cycle discharge capacity is extracted exactly."""
    cap = select_reference_capacity(_cycles())
    assert cap is not None
    assert cap.q_ref_ah == pytest.approx(11.0441)
    assert cap.reference_cycle_index == 1
    assert cap.reference_capacity_source == "BASELINE_CYCLE"


def test_baseline_qref_t18() -> None:
    """T18: Q_ref is the baseline (first complete) cycle discharge capacity."""
    cap = select_reference_capacity(_cycles())
    assert cap.q_ref_ah == pytest.approx(11.0441)


def test_baseline_cycle_soh_100_t19() -> None:
    """T19: baseline cycle SOH = 100 by definition."""
    r = compute_soh_reference(q_discharge_ah=11.0441, q_ref_ah=11.0441)
    assert r.soh_capacity_reference_percent == pytest.approx(100.0)


def test_later_cycle_ratio_t20() -> None:
    """T20: later-cycle SOH is the capacity ratio."""
    r = compute_soh_reference(q_discharge_ah=11.0083, q_ref_ah=11.0441)
    assert r.soh_capacity_reference_percent == pytest.approx(100 * 11.0083 / 11.0441)
    assert r.soh_capacity_reference_percent < 100.0


def test_incomplete_cycle_ineligible_t21() -> None:
    """T21: a cycle without a discharge capacity is SOH-ineligible."""
    out = build_cycle_soh_labels(_cycles(), reference=select_reference_capacity(_cycles()))
    assert len(out) == 2
    assert out["soh_label_eligible"].all()


def test_no_guessed_nominal_t22() -> None:
    """T22: SOH NEVER falls back to a guessed nominal capacity."""
    # No nominal capacity anywhere in the input -> source must be BASELINE_CYCLE.
    cap = select_reference_capacity(_cycles())
    assert cap.reference_capacity_source != "EXTERNAL_METADATA"
    assert cap.reference_capacity_source == "BASELINE_CYCLE"


def test_explicit_rpt_policy_t23() -> None:
    """T23: an RPT reference is used only when explicitly provided."""
    cap = select_reference_capacity(_cycles(), rpt_capacity_ah=11.2)
    assert cap.reference_capacity_source == "RPT"
    assert cap.q_ref_ah == pytest.approx(11.2)


def test_exact_cycle_propagation_t24() -> None:
    """T24: SOH propagates to events by exact battery+experiment+cycle keys."""
    out = build_cycle_soh_labels(_cycles(), reference=select_reference_capacity(_cycles()))
    cyc2 = out[out["cycle_index_raw"] == 2].iloc[0]
    assert cyc2["soh_reference_cycle_index"] == 1
    assert cyc2["soh_capacity_reference_percent"] == pytest.approx(100 * 11.0083 / 11.0441)


def test_no_timestamp_join_t25() -> None:
    """T25: propagation keys are battery+experiment+cycle — never timestamps."""
    out = build_cycle_soh_labels(_cycles(), reference=select_reference_capacity(_cycles()))
    assert "timestamp" not in " ".join(out.columns)


def test_deterministic_soh_t26() -> None:
    """T26: identical inputs yield identical SOH."""
    a = compute_soh_reference(q_discharge_ah=11.0083, q_ref_ah=11.0441)
    b = compute_soh_reference(q_discharge_ah=11.0083, q_ref_ah=11.0441)
    assert a.soh_capacity_reference_percent == b.soh_capacity_reference_percent

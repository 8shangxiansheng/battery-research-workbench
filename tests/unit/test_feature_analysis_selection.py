"""BRW-021 T22-T44: gate comparison, redundancy, selection, determinism."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.feature_analysis.engine import (
    gate_comparison,
    run_analysis,
    subgroup_analysis,
)
from battery_workbench.feature_analysis.schemas import FeatureAnalysisSpec


def _frame(n: int = 60, with_gates: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "cycle_group_id": ["CG::1"] * (n // 2) + ["CG::2"] * (n - n // 2),
            "step_type": (
                ["恒流充电"] * (n // 3) + ["恒流放电"] * (n // 3) + ["搁置"] * (n - 2 * (n // 3))
            ),
            "soc_reference_percent": np.linspace(100, 20, n),
        }
    )
    frame["amplitude_a_u"] = np.linspace(90, 30, n) + rng.normal(0, 1, n)
    frame["waveform_rms_a_u"] = np.linspace(50, 15, n) + rng.normal(0, 0.5, n)
    frame["waveform_p2p_a_u"] = frame["amplitude_a_u"] * 1.9 + rng.normal(0, 0.2, n)  # redundant
    frame["waveform_energy_sum_sq_a_u2"] = rng.normal(100, 5, n)  # near-constant
    if with_gates:
        frame["amplitude_a_u@GATE::A"] = frame["amplitude_a_u"] * 1.0
        frame["amplitude_a_u@GATE::B"] = frame["amplitude_a_u"] * 0.6 + rng.normal(0, 0.5, n)
    return frame


def _train_view(frame: pd.DataFrame, assigns: pd.DataFrame, fold: str) -> pd.DataFrame:
    from battery_workbench.feature_analysis.engine import train_feature_input

    return train_feature_input(frame, assigns, fold=fold).frame


def _spec(**overrides) -> FeatureAnalysisSpec:
    values = {
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "target": "soc_reference_percent",
        "candidate_features": ["amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"],
    }
    values.update(overrides)
    return FeatureAnalysisSpec(**values)


# --- T22-T23: gate comparison / subgroup ---


def test_t22_gate_comparison() -> None:
    result = gate_comparison(
        _frame(), "amplitude_a_u", ["GATE::A", "GATE::B"], "soc_reference_percent"
    )
    assert {row["gate_id"] for row in result} == {"GATE::A", "GATE::B"}
    assert all("spearman_rho" in row for row in result)
    # no "best gate" claim
    assert all("best" not in row for row in result)


def test_t23_insufficient_subgroup_rows_flagged() -> None:
    tiny = _frame(8)
    tiny["step_type"] = ["搁置"] * 7 + ["恒流充电"]
    result = subgroup_analysis(
        tiny, ["amplitude_a_u"], "soc_reference_percent", subgroup_by="step_type", min_rows=5
    )
    charge = next(r for r in result if r["subgroup"] == "恒流充电")
    assert charge["status"] == "INSUFFICIENT_ROWS"


# --- T24-T26: redundancy ---


def test_t24_high_redundancy_flagged() -> None:
    frame = _frame(60)
    assigns = _assignments(60)
    spec = _spec(
        candidate_features=["amplitude_a_u", "waveform_p2p_a_u"],
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.9},
        },
    )
    result = run_analysis(spec, _train_view(frame, assigns, "fold1"))
    redundant = [r for r in result["redundancy"] if r["verdict"] == "HIGH_REDUNDANCY"]
    assert redundant, "amplitude/p2p should be flagged"
    # T25: flagged but NOT removed
    assert result["auto_removed_features"] == []


def test_t26_redundancy_threshold_versioned() -> None:
    from battery_workbench.feature_analysis.engine import REDUNDANCY_POLICY_VERSION

    assert REDUNDANCY_POLICY_VERSION


# --- T27-T33: selection ---


def test_t27_user_explicit_exact() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame()
    spec = _spec(
        selection={"requested": True, "mode": "USER_EXPLICIT", "user_features": ["amplitude_a_u"]}
    )
    s = run_selection(spec, frame)
    assert s["selected_features"] == ["amplitude_a_u"]
    assert s["selection_mode"] == "USER_EXPLICIT"


def test_t28_train_only_selector() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame(60)
    assigns = pd.DataFrame(
        {
            "measurement_event_id": frame["measurement_event_id"],
            "fold": ["fold1"] * 60,
            "role": ["TRAIN"] * 30 + ["HELD_OUT"] * 30,
        }
    )
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        candidate_features=["amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"],
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.8, "max_missing_fraction": 0.05},
        },
    )
    s = run_selection(spec, frame, assignments=assigns, fold="fold1")
    assert s["analysis_mode"] == "TRAIN_ONLY_ML_SAFE"
    assert s["ml_safe_selection"] is True
    assert s["split_id"] == "SPLIT::abc" and s["fold_index"] == 1


def test_t29_exploratory_selection_marked_non_ml_safe() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    spec = _spec(
        selection={"requested": True, "mode": "USER_EXPLICIT", "user_features": ["amplitude_a_u"]},
    )
    s = run_selection(spec, _frame())
    assert s["selection_basis"] == "EXPLORATORY_FULL_DATA"
    assert s["ml_safe_selection"] is False


def _assignments(n: int = 60, fold: str = "fold1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "fold": [fold] * n,
            "role": ["TRAIN"] * (n // 2) + ["HELD_OUT"] * (n - n // 2),
        }
    )


def test_t30_fold_selections_independent() -> None:
    """Two folds with genuinely different train data may select differently."""
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame(60, with_gates=False)
    # fold1 TRAIN = first half (amplitude tracks target); fold2 TRAIN = second half
    # with amplitude noise-dominated (no association) → different outcomes allowed
    assigns1 = pd.DataFrame(
        {
            "measurement_event_id": frame["measurement_event_id"],
            "fold": ["fold1"] * 60,
            "role": ["TRAIN"] * 30 + ["HELD_OUT"] * 30,
        }
    )
    assigns2 = pd.DataFrame(
        {
            "measurement_event_id": frame["measurement_event_id"],
            "fold": ["fold2"] * 60,
            "role": ["HELD_OUT"] * 30 + ["TRAIN"] * 30,
        }
    )
    frame2 = frame.copy()
    rng = np.random.default_rng(99)
    frame2.loc[frame2.index[30:], "amplitude_a_u"] = rng.normal(0, 1, 30)  # no signal
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        candidate_features=["amplitude_a_u", "waveform_rms_a_u"],
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.8},
        },
    )
    s1 = run_selection(spec, frame, assignments=assigns1, fold="fold1")
    s2 = run_selection(spec, frame2, assignments=assigns2, fold="fold2")
    assert "amplitude_a_u" in s1["selected_features"]
    assert "amplitude_a_u" not in s2["selected_features"]


def test_t31_held_out_target_permutation_invariant() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame(60)
    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.9},
        },
    )
    s1 = run_selection(spec, frame, assignments=assigns, fold="fold1")
    perm = frame.copy()
    held = assigns["role"] == "HELD_OUT"
    perm.loc[held, "soc_reference_percent"] = (
        perm.loc[held, "soc_reference_percent"].sample(frac=1.0, random_state=5).to_numpy()
    )
    s2 = run_selection(spec, perm, assignments=assigns, fold="fold1")
    assert s1["selected_features"] == s2["selected_features"]


def test_t32_train_target_change_may_alter_selection() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame(60)
    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        candidate_features=["amplitude_a_u", "waveform_rms_a_u"],
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.95},
        },
    )
    s1 = run_selection(spec, frame, assignments=assigns, fold="fold1")
    changed = frame.copy()
    train = assigns["role"] == "TRAIN"
    # non-monotone noise destroys the amplitude↔target association in TRAIN
    changed.loc[train, "soc_reference_percent"] = np.random.default_rng(4).normal(
        50, 25, int(train.sum())
    )
    s2 = run_selection(spec, changed, assignments=assigns, fold="fold1")
    assert s1["selection_id"] != s2["selection_id"]


def test_t33_deterministic_selection() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={"requested": True, "mode": "TRAIN_ONLY_RULE_BASED"},
    )
    s1 = run_selection(spec, _frame(60), assignments=assigns, fold="fold1")
    s2 = run_selection(spec, _frame(60), assignments=assigns, fold="fold1")
    assert s1["selection_id"] == s2["selection_id"]


# --- T34-T36: determinism ---


def test_t34_deterministic_analysis_id() -> None:
    assert _spec().analysis_id == _spec().analysis_id


def test_t35_config_change_changes_id() -> None:
    assert _spec().analysis_id != _spec(target="soh_capacity_reference_percent").analysis_id
    assert _spec(candidate_features=["amplitude_a_u"]).analysis_id != _spec().analysis_id


def test_t36_deterministic_selection_id() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    frame = _frame(60)
    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={"requested": True, "mode": "TRAIN_ONLY_RULE_BASED"},
    )
    s = run_selection(spec, frame, assignments=assigns, fold="fold1")
    assert s["selection_id"].startswith("SEL::")


def test_ml_safe_selector_requires_train_mode() -> None:
    from battery_workbench.feature_analysis.selection import run_selection

    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={"requested": True, "mode": "USER_EXPLICIT", "user_features": ["amplitude_a_u"]},
    )
    s = run_selection(spec, _frame(60), assignments=assigns, fold="fold1")
    assert s["selection_mode"] == "USER_EXPLICIT"
    assert s["selection_basis"] == "TRAIN_ONLY_ML_SAFE"
    # rule-based selector refuses exploratory mode at the schema level
    with pytest.raises(ValueError, match="TRAIN_ONLY_ML_SAFE"):
        FeatureAnalysisSpec(
            analysis_mode="EXPLORATORY_FULL_DATA",
            target="soc_reference_percent",
            candidate_features=["amplitude_a_u"],
            selection={"requested": True, "mode": "TRAIN_ONLY_RULE_BASED"},
        )

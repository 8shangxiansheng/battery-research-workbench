"""BRW-021 T01-T19: spec validation, structural HELD_OUT isolation, methods."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.feature_analysis.engine import (
    descriptive_stats,
    pair_correlation,
    pairwise_correlation,
    train_feature_input,
)
from battery_workbench.feature_analysis.schemas import (
    AnalysisMode,
    FeatureAnalysisSpec,
)


def _frame(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "cycle_group_id": ["CG::1"] * (n // 2) + ["CG::2"] * (n - n // 2),
            "soc_reference_percent": np.linspace(100, 20, n),
            "amplitude_a_u": np.linspace(90, 30, n) + rng.normal(0, 1, n),
            "waveform_rms_a_u": np.linspace(50, 15, n) + rng.normal(0, 0.5, n),
            "waveform_p2p_a_u": np.linspace(170, 60, n) + rng.normal(0, 1, n),
            "tof_us": [None] * n,
            "envelope_peak_a_u": np.linspace(80, 25, n) + rng.normal(0, 1, n),
        }
    )


def _assignments(n: int = 40) -> pd.DataFrame:
    roles = ["TRAIN"] * (n // 2) + ["HELD_OUT"] * (n - n // 2)
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "fold": ["fold1"] * n,
            "role": roles,
        }
    )


def _spec(**overrides) -> FeatureAnalysisSpec:
    values = {
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "target": "soc_reference_percent",
        "candidate_features": ["amplitude_a_u", "waveform_rms_a_u"],
    }
    values.update(overrides)
    return FeatureAnalysisSpec(**values)


# --- T01-T05: modes ---


def test_t01_exploratory_mode_valid() -> None:
    spec = _spec()
    assert spec.analysis_mode == AnalysisMode.EXPLORATORY_FULL_DATA
    assert spec.analysis_id.startswith("AN::")


def test_t02_ml_safe_mode_valid() -> None:
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
    )
    assert spec.analysis_mode == AnalysisMode.TRAIN_ONLY_ML_SAFE


def test_t03_ml_safe_requires_split() -> None:
    with pytest.raises(ValueError, match="split_id"):
        _spec(analysis_mode="TRAIN_ONLY_ML_SAFE", fold_index=1)


def test_t04_ml_safe_requires_fold() -> None:
    with pytest.raises(ValueError, match="fold_index"):
        _spec(analysis_mode="TRAIN_ONLY_ML_SAFE", split_id="SPLIT::abc")


def test_t05_exploratory_marked_non_ml_safe() -> None:
    assert _spec().ml_safe_selection is False


# --- T06-T07: structural HELD_OUT isolation ---


def test_t06_held_out_target_structurally_inaccessible() -> None:
    """TrainFeatureAnalysisInput physically carries only TRAIN rows."""
    frame = _frame()
    tfa = train_feature_input(frame, _assignments(), fold="fold1")
    train_ids = set(_assignments()[_assignments()["role"] == "TRAIN"]["measurement_event_id"])
    assert set(tfa.frame["measurement_event_id"]) == train_ids
    # HELD_OUT rows are simply not present — impossible to read their target
    assert "ME::39" not in set(tfa.frame["measurement_event_id"])
    assert len(tfa.frame) == len(train_ids)


def test_t07_held_out_target_permutation_does_not_change_selection() -> None:
    frame = _frame(60)
    assigns = _assignments(60)
    spec = _spec(
        analysis_mode="TRAIN_ONLY_ML_SAFE",
        split_id="SPLIT::abc",
        fold_index=1,
        selection={"requested": True, "mode": "TRAIN_ONLY_RULE_BASED"},
    )
    from battery_workbench.feature_analysis.selection import run_selection

    s1 = run_selection(spec, frame, assigns, fold="fold1")
    permuted = frame.copy()
    held_mask = assigns["role"] == "HELD_OUT"
    permuted.loc[held_mask, "soc_reference_percent"] = (
        permuted.loc[held_mask, "soc_reference_percent"].sample(frac=1.0, random_state=1).to_numpy()
    )
    s2 = run_selection(spec, permuted, assigns, fold="fold1")
    assert s1["selected_features"] == s2["selected_features"]
    assert s1["selection_id"] == s2["selection_id"]


# --- T08-T10: feature resolution ---


def test_t08_core_feature_resolution() -> None:
    from battery_workbench.feature_analysis.resolve import resolve_candidates

    resolved = resolve_candidates(
        ["amplitude_a_u", "tof_us"], _frame(), mode="EXPLORATORY_FULL_DATA"
    )
    by_name = {r["feature_name"]: r for r in resolved}
    assert by_name["amplitude_a_u"]["status"] == "AVAILABLE"
    assert by_name["amplitude_a_u"]["locator"] == "amplitude_a_u"
    assert by_name["tof_us"]["status"] == "UNAVAILABLE"


def test_t09_auxiliary_resolution() -> None:
    from battery_workbench.feature_analysis.resolve import resolve_candidates

    resolved = resolve_candidates(
        ["waveform_rms_a_u", "waveform_p2p_a_u", "envelope_peak_a_u"],
        _frame(),
        mode="EXPLORATORY_FULL_DATA",
    )
    assert all(r["status"] == "AVAILABLE" for r in resolved)
    assert all(r["role"] == "AUXILIARY" for r in resolved)


def test_t10_gated_locator_resolution() -> None:
    from battery_workbench.feature_analysis.resolve import resolve_candidates

    frame = _frame()
    frame["amplitude_a_u@GATE::abc"] = frame["amplitude_a_u"] * 0.5
    resolved = resolve_candidates(["amplitude_a_u@GATE::abc"], frame, mode="EXPLORATORY_FULL_DATA")
    assert resolved[0]["status"] == "AVAILABLE"
    assert resolved[0]["locator"] == "amplitude_a_u@GATE::abc"
    assert resolved[0]["role"] == "GATED"
    assert resolved[0]["gate_id"] == "GATE::abc"


# --- T11: TOF unavailability ---


def test_t11_unavailable_tof_handled() -> None:
    from battery_workbench.feature_analysis.engine import run_analysis

    spec = _spec(candidate_features=["tof_us", "amplitude_a_u"])
    result = run_analysis(spec, _frame())
    tof_row = next(r for r in result["availability"] if r["feature_name"] == "tof_us")
    assert tof_row["status"] == "UNAVAILABLE"
    assert tof_row["reason"]
    # amplitude still analysed
    amp = next(r for r in result["availability"] if r["feature_name"] == "amplitude_a_u")
    assert amp["status"] == "AVAILABLE"


# --- T12-T13: forbidden features ---


def test_t12_forbidden_predictor_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden|target-leakage"):
        _spec(candidate_features=["soc_dod_percent"])


def test_t13_target_rejected_as_feature() -> None:
    with pytest.raises(ValueError, match="target"):
        _spec(candidate_features=["soc_reference_percent"])


# --- T14-T18: correlation methods ---


def test_t14_pearson_synthetic_golden() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    y = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])
    r = pair_correlation(x, y, method="pearson")
    assert r["coefficient"] == pytest.approx(1.0)
    assert r["status"] == "OK"
    assert r["n"] == 5


def test_t15_spearman_synthetic_golden() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    y = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0]) ** 2  # monotone but nonlinear
    rho = pair_correlation(x, y, method="spearman")
    assert rho["coefficient"] == pytest.approx(1.0)
    pearson = pair_correlation(x, y, method="pearson")
    assert pearson["coefficient"] < 1.0  # nonlinearity only affects pearson
    y_nonmono = pd.Series([10.0, 20.0, 5.0, 4.0, 50.0])
    rho2 = pair_correlation(x, y_nonmono, method="spearman")
    assert rho2["coefficient"] < 1.0


def test_t16_constant_feature_flagged() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    const = pd.Series([7.0] * 5)
    r = pair_correlation(x, const, method="pearson")
    assert r["status"] == "CONSTANT_FEATURE"
    assert r["coefficient"] is None


def test_t17_missing_pairwise_n() -> None:
    x = pd.Series([1.0, 2.0, None, 4.0, 5.0])
    y = pd.Series([2.0, 4.0, 6.0, None, 10.0])
    r = pair_correlation(x, y, method="pearson")
    assert r["n"] == 3
    heavy = pair_correlation(x, y, method="pearson", min_rows=10)
    assert heavy["status"] == "INSUFFICIENT_ROWS"


def test_t18_deterministic_correlation() -> None:
    frame = _frame()
    a1 = pairwise_correlation(frame, ["amplitude_a_u", "waveform_rms_a_u"])
    a2 = pairwise_correlation(
        frame.sample(frac=1.0, random_state=3), ["amplitude_a_u", "waveform_rms_a_u"]
    )
    assert a1.equals(a2)


# --- T19: descriptive stats ---


def test_t19_descriptive_stats() -> None:
    frame = _frame()
    stats = descriptive_stats(frame, ["amplitude_a_u", "tof_us"])
    amp = next(s for s in stats if s["feature_name"] == "amplitude_a_u")
    assert amp["n"] == len(frame)
    assert amp["missing_count"] == 0
    assert amp["p25"] <= amp["median"] <= amp["p75"]
    tof = next(s for s in stats if s["feature_name"] == "tof_us")
    assert tof["missing_fraction"] == 1.0

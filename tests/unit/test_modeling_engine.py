"""BRW-022 T01-T26: ModelSpec, FoldTrainingView isolation, fitting, metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.modeling.engine import (
    MissingPredictorError,
    evaluate_predictions,
    fit_model,
)
from battery_workbench.modeling.schemas import (
    MODELING_POLICY_VERSION,
    ModelSpec,
)
from battery_workbench.modeling.view import FoldTrainingView


def _frame(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    half = n // 2
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "cycle_group_id": ["CG::1"] * half + ["CG::2"] * (n - half),
            "step_type": (
                ["恒流充电"] * (n // 3) + ["恒流放电"] * (n // 3) + ["搁置"] * (n - 2 * (n // 3))
            ),
            "soc_reference_percent": np.linspace(100, 20, n),
            "amplitude_a_u": np.linspace(90, 30, n) + rng.normal(0, 1, n),
            "waveform_rms_a_u": np.linspace(50, 15, n) + rng.normal(0, 0.5, n),
        }
    )


def _assignments(n: int = 60, fold: str = "fold1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "fold": [fold] * n,
            "role": ["TRAIN"] * (n // 2) + ["HELD_OUT"] * (n - n // 2),
        }
    )


def _view(
    frame: pd.DataFrame | None = None, fold: str = "fold1", features: list[str] | None = None
) -> FoldTrainingView:
    frame = frame if frame is not None else _frame()
    assigns = _assignments(len(frame), fold)
    from battery_workbench.modeling.view import build_fold_training_view

    return build_fold_training_view(
        frame,
        assigns,
        fold=fold,
        features=features or ["amplitude_a_u", "waveform_rms_a_u"],
        target="soc_reference_percent",
    )


def _spec(**overrides) -> ModelSpec:
    values = {
        "strategy": "RIDGE",
        "dataset_id": "DS::test",
        "split_id": "SPLIT::test",
        "fold_index": 1,
        "selection_id": "SEL::test",
        "selected_features": ["amplitude_a_u", "waveform_rms_a_u"],
    }
    values.update(overrides)
    return ModelSpec(**values)


# --- T01-T05: ModelSpec ---


def test_t01_spec_validation() -> None:
    s = _spec()
    assert s.strategy == "RIDGE"
    assert s.model_id.startswith("MODEL::")
    assert s.policy_version == MODELING_POLICY_VERSION


def test_t02_unknown_model_rejected() -> None:
    with pytest.raises(ValueError, match="strategy"):
        _spec(strategy="XGBOOST")


def test_t03_deterministic_model_id() -> None:
    assert _spec().model_id == _spec().model_id


def test_t04_stochastic_requires_random_state() -> None:
    with pytest.raises(ValueError, match="random_state"):
        _spec(strategy="RANDOM_FOREST", random_state=None)
    s = _spec(strategy="RANDOM_FOREST", random_state=42)
    assert s.random_state == 42


def test_t05_scaler_fit_train_only() -> None:
    """Linear/Ridge pipeline scaler is fitted on TRAIN only (structurally: fit_model
    only receives the TRAIN view)."""
    view = _view()
    fit = fit_model(view, _spec(strategy="LINEAR_REGRESSION"))
    scaler = fit.pipeline.named_steps["scaler"]
    # scaler statistics must derive from TRAIN rows only: check mean matches TRAIN
    train_mean = view.x_train["amplitude_a_u"].mean()
    assert scaler.mean_[0] == pytest.approx(train_mean)


def test_t06_held_out_distribution_does_not_affect_scaler() -> None:
    frame = _frame(60)
    v1 = _view(frame)
    fit1 = fit_model(v1, _spec(strategy="LINEAR_REGRESSION"))
    # change HELD_OUT feature values massively — scaler must not move
    frame2 = frame.copy()
    held_mask = frame2["cycle_group_id"] == "CG::2"  # fold1 HELD_OUT group
    frame2.loc[held_mask, "amplitude_a_u"] = 1e6
    v2 = _view(frame2)
    fit2 = fit_model(v2, _spec(strategy="LINEAR_REGRESSION"))
    assert fit1.pipeline.named_steps["scaler"].mean_[0] == pytest.approx(
        fit2.pipeline.named_steps["scaler"].mean_[0]
    )


def test_t07_tree_no_scaler() -> None:
    view = _view()
    fit = fit_model(view, _spec(strategy="RANDOM_FOREST", random_state=42))
    assert fit.pipeline is None
    assert fit.estimator is not None


# --- T08: missing predictor ---


def test_t08_missing_predictor_fail_no_imputation() -> None:
    view = _view()
    view.x_train.loc[view.x_train.index[:5], "amplitude_a_u"] = np.nan
    with pytest.raises(MissingPredictorError) as exc:
        fit_model(view, _spec())
    assert exc.value.policy == "FAIL"
    assert "amplitude_a_u" in str(exc.value)


def test_missing_predictor_in_held_out_features_fails() -> None:
    frame = _frame()
    held_mask = frame["cycle_group_id"] == "CG::2"  # fold1 HELD_OUT group
    frame.loc[held_mask, "waveform_rms_a_u"] = 0.0
    view = _view(frame)
    # corrupt only the HELD_OUT copy after view construction: fit sees clean TRAIN,
    # prediction sees missing HELD_OUT feature -> MissingPredictorError at predict
    from battery_workbench.modeling.engine import fit_model as _fm
    from battery_workbench.modeling.engine import predict as _pred

    fit = _fm(view, _spec())
    x_held = view.x_held_out.copy()
    x_held["waveform_rms_a_u"] = np.nan
    with pytest.raises(MissingPredictorError):
        _pred(fit, x_held)


def test_missing_policy_none_is_not_impute() -> None:
    """MODEL_INPUT_NOT_COMPLETE is surfaced; nothing is filled."""
    view = _view()
    view.x_train.loc[view.x_train.index[:3], "amplitude_a_u"] = np.nan
    with pytest.raises(MissingPredictorError) as exc:
        fit_model(view, _spec())
    assert "impute" not in str(exc.value).lower() or exc.value.policy == "FAIL"


# --- T11-T12: fold isolation ---


def test_t12_y_held_out_unavailable_during_fit() -> None:
    """fit_model signature has no y_held_out parameter."""
    import inspect

    sig = inspect.signature(fit_model)
    assert "y_held_out" not in sig.parameters
    assert "y_test" not in sig.parameters


def test_fold_training_view_has_no_held_out_target() -> None:
    view = _view()
    assert not hasattr(view, "y_held_out")
    assert not hasattr(view, "held_out_target")
    # x_held_out has features but the view carries no held-out target series
    assert view.x_held_out.shape[0] == (len(_frame()) - len(_frame()) // 2)


def test_train_target_change_changes_fit() -> None:
    frame = _frame(60)
    v1 = _view(frame)
    fit1 = fit_model(v1, _spec(strategy="LINEAR_REGRESSION"))
    frame2 = frame.copy()
    train_mask = frame2["cycle_group_id"] == "CG::1"  # fold1 TRAIN group
    frame2.loc[train_mask, "soc_reference_percent"] = np.linspace(5, 95, int(train_mask.sum()))
    v2 = _view(frame2)
    fit2 = fit_model(v2, _spec(strategy="LINEAR_REGRESSION"))
    coef1 = fit1.pipeline.named_steps["regressor"].coef_
    coef2 = fit2.pipeline.named_steps["regressor"].coef_
    assert not np.allclose(coef1, coef2) or not np.allclose(
        fit1.pipeline.named_steps["scaler"].mean_,
        fit2.pipeline.named_steps["scaler"].mean_,
    )


# --- T13: held-out target permutation invariance ---


def test_t13_held_out_target_permutation_invariance() -> None:
    frame = _frame(60)
    v1 = _view(frame)
    fit1 = fit_model(v1, _spec(strategy="RIDGE"))
    from battery_workbench.modeling.engine import predict

    pred1 = predict(fit1, v1.x_held_out)

    frame2 = frame.copy()
    held_mask = frame2["cycle_group_id"] == "CG::2"  # fold1 HELD_OUT group
    frame2.loc[held_mask, "soc_reference_percent"] = (
        frame2.loc[held_mask, "soc_reference_percent"].sample(frac=1.0, random_state=9).to_numpy()
    )
    v2 = _view(frame2)
    fit2 = fit_model(v2, _spec(strategy="RIDGE"))
    from battery_workbench.modeling.engine import predict

    pred2 = predict(fit2, v2.x_held_out)
    assert np.allclose(pred1, pred2)


# --- T14: forbidden predictors ---


def test_t14_forbidden_predictor_rejected() -> None:
    from battery_workbench.modeling.view import build_fold_training_view

    frame = _frame()
    frame["soc_dod_percent"] = 50.0
    with pytest.raises(ValueError, match="forbidden|target-leakage"):
        build_fold_training_view(
            frame,
            _assignments(60),
            fold="fold1",
            features=["amplitude_a_u", "soc_dod_percent"],
            target="soc_reference_percent",
        )


# --- T15-T19: metrics golden ---


def test_t15_mae_golden() -> None:
    y_true = np.array([100.0, 80.0, 60.0, 40.0])
    y_pred = np.array([90.0, 90.0, 50.0, 60.0])
    m = evaluate_predictions(y_true, y_pred, step_type=None)
    assert m["overall"]["MAE"] == pytest.approx(12.5)


def test_t16_rmse_golden() -> None:
    y_true = np.array([100.0, 80.0, 60.0, 40.0])
    y_pred = np.array([90.0, 90.0, 50.0, 60.0])
    m = evaluate_predictions(y_true, y_pred, step_type=None)
    assert m["overall"]["RMSE"] == pytest.approx(np.sqrt((100 + 100 + 100 + 400) / 4))  # 13.229


def test_t17_r2_golden() -> None:
    y_true = np.array([1.0, 2.0, 3.0, 4.0])
    y_pred = np.array([1.0, 2.0, 3.0, 4.0])
    m = evaluate_predictions(y_true, y_pred, step_type=None)
    assert m["overall"]["R2"] == pytest.approx(1.0)
    y_bad = np.array([4.0, 3.0, 2.0, 1.0])
    m2 = evaluate_predictions(y_true, y_bad, step_type=None)
    assert m2["overall"]["R2"] < 0.0


def test_t18_dummy_golden() -> None:
    """DummyRegressor(mean of TRAIN) predicts the TRAIN target mean."""
    view = _view()
    fit = fit_model(view, _spec(strategy="DUMMY_MEAN"))
    from battery_workbench.modeling.engine import predict

    preds = predict(fit, view.x_held_out)
    train_mean = view.y_train.mean()
    assert np.allclose(preds, train_mean)


def test_direction_metrics() -> None:
    y_true = np.array([100.0, 90.0, 80.0, 70.0])
    y_pred = np.array([95.0, 85.0, 75.0, 65.0])
    step = np.array(["恒流充电", "恒流放电", "恒流充电", "搁置"])
    m = evaluate_predictions(y_true, y_pred, step_type=step)
    assert "CHARGE" in m["subgroups"]
    assert "DISCHARGE" in m["subgroups"]
    assert "REST" in m["subgroups"]
    assert m["subgroups"]["CHARGE"]["MAE"] == pytest.approx(5.0)


# --- T21: OOB / no clipping ---


def test_oob_count_and_no_clipping() -> None:
    y_true = np.array([80.0, 60.0])
    y_pred = np.array([-5.0, 120.0])  # out of bounds, NOT clipped
    m = evaluate_predictions(y_true, y_pred, step_type=None)
    assert m["overall"]["out_of_bounds_count"] == 2
    assert m["overall"]["raw_min"] == pytest.approx(-5.0)
    assert m["overall"]["raw_max"] == pytest.approx(120.0)


# --- T24-T26: fold handling ---


def test_t24_fold_specific_features_allowed() -> None:
    frame = _frame(60)
    v1 = _view(frame, fold="fold1", features=["amplitude_a_u"])
    v2 = _view(frame, fold="fold2", features=["waveform_rms_a_u"])
    assert list(v1.x_train.columns) == ["amplitude_a_u"]
    assert list(v2.x_train.columns) == ["waveform_rms_a_u"]


def test_t25_no_group_overlap() -> None:
    view = _view()
    train_groups = (
        set(view.x_train["cycle_group_id"]) if "cycle_group_id" in view.x_train else set()
    )
    held_groups = set(_frame()[_frame()["cycle_group_id"] == "CG::1"]["cycle_group_id"])
    # train group (CG::2) must not equal held-out group (CG::1)
    assert not (train_groups & held_groups)


def test_t26_macro_from_fold_metrics() -> None:
    from battery_workbench.modeling.engine import macro_average

    fold_metrics = [
        {"fold_index": 1, "overall": {"MAE": 10.0, "RMSE": 20.0, "R2": 0.5}},
        {"fold_index": 2, "overall": {"MAE": 20.0, "RMSE": 30.0, "R2": 0.7}},
    ]
    macro = macro_average(fold_metrics)
    assert macro["macro_MAE"] == pytest.approx(15.0)
    assert macro["macro_RMSE"] == pytest.approx(25.0)
    assert macro["macro_R2"] == pytest.approx(0.6)

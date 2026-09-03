"""BRW-022 fitting + evaluation.

``fit_model`` accepts only a FoldTrainingView + ModelSpec — its signature has
no y_held_out parameter, so the held-out target is structurally unavailable
during fitting. HELD_OUT rows are predicted with the fitted estimator and
scored separately in ``evaluate_predictions``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from battery_workbench.modeling.schemas import ModelSpec
from battery_workbench.modeling.view import FoldTrainingView, MissingPredictorError

MODEL_INPUT_NOT_COMPLETE = "MODEL_INPUT_NOT_COMPLETE"
SCALED_STRATEGIES = {"LINEAR_REGRESSION", "RIDGE"}


@dataclass
class FittedModel:
    spec: ModelSpec
    estimator: Any
    pipeline: Any | None
    feature_names: list[str]
    train_row_count: int


def fit_model(view: FoldTrainingView, spec: ModelSpec) -> FittedModel:
    """Fit one baseline on TRAIN rows only. No y_held_out parameter exists."""
    x = view.x_train
    y = view.y_train
    null_cols = [c for c in x.columns if x[c].isna().any()]
    if null_cols or y.isna().any():
        raise MissingPredictorError(
            f"MODEL_INPUT_NOT_COMPLETE: missing values in {null_cols or 'target'} "
            "(missing_value_policy=FAIL, no imputation)"
        )

    feature_names = list(x.columns)
    if spec.strategy == "DUMMY_MEAN":
        est = DummyRegressor(strategy="mean")
        pipeline = None
        est.fit(x, y)
    elif spec.strategy in ("LINEAR_REGRESSION", "RIDGE"):
        inner = (
            LinearRegression()
            if spec.strategy == "LINEAR_REGRESSION"
            else Ridge(alpha=spec.config.get("alpha", 1.0))
        )
        pipeline = Pipeline([("scaler", StandardScaler()), ("regressor", inner)])
        pipeline.fit(x, y)
        est = pipeline.named_steps["regressor"]
    elif spec.strategy == "RANDOM_FOREST":
        pipeline = None
        est = RandomForestRegressor(
            n_estimators=spec.config.get("n_estimators", 300),
            max_depth=spec.config.get("max_depth"),
            random_state=spec.random_state,
        )
        est.fit(x, y)
    elif spec.strategy == "GRADIENT_BOOSTING":
        pipeline = None
        est = GradientBoostingRegressor(
            n_estimators=spec.config.get("n_estimators", 200),
            learning_rate=spec.config.get("learning_rate", 0.05),
            random_state=spec.random_state,
        )
        est.fit(x, y)
    else:  # pragma: no cover - schema rejects unknown strategies
        raise ValueError(f"unknown strategy: {spec.strategy}")

    return FittedModel(
        spec=spec,
        estimator=est,
        pipeline=pipeline,
        feature_names=feature_names,
        train_row_count=len(x),
    )


def predict(fitted: FittedModel, x: pd.DataFrame) -> np.ndarray:
    """Predict on feature rows (HELD_OUT features may be used; no target)."""
    null_cols = [c for c in x.columns if x[c].isna().any()]
    if null_cols:
        raise MissingPredictorError(
            f"MODEL_INPUT_NOT_COMPLETE: missing values in HELD_OUT features {null_cols}"
        )
    if fitted.pipeline is not None:
        return np.asarray(fitted.pipeline.predict(x[fitted.feature_names]), dtype=float)
    return np.asarray(fitted.estimator.predict(x[fitted.feature_names]), dtype=float)


def evaluate_predictions(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    *,
    step_type: np.ndarray | pd.Series | None,
    soc_bins: bool = False,
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true
    abs_err = np.abs(err)
    mae = float(abs_err.mean())
    rmse = float(np.sqrt((err**2).mean()))
    ss_res = float(((y_true - y_pred) ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    r2: float | None = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else None

    overall: dict[str, Any] = {
        "n": len(y_true),
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2,
        "R2_status": "OK" if r2 is not None else "UNDEFINED_SINGLE_GROUP_TARGET",
        "MedianAE": float(np.median(abs_err)),
        "MaxAE": float(abs_err.max()),
        "out_of_bounds_count": int(((y_pred < 0) | (y_pred > 100)).sum()),
        "raw_min": float(y_pred.min()),
        "raw_max": float(y_pred.max()),
        "clipping": "NONE (raw predictions preserved)",
    }

    result: dict[str, Any] = {"overall": overall, "subgroups": {}}

    if step_type is not None:
        st = np.asarray(step_type, dtype=object)
        mapping = {"恒流充电": "CHARGE", "恒流放电": "DISCHARGE", "搁置": "REST"}
        for label, group_name in mapping.items():
            mask = st == label
            if not mask.any():
                continue
            gt, gp = y_true[mask], y_pred[mask]
            gerr = np.abs(gp - gt)
            gss_res = float(((gt - gp) ** 2).sum())
            gss_tot = float(((gt - gt.mean()) ** 2).sum())
            result["subgroups"][group_name] = {
                "n": int(mask.sum()),
                "MAE": float(gerr.mean()),
                "RMSE": float(np.sqrt((gp - gt) ** 2).mean()),
                "R2": float(1.0 - gss_res / gss_tot) if gss_tot > 0 else None,
            }

    if soc_bins:
        bins = [0, 20, 40, 60, 80, 100]
        labels = ["0-20", "20-40", "40-60", "60-80", "80-100"]
        binned = pd.cut(y_true, bins=bins, labels=labels, include_lowest=True)
        diag = []
        for label in labels:
            mask = np.asarray(binned == label)
            if mask.any():
                diag.append(
                    {
                        "soc_bin": label,
                        "n": int(mask.sum()),
                        "MAE": float(abs_err[mask].mean()),
                    }
                )
        result["soc_bin_diagnostics"] = diag
    return result


def macro_average(fold_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro mean of fold-level overall metrics (primary summary)."""
    keys = ("MAE", "RMSE", "R2", "MedianAE", "MaxAE")
    out: dict[str, Any] = {}
    for key in keys:
        vals = [
            f["overall"][key] for f in fold_metrics if f.get("overall", {}).get(key) is not None
        ]
        out[f"macro_{key}"] = float(np.mean(vals)) if vals else None  # type: ignore[arg-type]
    out["fold_count"] = len(fold_metrics)
    out["aggregation"] = "MACRO_MEAN_OF_FOLD_METRICS"
    return out

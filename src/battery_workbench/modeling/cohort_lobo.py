"""Battery-grouped LOBO evaluation for immutable harmonized cohort datasets."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.modeling.engine import (
    evaluate_predictions,
    fit_model,
    macro_average_by_battery,
    predict,
)
from battery_workbench.modeling.schemas import STRATEGIES, ModelSpec
from battery_workbench.modeling.view import build_fold_training_view
from battery_workbench.splits.engine import build_assignments, leakage_audit
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy


def evaluate_cohort_lobo(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    features: list[str],
    target: str,
    strategies: list[str] | None = None,
    random_state: int = 42,
    cohort_id: str | None = None,
) -> dict[str, Any]:
    """Train fixed baselines with all non-held-out batteries; score each held-out battery."""
    selected_strategies = strategies or ["DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE"]
    unknown = sorted(set(selected_strategies) - set(STRATEGIES))
    if unknown:
        raise ValueError(f"unknown baseline strategies: {unknown}")
    if len(set(selected_strategies)) != len(selected_strategies):
        raise ValueError("baseline strategies must be unique")
    if target in features or not features:
        raise ValueError("cohort requires non-empty predictors distinct from target")
    if len(set(features)) != len(features):
        raise ValueError("cohort predictor feature names must be unique")
    if frame.empty:
        raise ValueError("cohort requires at least one row")
    required_columns = {
        "battery_id",
        "experiment_id",
        "measurement_event_id",
        "source_dataset_id",
        target,
        *features,
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(
            f"cohort rows are missing required columns: {missing_columns}"
        )
    for identity_column in (
        "battery_id",
        "experiment_id",
        "measurement_event_id",
        "source_dataset_id",
    ):
        values = frame[identity_column]
        if values.map(
            lambda value: not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ).any():
            raise ValueError(
                f"cohort {identity_column} values must be non-empty trimmed strings"
            )
    if frame["measurement_event_id"].duplicated().any():
        raise ValueError("cohort measurement_event_id values must be unique")

    source_identity_counts = frame.groupby("source_dataset_id", sort=False)[
        ["battery_id", "experiment_id"]
    ].nunique(dropna=False)
    if (source_identity_counts != 1).any().any():
        raise ValueError(
            "each source_dataset_id must map to exactly one Battery/Experiment identity"
        )

    for column in [*features, target]:
        try:
            values = np.asarray(frame[column], dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"cohort column {column!r} must contain numeric values") from exc
        if not np.isfinite(values).all():
            raise ValueError(f"cohort column {column!r} must contain only finite values")

    spec = SplitSpec(
        strategy=SplitStrategy.LEAVE_ONE_GROUP_OUT,
        split_unit="BATTERY",
        group_column="battery_id",
        dataset_id=dataset_id,
        require_roles=["TRAIN", "HELD_OUT"],
    )
    assignments = build_assignments(spec, frame)
    assignment_provenance = frame[["measurement_event_id", "source_dataset_id"]].drop_duplicates()
    assignments = assignments.merge(assignment_provenance, on="measurement_event_id", how="left")
    cohort_id = cohort_id or dataset_id
    assignments["cohort_id"] = cohort_id
    audit = leakage_audit(spec, assignments, frame)
    if audit["group_overlap"] or audit["target_used_for_assignment"]:
        raise ValueError("cohort split failed leakage audit")

    battery_results: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    for strategy in selected_strategies:
        for fold_index, fold in enumerate(sorted(assignments["fold"].unique()), start=1):
            view = build_fold_training_view(
                frame,
                assignments,
                fold=fold,
                features=features,
                target=target,
                group_column="battery_id",
            )
            held_ids = set(
                assignments.loc[
                    (assignments["fold"] == fold) & (assignments["role"] == "HELD_OUT"),
                    "measurement_event_id",
                ]
            )
            held = frame[frame["measurement_event_id"].isin(held_ids)]
            model_spec = ModelSpec(
                strategy=strategy,
                dataset_id=dataset_id,
                split_id=spec.split_id,
                fold_index=fold_index,
                selection_id="COHORT_PREDECLARED_FEATURE_MAP",
                selected_features=features,
                random_state=random_state,
            )
            fitted = fit_model(view, model_spec)
            y_true = held[target].to_numpy(dtype=float)
            y_pred = predict(fitted, view.x_held_out)
            metrics = evaluate_predictions(y_true, y_pred, step_type=None)
            battery_id = view.held_out_group_ids[0]
            battery_results.append(
                {
                    "strategy": strategy,
                    "cohort_id": cohort_id,
                    "battery_id": battery_id,
                    "source_dataset_ids": sorted(held["source_dataset_id"].astype(str).unique()),
                    "fold": fold,
                    "overall": metrics["overall"],
                    "row_count": len(held),
                    "train_battery_ids": view.train_group_ids,
                    "held_out_battery_id": battery_id,
                }
            )
            predictions.extend(
                {
                    "strategy": strategy,
                    "cohort_id": cohort_id,
                    "battery_id": battery_id,
                    "fold": fold,
                    "source_dataset_id": str(source_dataset_id),
                    "measurement_event_id": event_id,
                    "y_true": float(actual),
                    "y_pred": float(predicted),
                }
                for event_id, source_dataset_id, actual, predicted in zip(
                    held["measurement_event_id"].astype(str),
                    held["source_dataset_id"].astype(str),
                    y_true,
                    y_pred,
                    strict=True,
                )
            )

    macros: dict[str, dict[str, Any]] = {}
    pooled: dict[str, dict[str, Any]] = {}
    prediction_frame = pd.DataFrame(predictions)
    for strategy in selected_strategies:
        entries = [item for item in battery_results if item["strategy"] == strategy]
        macros[strategy] = macro_average_by_battery(entries)
        rows = prediction_frame[prediction_frame["strategy"] == strategy]
        expected_event_ids = set(frame["measurement_event_id"].astype(str))
        observed_event_ids = set(rows["measurement_event_id"].astype(str))
        if (
            len(rows) != len(expected_event_ids)
            or observed_event_ids != expected_event_ids
            or rows["measurement_event_id"].astype(str).duplicated().any()
            or set(rows["battery_id"].astype(str)) != set(frame["battery_id"].astype(str))
        ):
            raise RuntimeError(f"incomplete held-out prediction coverage for strategy {strategy}")
        pooled[strategy] = evaluate_predictions(
            rows["y_true"].to_numpy(), rows["y_pred"].to_numpy(), step_type=None
        )["overall"]

    expected_prediction_count = len(frame) * len(selected_strategies)
    if len(prediction_frame) != expected_prediction_count:
        raise RuntimeError("held-out prediction row count does not match cohort coverage")

    return {
        "evaluation_id": "LOBO::"
        + hashlib.sha256(
            json.dumps(
                {
                    "dataset_id": dataset_id,
                    "features": features,
                    "target": target,
                    "strategies": selected_strategies,
                    "split_id": spec.split_id,
                    "random_state": random_state,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:24],
        "dataset_id": dataset_id,
        "cohort_id": cohort_id,
        "split_id": spec.split_id,
        "split_unit": "BATTERY",
        "evaluation_scope": "CROSS_BATTERY_LOBO_LIMITED_EVALUATION",
        "strategies": selected_strategies,
        "features": features,
        "target": target,
        "battery_results": battery_results,
        "macro_by_strategy": macros,
        "pooled_row_diagnostic_by_strategy": pooled,
        "leakage_audit": audit,
        "split_assignments": assignments.to_dict(orient="records"),
        "fold_count": int(assignments["fold"].nunique()),
        "battery_count": int(frame["battery_id"].nunique()),
        "held_out_prediction_coverage": {
            "status": "COMPLETE",
            "independent_unit": "BATTERY",
            "expected_battery_count": int(frame["battery_id"].nunique()),
            "observed_battery_count_per_strategy": {
                strategy: int(
                    prediction_frame.loc[prediction_frame["strategy"] == strategy, "battery_id"].nunique()
                )
                for strategy in selected_strategies
            },
            "expected_prediction_rows": expected_prediction_count,
            "observed_prediction_rows": len(prediction_frame),
            "expected_unique_event_count_per_strategy": int(frame["measurement_event_id"].nunique()),
        },
        "uncertainty_assessment": {
            "independent_unit": "BATTERY",
            "independent_group_count": int(frame["battery_id"].nunique()),
            "confidence_interval": {
                "status": "NOT_ESTIMATED",
                "reason": "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN",
                "resampling_unit": "BATTERY",
            },
        },
        "limitations": [
            "LOBO is a limited evaluation when cohort battery count is small",
            "macro metrics weight each held-out battery equally",
            "pooled row metrics are diagnostic only",
            "no hyperparameter tuning or held-out target selection is performed",
        ],
        "predictions": predictions,
    }

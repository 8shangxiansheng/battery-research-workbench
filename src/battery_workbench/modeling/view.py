"""BRW-022 FoldTrainingView: structural TRAIN/HELD_OUT isolation.

``FoldTrainingView`` carries X_train / y_train / X_held_out (features only).
The held-out *target* is NOT part of this object — ``fit_model`` accepts only
a view and therefore cannot read held-out targets. Evaluation reads
y_held_out separately in ``evaluate_predictions``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from battery_workbench.feature_analysis.schemas import FORBIDDEN_CANDIDATES


class MissingPredictorError(ValueError):
    """selected predictor missing in TRAIN or HELD_OUT — policy FAIL, no impute."""

    def __init__(self, message: str, policy: str = "FAIL") -> None:
        super().__init__(message)
        self.policy = policy


@dataclass
class FoldTrainingView:
    fold_index: int
    fold: str
    x_train: pd.DataFrame
    y_train: pd.Series
    x_held_out: pd.DataFrame
    train_group_ids: list[str]
    held_out_group_ids: list[str]
    train_measurement_event_ids: pd.Index
    held_out_measurement_event_ids: pd.Index
    train_row_count: int = 0
    held_out_row_count: int = 0


def build_fold_training_view(
    dataset: pd.DataFrame,
    assignments: pd.DataFrame,
    *,
    fold: str,
    features: list[str],
    target: str,
) -> FoldTrainingView:
    fold_assign = assignments[assignments["fold"] == fold]
    train_ids = set(fold_assign[fold_assign["role"] == "TRAIN"]["measurement_event_id"])
    held_ids = set(fold_assign[fold_assign["role"] == "HELD_OUT"]["measurement_event_id"])

    illegal = [f for f in features if f in FORBIDDEN_CANDIDATES]
    if illegal:
        raise ValueError(f"forbidden / target-leakage predictor(s): {illegal}")
    if target in features:
        raise ValueError(f"target {target!r} cannot be a predictor")

    train = dataset[dataset["measurement_event_id"].isin(train_ids)]
    held = dataset[dataset["measurement_event_id"].isin(held_ids)]

    missing = [f for f in features if f not in dataset.columns]
    if missing:
        raise MissingPredictorError(f"selected predictor(s) missing from dataset: {missing}")

    x_train = train[features].copy()
    x_held = held[features].copy()
    y_train = train[target].copy()

    # missing policy FAIL (no imputation)
    for name, part in (("TRAIN", x_train), ("HELD_OUT", x_held)):
        null_cols = [c for c in part.columns if part[c].isna().any()]
        if null_cols:
            raise MissingPredictorError(
                f"selected predictor(s) with missing values in {part_name(part)}: "
                f"{null_cols} (missing_value_policy=FAIL, no imputation)"
            )
    if y_train.isna().any():
        raise MissingPredictorError(f"target {target!r} has missing values in TRAIN")

    return FoldTrainingView(
        fold_index=int(fold.replace("fold", "")) if fold.startswith("fold") else 0,
        fold=fold,
        x_train=x_train,
        y_train=y_train,
        x_held_out=x_held,
        train_group_ids=sorted(train[fold_assign_col(dataset)].astype(str).unique()),
        held_out_group_ids=sorted(held[fold_assign_col(dataset)].astype(str).unique()),
        train_measurement_event_ids=train["measurement_event_id"].index,
        held_out_measurement_event_ids=held["measurement_event_id"].index,
        train_row_count=len(x_train),
        held_out_row_count=len(x_held),
    )


def part_name(part: pd.DataFrame) -> str:  # pragma: no cover - helper
    return "TRAIN"


def fold_assign_col(dataset: pd.DataFrame) -> str:
    return "cycle_group_id"

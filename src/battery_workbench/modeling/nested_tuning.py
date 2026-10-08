"""Nested grouped candidate selection using only one outer TRAIN partition.

This module intentionally has no API/service adapter. Callers must first
materialize the outer TRAIN rows; no outer HELD_OUT frame or target is accepted
by the public function.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.feature_analysis.schemas import FORBIDDEN_CANDIDATES

CandidatePredictor = Callable[
    [dict[str, Any], pd.DataFrame, pd.Series, pd.DataFrame], Sequence[float] | np.ndarray
]
_OBJECTIVES = {"MAE", "RMSE"}
_IDENTITY_COLUMNS = {
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "electrical_asset_id",
    "ultrasound_asset_id",
    "cycle_group_id",
    "cycle_index_raw",
    "step_index_raw",
}


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    config: dict[str, Any]
    fold_scores: tuple[float, ...]
    macro_score: float


@dataclass(frozen=True)
class NestedGroupedSelection:
    objective_metric: str
    inner_group_column: str
    inner_fold_count: int
    training_group_count: int
    candidate_count: int
    selected_candidate_id: str
    selected_config: dict[str, Any]
    selected_macro_score: float
    candidate_scores: tuple[CandidateScore, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible deterministic report payload."""
        return asdict(self)


def _candidate_configs(
    search_space: Mapping[str, Sequence[Any]], *, max_trials: int
) -> list[dict[str, Any]]:
    if not search_space:
        raise ValueError("search_space must contain at least one parameter")
    if max_trials < 1 or max_trials > 500:
        raise ValueError("max_trials must be between 1 and 500")
    if any(not isinstance(key, str) or not key.strip() for key in search_space):
        raise ValueError("search_space parameter names must be non-empty strings")
    keys = sorted(search_space)
    values: list[Sequence[Any]] = []
    for key in keys:
        options = search_space[key]
        if isinstance(options, (str, bytes)) or not isinstance(options, Sequence) or not options:
            raise ValueError(f"search_space[{key!r}] must be a non-empty list")
        values.append(options)
    trial_count = math.prod(len(options) for options in values)
    if trial_count > max_trials:
        raise ValueError(f"search space has {trial_count} trials, exceeding max_trials={max_trials}")

    configs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for combination in itertools.product(*values):
        config = dict(zip(keys, combination, strict=True))
        try:
            canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("search-space values must be JSON serializable") from exc
        if canonical in seen:
            continue
        seen.add(canonical)
        configs.append(config)
    return configs


def _inner_folds(training_data: pd.DataFrame, group_column: str) -> list[tuple[str, np.ndarray]]:
    if group_column not in training_data:
        raise ValueError(f"inner group column {group_column!r} is missing")
    if training_data[group_column].isna().any():
        raise ValueError("null group id in outer TRAIN rows")
    group_ids = training_data[group_column].astype(str).str.strip()
    if group_ids.eq("").any():
        raise ValueError("empty group id in outer TRAIN rows")
    if group_ids.nunique() != training_data[group_column].nunique(dropna=True):
        raise ValueError("group ids are ambiguous after string normalization")
    groups = sorted(group_ids.unique())
    if len(groups) < 3:
        raise ValueError(
            "nested grouped selection requires at least 3 outer TRAIN groups "
            "so each inner fold has >=2 training groups and 1 validation group"
        )
    group_values = group_ids.to_numpy()
    return [(group, group_values == group) for group in groups]


def select_hyperparameters_nested_grouped(
    outer_train_data: pd.DataFrame,
    *,
    features: list[str],
    target: str,
    inner_group_column: str,
    search_space: Mapping[str, Sequence[Any]],
    candidate_predictor: CandidatePredictor,
    objective_metric: str = "MAE",
    max_trials: int = 50,
) -> NestedGroupedSelection:
    """Select a config by equal-weight grouped CV over outer TRAIN rows only.

    For each inner fold, the callback receives only the inner training X/y and
    validation X. Validation y is read here for scoring; callers have no API to
    provide or access an outer HELD_OUT frame/target.
    """
    if objective_metric not in _OBJECTIVES:
        raise ValueError(f"objective_metric must be one of {sorted(_OBJECTIVES)}")
    if (
        not features
        or any(not isinstance(feature, str) or not feature.strip() for feature in features)
        or len(set(features)) != len(features)
    ):
        raise ValueError("features must be a non-empty unique list")
    if target in features:
        raise ValueError("target cannot be a predictor")
    illegal = sorted(set(features) & FORBIDDEN_CANDIDATES)
    if illegal:
        raise ValueError(f"forbidden / target-leakage predictor(s): {illegal}")
    if inner_group_column in features or set(features) & _IDENTITY_COLUMNS:
        raise ValueError("group and event identity columns cannot be predictors")
    if inner_group_column not in {"battery_id", "experiment_id", "cycle_group_id"}:
        raise ValueError("inner_group_column must be battery_id, experiment_id, or cycle_group_id")
    required = {"measurement_event_id", inner_group_column, target, *features}
    missing = sorted(required - set(outer_train_data.columns))
    if missing:
        raise ValueError(f"outer TRAIN data missing required columns: {missing}")
    if outer_train_data["measurement_event_id"].isna().any() or not outer_train_data[
        "measurement_event_id"
    ].is_unique:
        raise ValueError("outer TRAIN measurement_event_id values must be non-null and unique")

    configs = _candidate_configs(search_space, max_trials=max_trials)
    folds = _inner_folds(outer_train_data, inner_group_column)
    scores: list[CandidateScore] = []
    for config in configs:
        canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        candidate_id = "TUNE_CANDIDATE::" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        fold_scores: list[float] = []
        for validation_group, validation_mask in folds:
            train_mask = ~validation_mask
            inner_train = outer_train_data.loc[train_mask]
            inner_valid = outer_train_data.loc[validation_mask]
            x_train = inner_train[features].copy()
            y_train = pd.to_numeric(inner_train[target], errors="raise").astype(float)
            x_valid = inner_valid[features].copy()
            y_valid = pd.to_numeric(inner_valid[target], errors="raise").to_numpy(dtype=float)
            if x_train.isna().any().any() or y_train.isna().any() or x_valid.isna().any().any():
                raise ValueError("nested tuning uses missing_value_policy=FAIL; no imputation")
            if not np.isfinite(y_train.to_numpy()).all() or not np.isfinite(y_valid).all():
                raise ValueError("nested tuning target values must be finite")
            predictions = np.asarray(
                candidate_predictor(config.copy(), x_train, y_train, x_valid), dtype=float
            )
            if predictions.ndim != 1 or len(predictions) != len(y_valid):
                raise ValueError(
                    f"candidate returned invalid prediction shape for group {validation_group!r}"
                )
            if not np.isfinite(predictions).all():
                raise ValueError("candidate predictions must be finite")
            errors = predictions - y_valid
            score = (
                float(np.abs(errors).mean())
                if objective_metric == "MAE"
                else float(np.sqrt(np.square(errors).mean()))
            )
            fold_scores.append(score)
        scores.append(
            CandidateScore(
                candidate_id=candidate_id,
                config=config,
                fold_scores=tuple(fold_scores),
                macro_score=float(np.mean(fold_scores)),
            )
        )

    winner = min(scores, key=lambda item: item.macro_score)
    return NestedGroupedSelection(
        objective_metric=objective_metric,
        inner_group_column=inner_group_column,
        inner_fold_count=len(folds),
        training_group_count=len(folds),
        candidate_count=len(scores),
        selected_candidate_id=winner.candidate_id,
        selected_config=winner.config.copy(),
        selected_macro_score=winner.macro_score,
        candidate_scores=tuple(scores),
    )

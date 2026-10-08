from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from battery_workbench.modeling.nested_tuning import select_hyperparameters_nested_grouped


def _outer_train_data(group_count: int = 4) -> pd.DataFrame:
    rows = []
    for group_index in range(group_count):
        for row_index, target in enumerate((0.0, 1.0)):
            rows.append(
                {
                    "measurement_event_id": f"ME::{group_index}::{row_index}",
                    "cycle_group_id": f"CG::{group_index}",
                    "feature": float(row_index),
                    "soc_reference_percent": target,
                }
            )
    return pd.DataFrame(rows)


def _zero_predictor(config, x_train, y_train, x_validation):
    return np.zeros(len(x_validation))


def test_nested_grouped_selection_uses_equal_weight_group_folds_deterministically() -> None:
    observed: list[tuple[int, int]] = []

    def predictor(config, x_train, y_train, x_validation):
        observed.append((len(y_train), len(x_validation)))
        return np.full(len(x_validation), config["constant"])

    result = select_hyperparameters_nested_grouped(
        _outer_train_data(),
        features=["feature"],
        target="soc_reference_percent",
        inner_group_column="cycle_group_id",
        search_space={"constant": [10.0, 0.0]},
        candidate_predictor=predictor,
    )

    assert result.inner_fold_count == 4
    assert result.training_group_count == 4
    assert result.candidate_count == 2
    assert result.selected_config == {"constant": 0.0}
    assert result.selected_macro_score == pytest.approx(0.5)
    assert len(observed) == 8
    assert set(observed) == {(6, 2)}
    assert result.to_dict()["selected_candidate_id"] == result.selected_candidate_id


def test_nested_tuner_accepts_only_outer_train_rows_and_exposes_no_validation_target_to_fitter() -> None:
    signature = inspect.signature(select_hyperparameters_nested_grouped)
    assert "y_held_out" not in signature.parameters
    assert "held_out_data" not in signature.parameters
    outer_train = _outer_train_data()
    outer_train.loc[:, "soc_reference_percent"] = 37.0
    held_out_target = 999_999.0
    observed_targets: list[float] = []

    def predictor(config, x_train, y_train, x_validation):
        observed_targets.extend(y_train.astype(float).tolist())
        assert "measurement_event_id" not in x_train
        assert "cycle_group_id" not in x_train
        assert "soc_reference_percent" not in x_validation
        return np.full(len(x_validation), 37.0)

    result = select_hyperparameters_nested_grouped(
        outer_train,
        features=["feature"],
        target="soc_reference_percent",
        inner_group_column="cycle_group_id",
        search_space={"constant": [37.0]},
        candidate_predictor=predictor,
    )

    assert result.selected_macro_score == 0.0
    assert observed_targets
    assert set(observed_targets) == {37.0}
    assert held_out_target not in observed_targets


def test_nested_tuner_requires_three_non_null_groups_and_complete_data() -> None:
    with pytest.raises(ValueError, match="at least 3 outer TRAIN groups"):
        select_hyperparameters_nested_grouped(
            _outer_train_data(group_count=2),
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )

    null_group = _outer_train_data()
    null_group.loc[0, "cycle_group_id"] = None
    with pytest.raises(ValueError, match="null group id"):
        select_hyperparameters_nested_grouped(
            null_group,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )

    missing = _outer_train_data()
    missing.loc[0, "feature"] = np.nan
    with pytest.raises(ValueError, match="missing_value_policy=FAIL"):
        select_hyperparameters_nested_grouped(
            missing,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )


def test_nested_tuner_rejects_target_identity_predictors_and_unbounded_search() -> None:
    data = _outer_train_data()
    with pytest.raises(ValueError, match="target cannot be a predictor"):
        select_hyperparameters_nested_grouped(
            data,
            features=["soc_reference_percent"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )
    with pytest.raises(ValueError, match="group and event identity"):
        select_hyperparameters_nested_grouped(
            data,
            features=["measurement_event_id"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )
    with pytest.raises(ValueError, match="exceeding max_trials"):
        select_hyperparameters_nested_grouped(
            data,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": list(range(3))},
            candidate_predictor=_zero_predictor,
            max_trials=2,
        )


def test_nested_tuner_rejects_invalid_candidate_predictions() -> None:
    def malformed(config, x_train, y_train, x_validation):
        return np.zeros(len(x_validation) + 1)

    with pytest.raises(ValueError, match="invalid prediction shape"):
        select_hyperparameters_nested_grouped(
            _outer_train_data(),
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=malformed,
        )

    def non_finite(config, x_train, y_train, x_validation):
        return np.full(len(x_validation), np.nan)

    with pytest.raises(ValueError, match="predictions must be finite"):
        select_hyperparameters_nested_grouped(
            _outer_train_data(),
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=non_finite,
        )


def test_nested_tuner_validates_metric_group_identity_and_empty_search_options() -> None:
    data = _outer_train_data()
    with pytest.raises(ValueError, match="objective_metric"):
        select_hyperparameters_nested_grouped(
            data,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
            objective_metric="R2",
        )

    ambiguous_groups = data.copy()
    ambiguous_groups.loc[1, "cycle_group_id"] = " CG::0 "
    with pytest.raises(ValueError, match="ambiguous after string normalization"):
        select_hyperparameters_nested_grouped(
            ambiguous_groups,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": [0.0]},
            candidate_predictor=_zero_predictor,
        )

    with pytest.raises(ValueError, match="non-empty list"):
        select_hyperparameters_nested_grouped(
            data,
            features=["feature"],
            target="soc_reference_percent",
            inner_group_column="cycle_group_id",
            search_space={"constant": []},
            candidate_predictor=_zero_predictor,
        )

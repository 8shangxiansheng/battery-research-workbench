from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.modeling import cohort_lobo
from battery_workbench.modeling.cohort_lobo import evaluate_cohort_lobo


def _cohort_frame() -> pd.DataFrame:
    rows = []
    for battery, count, offset in (("B1", 2, 0.0), ("B2", 3, 12.0), ("B3", 6, 30.0)):
        for index in range(count):
            rows.append(
                {
                    "measurement_event_id": f"{battery}::ME::{index}",
                    "battery_id": battery,
                    "experiment_id": f"E::{battery}",
                    "source_dataset_id": f"DS::{battery}",
                    "x": float(index),
                    "soc": offset + float(index * 2),
                }
            )
    return pd.DataFrame(rows)


def test_lobo_keeps_batteries_atomic_and_reports_macro_separately_from_pooled() -> None:
    result = evaluate_cohort_lobo(
        _cohort_frame(),
        dataset_id="COHORT::synthetic",
        features=["x"],
        target="soc",
        strategies=["DUMMY_MEAN"],
    )

    assert result["split_unit"] == "BATTERY"
    assert result["battery_count"] == 3
    assert result["fold_count"] == 3
    assert result["held_out_prediction_coverage"] == {
        "status": "COMPLETE",
        "independent_unit": "BATTERY",
        "expected_battery_count": 3,
        "observed_battery_count_per_strategy": {"DUMMY_MEAN": 3},
        "expected_prediction_rows": len(_cohort_frame()),
        "observed_prediction_rows": len(_cohort_frame()),
        "expected_unique_event_count_per_strategy": len(_cohort_frame()),
    }
    assert result["leakage_audit"]["group_overlap"] is False
    assert result["leakage_audit"]["group_column"] == "battery_id"
    assert len(result["battery_results"]) == 3
    macro = result["macro_by_strategy"]["DUMMY_MEAN"]
    battery_maes = [row["overall"]["MAE"] for row in result["battery_results"]]
    assert macro["macro_MAE"] == sum(battery_maes) / len(battery_maes)
    assert macro["aggregation"] == "MACRO_MEAN_OF_BATTERY_METRICS"
    assert result["pooled_row_diagnostic_by_strategy"]["DUMMY_MEAN"]["MAE"] != macro["macro_MAE"]
    assert result["uncertainty_assessment"] == {
        "independent_unit": "BATTERY",
        "independent_group_count": 3,
        "confidence_interval": {
            "status": "NOT_ESTIMATED",
            "reason": "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN",
            "resampling_unit": "BATTERY",
        },
    }
    assert all(
        row["train_battery_ids"] != [row["held_out_battery_id"]]
        for row in result["battery_results"]
    )


def test_lobo_keeps_multiple_experiments_of_one_battery_in_one_outer_group() -> None:
    frame = _cohort_frame()
    battery_a = frame[frame["battery_id"] == "B1"].index
    frame.loc[battery_a[1], "experiment_id"] = "E::B1::repeat"
    frame.loc[battery_a[1], "source_dataset_id"] = "DS::B1::repeat"

    result = evaluate_cohort_lobo(
        frame,
        dataset_id="COHORT::same-battery-multiple-experiments",
        features=["x"],
        target="soc",
        strategies=["DUMMY_MEAN"],
    )

    assignments = pd.DataFrame(result["split_assignments"])
    assert result["battery_count"] == 3
    assert result["fold_count"] == 3
    assert len(result["battery_results"]) == 3
    assert assignments.groupby(["fold", "battery_id"])["role"].nunique().max() == 1
    assert assignments.loc[assignments["battery_id"] == "B1", "fold"].nunique() == 3


def test_lobo_rejects_duplicate_measurement_event_identity() -> None:
    frame = _cohort_frame()
    frame.loc[1, "measurement_event_id"] = frame.loc[0, "measurement_event_id"]

    with pytest.raises(ValueError, match="measurement_event_id values must be unique"):
        evaluate_cohort_lobo(
            frame,
            dataset_id="COHORT::duplicate-events",
            features=["x"],
            target="soc",
            strategies=["DUMMY_MEAN"],
        )


@pytest.mark.parametrize("column", ["x", "soc"])
@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_lobo_rejects_non_finite_predictor_or_target(
    column: str, invalid_value: float
) -> None:
    frame = _cohort_frame()
    frame.loc[0, column] = invalid_value

    with pytest.raises(ValueError, match=rf"{column!r}.*finite"):
        evaluate_cohort_lobo(
            frame,
            dataset_id="COHORT::non-finite",
            features=["x"],
            target="soc",
            strategies=["DUMMY_MEAN"],
        )


def test_lobo_rejects_source_dataset_spanning_multiple_declared_identities() -> None:
    frame = _cohort_frame()
    frame.loc[frame.index[0], "source_dataset_id"] = "DS::shared"
    frame.loc[frame.index[-1], "source_dataset_id"] = "DS::shared"

    with pytest.raises(ValueError, match="exactly one Battery/Experiment identity"):
        evaluate_cohort_lobo(
            frame,
            dataset_id="COHORT::misidentified-source",
            features=["x"],
            target="soc",
            strategies=["DUMMY_MEAN"],
        )


@pytest.mark.parametrize("column", ["battery_id", "experiment_id", "source_dataset_id"])
def test_lobo_rejects_blank_or_untrimmed_identity_values(column: str) -> None:
    frame = _cohort_frame()
    frame.loc[0, column] = " "

    with pytest.raises(ValueError, match=f"{column} values must be non-empty trimmed strings"):
        evaluate_cohort_lobo(
            frame,
            dataset_id="COHORT::invalid-identity",
            features=["x"],
            target="soc",
            strategies=["DUMMY_MEAN"],
        )


def test_lobo_repeat_is_deterministic_and_target_is_not_used_for_split() -> None:
    frame = _cohort_frame()
    first = evaluate_cohort_lobo(
        frame,
        dataset_id="COHORT::synthetic",
        features=["x"],
        target="soc",
        strategies=["DUMMY_MEAN"],
    )
    frame["soc"] = frame["soc"].sample(frac=1, random_state=91).to_numpy()
    second = evaluate_cohort_lobo(
        frame,
        dataset_id="COHORT::synthetic",
        features=["x"],
        target="soc",
        strategies=["DUMMY_MEAN"],
    )

    assert first["split_id"] == second["split_id"]
    assert [row["held_out_battery_id"] for row in first["battery_results"]] == [
        row["held_out_battery_id"] for row in second["battery_results"]
    ]


def test_model_fit_view_never_contains_held_out_target(monkeypatch: pytest.MonkeyPatch) -> None:
    original_fit = cohort_lobo.fit_model

    def inspect_training_view(view, spec):
        assert not hasattr(view, "y_held_out")
        assert view.y_train.index.isin(view.x_train.index).all()
        assert not set(view.held_out_group_ids).intersection(view.train_group_ids)
        return original_fit(view, spec)

    monkeypatch.setattr(cohort_lobo, "fit_model", inspect_training_view)
    result = evaluate_cohort_lobo(
        _cohort_frame(),
        dataset_id="COHORT::synthetic",
        features=["x"],
        target="soc",
        strategies=["DUMMY_MEAN"],
    )

    assert result["fold_count"] == 3

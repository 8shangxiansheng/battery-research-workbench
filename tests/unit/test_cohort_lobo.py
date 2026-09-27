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
    assert result["leakage_audit"]["group_overlap"] is False
    assert result["leakage_audit"]["group_column"] == "battery_id"
    assert len(result["battery_results"]) == 3
    macro = result["macro_by_strategy"]["DUMMY_MEAN"]
    battery_maes = [row["overall"]["MAE"] for row in result["battery_results"]]
    assert macro["macro_MAE"] == sum(battery_maes) / len(battery_maes)
    assert macro["aggregation"] == "MACRO_MEAN_OF_BATTERY_METRICS"
    assert result["pooled_row_diagnostic_by_strategy"]["DUMMY_MEAN"]["MAE"] != macro["macro_MAE"]
    assert all(
        row["train_battery_ids"] != [row["held_out_battery_id"]]
        for row in result["battery_results"]
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

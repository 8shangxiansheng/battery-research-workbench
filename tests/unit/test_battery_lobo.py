"""Synthetic acceptance tests for the deterministic LOBO kernel."""

from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.modeling import engine as modeling_engine
from battery_workbench.splits.engine import (
    SplitInfeasibleError,
    build_assignments,
    feasibility_check,
    leakage_audit,
)
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy


def _battery_frame() -> pd.DataFrame:
    rows = []
    # Deliberately unequal event counts; each battery spans multiple experiments/cycles.
    for battery_id, experiments in {
        "BAT::A": {
            "EXP::1": {"CYCLE::1": 2, "CYCLE::2": 1},
            "EXP::2": {"CYCLE::1": 1},
        },
        "BAT::B": {
            "EXP::1": {"CYCLE::1": 4, "CYCLE::2": 2},
            "EXP::2": {"CYCLE::1": 2},
        },
        "BAT::C": {
            "EXP::1": {"CYCLE::1": 7, "CYCLE::2": 3},
            "EXP::2": {"CYCLE::1": 4},
        },
    }.items():
        for experiment_id, cycles in experiments.items():
            for cycle_group_id, event_count in cycles.items():
                for index in range(event_count):
                    event_id = f"{battery_id}:{experiment_id}:{cycle_group_id}:{index}"
                    rows.append(
                        {
                            "measurement_event_id": event_id,
                            "battery_id": battery_id,
                            "experiment_id": experiment_id,
                            "cycle_group_id": cycle_group_id,
                            "target": float(index),
                        }
                    )
    return pd.DataFrame(rows)


def _battery_spec(**overrides) -> SplitSpec:
    values = {
        "strategy": SplitStrategy.LEAVE_ONE_GROUP_OUT,
        "split_unit": "BATTERY",
        "group_column": "battery_id",
        "dataset_id": "COHORT::synthetic",
    }
    values.update(overrides)
    return SplitSpec(**values)


def test_lobo_emits_one_atomic_held_out_battery_per_fold() -> None:
    frame = _battery_frame()
    spec = _battery_spec()
    assignments = build_assignments(spec, frame)

    assert assignments["fold"].nunique() == frame["battery_id"].nunique() == 3
    for _, fold in assignments.groupby("fold"):
        held_out = fold.loc[fold["role"] == "HELD_OUT", "battery_id"].unique()
        train = fold.loc[fold["role"] == "TRAIN", "battery_id"].unique()
        assert len(held_out) == 1
        assert set(train).isdisjoint(set(held_out))
        assert set(train) | set(held_out) == set(frame["battery_id"])
        assert fold.groupby("battery_id")["role"].nunique().max() == 1

    held_out_by_battery = (
        assignments.query("role == 'HELD_OUT'").groupby("battery_id")["fold"].nunique()
    )
    assert held_out_by_battery.to_dict() == {"BAT::A": 1, "BAT::B": 1, "BAT::C": 1}
    audit = leakage_audit(spec, assignments, frame)
    assert audit["group_overlap"] is False
    assert audit["group_column"] == "battery_id"


def test_lobo_assignment_is_independent_of_row_order_and_target_values() -> None:
    frame = _battery_frame()
    spec = _battery_spec()
    baseline = build_assignments(spec, frame)
    shuffled = build_assignments(spec, frame.sample(frac=1, random_state=42))
    changed_target = frame.assign(target=range(len(frame), 0, -1))

    pd.testing.assert_frame_equal(baseline, shuffled)
    pd.testing.assert_frame_equal(baseline, build_assignments(spec, changed_target))


def test_lobo_requires_battery_identity_and_at_least_two_groups() -> None:
    with pytest.raises(ValueError, match="BATTERY.*battery_id"):
        _battery_spec(group_column="cycle_group_id")

    frame = _battery_frame().query("battery_id == 'BAT::A'")
    with pytest.raises(SplitInfeasibleError, match="only 1 group"):
        feasibility_check(_battery_spec(), frame)

    frame.loc[frame.index[0], "battery_id"] = None
    with pytest.raises(ValueError, match="null group id"):
        feasibility_check(_battery_spec(), frame)


def test_lobo_macro_is_equal_weighted_by_battery_not_event_count() -> None:
    aggregate = getattr(modeling_engine, "macro_average_by_battery", None)
    assert callable(aggregate), "modeling engine must expose explicit battery macro aggregation"

    metrics = [
        {"battery_id": "BAT::A", "overall": {"MAE": 1.0, "RMSE": 2.0, "n": 2}},
        {"battery_id": "BAT::B", "overall": {"MAE": 9.0, "RMSE": 10.0, "n": 16}},
    ]
    result = aggregate(metrics)

    assert result["macro_MAE"] == 5.0
    assert result["macro_RMSE"] == 6.0
    assert result["battery_count"] == result["fold_count"] == 2
    assert result["aggregation"] == "MACRO_MEAN_OF_BATTERY_METRICS"
    assert "pooled_row" not in result["aggregation"].lower()
    pooled_mae = (1.0 * 2 + 9.0 * 16) / 18
    assert result["macro_MAE"] != pooled_mae


def test_battery_macro_rejects_duplicate_or_missing_battery_metrics() -> None:
    aggregate = getattr(modeling_engine, "macro_average_by_battery", None)
    assert callable(aggregate), "modeling engine must expose explicit battery macro aggregation"
    duplicate = [
        {"battery_id": "BAT::A", "overall": {"MAE": 1.0}},
        {"battery_id": "BAT::A", "overall": {"MAE": 3.0}},
    ]
    with pytest.raises(ValueError, match="one metric record per battery"):
        aggregate(duplicate)
    with pytest.raises(ValueError, match="non-empty battery_id"):
        aggregate([{"overall": {"MAE": 1.0}}])

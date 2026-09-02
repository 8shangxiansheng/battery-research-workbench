"""BRW-020 T01-T19: split spec, deterministic ids, feasibility, assignment,
leakage audit, readiness."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from battery_workbench.splits.engine import (
    SplitInfeasibleError,
    build_assignments,
    feasibility_check,
    leakage_audit,
)
from battery_workbench.splits.readiness import evaluate_readiness
from battery_workbench.splits.schemas import (
    SplitSpec,
    SplitStrategy,
    split_id_for,
)


def _group_frame(group_column: str, groups: dict[str, int]) -> pd.DataFrame:
    rows = []
    for gid, count in groups.items():
        for i in range(count):
            rows.append({"measurement_event_id": f"{gid}::{i}", group_column: gid})
    return pd.DataFrame(rows)


def _two_cycle_frame() -> pd.DataFrame:
    return _group_frame("cycle_group_id", {"CG::1": 10, "CG::2": 8})


def _four_group_frame() -> pd.DataFrame:
    return _group_frame("cycle_group_id", {f"CG::{i}": 5 for i in range(1, 5)})


def _spec(**overrides) -> SplitSpec:
    values = {
        "strategy": SplitStrategy.LEAVE_ONE_GROUP_OUT,
        "split_unit": "CYCLE",
        "group_column": "cycle_group_id",
        "dataset_id": "DS::test",
    }
    values.update(overrides)
    return SplitSpec(**values)


# --- T01-T03: SplitSpec + deterministic id ---


def test_t01_spec_rejects_random_and_row_strategies() -> None:
    for bad in (
        "RANDOM_FRAME_SPLIT",
        "RANDOM_ROW_SPLIT",
        "RANDOM_MEASUREMENT_EVENT_SPLIT",
        "SOC_BIN_ROW_SPLIT",
    ):
        with pytest.raises(ValueError, match="prohibited"):
            SplitSpec(strategy=bad, split_unit="CYCLE", group_column="cycle_group_id")


def test_t02_split_id_deterministic() -> None:
    s = _spec()
    assert s.split_id == split_id_for(_spec())
    assert s.split_id.startswith("SPLIT::")


def test_t03_assignment_change_changes_split_id() -> None:
    assert _spec().split_id != _spec(k=2).split_id
    assert _spec(dataset_id="DS::other").split_id != _spec(dataset_id="DS::test").split_id


# --- T05-T08: group integrity ---


def test_t05_null_group_id_rejected() -> None:
    frame = _two_cycle_frame()
    frame.loc[0, "cycle_group_id"] = None
    with pytest.raises(ValueError, match="null"):
        feasibility_check(_spec(), frame)


def test_t06_t08_same_cycle_never_crosses_roles() -> None:
    """T06 train/test, T07 train/val, T08 val/test — a cycle group is atomic."""
    frame = _four_group_frame()
    spec = _spec(strategy=SplitStrategy.GROUP_HOLDOUT, explicit_holdout_groups=["CG::4"])
    assignments = build_assignments(spec, frame)
    # leave-one-cycle-out style: every (fold, group) pair carries exactly one role
    per_pair = assignments.groupby(["fold", "cycle_group_id"])["role"].nunique()
    assert per_pair.max() == 1
    # and holdout group is fully out of TRAIN folds' validation role, etc.
    train_groups = set(assignments[assignments["role"] == "TRAIN"]["cycle_group_id"])
    val_groups = set(assignments[assignments["role"] == "VALIDATION"]["cycle_group_id"])
    assert train_groups.isdisjoint(val_groups)


# --- T09-T12: feasibility ---


def test_t09_two_groups_cannot_make_three_way() -> None:
    frame = _two_cycle_frame()
    with pytest.raises(Exception) as exc:
        feasibility_check(
            _spec(strategy=SplitStrategy.GROUP_HOLDOUT, explicit_holdout_groups=["CG::1"]),
            frame,
            require_roles=("TRAIN", "VALIDATION", "TEST"),
        )
    assert "options" in str(exc.value)


def test_t10_two_groups_leave_one_out_works() -> None:
    frame = _two_cycle_frame()
    feasibility_check(_spec(), frame)
    assignments = build_assignments(_spec(), frame)
    folds = assignments["fold"].nunique()
    assert folds == 2
    for fold, fold_df in assignments.groupby("fold"):
        held_groups = fold_df[fold_df["role"] == "HELD_OUT"]["cycle_group_id"].unique()
        assert len(held_groups) == 1


def test_t11_k_greater_than_group_count_rejected() -> None:
    frame = _two_cycle_frame()
    with pytest.raises(SplitInfeasibleError):
        feasibility_check(_spec(strategy=SplitStrategy.K_FOLD_GROUPED, k=3), frame)


def test_t12_one_group_no_held_out_evaluation() -> None:
    frame = _group_frame("cycle_group_id", {"CG::1": 10})
    with pytest.raises(Exception, match="options"):
        feasibility_check(_spec(), frame)
    # TRAIN_ONLY is legal with one group
    feasibility_check(_spec(strategy=SplitStrategy.TRAIN_ONLY), frame)


def test_t13_train_only_works() -> None:
    frame = _two_cycle_frame()
    assignments = build_assignments(_spec(strategy=SplitStrategy.TRAIN_ONLY), frame)
    assert (assignments["role"] == "TRAIN").all()
    assert assignments["fold"].nunique() == 1


# --- T14: SOH readiness ---


def test_t14_soh_readiness_not_ready_for_model() -> None:
    readiness = evaluate_readiness(
        dataset_family="SOH_CAPACITY",
        independent_soh_states=2,
        battery_count=1,
        cycle_group_count=2,
    )
    assert readiness["status"] == "NOT_READY_FOR_MODEL_EVALUATION"
    soc = evaluate_readiness(
        dataset_family="SOC",
        independent_soh_states=None,
        battery_count=1,
        cycle_group_count=2,
    )
    assert soc["status"] == "READY_FOR_LIMITED_EVALUATION"


# --- T15-T18: assignments ---


def test_t15_all_assignments_originate_from_dataset() -> None:
    """Fold-grain assignments: every fold covers exactly the dataset events."""
    frame = _four_group_frame()
    assignments = build_assignments(_spec(), frame)
    fold_count = assignments["fold"].nunique()
    assert fold_count == 4  # one held-out group per fold
    for _, fold_df in assignments.groupby("fold"):
        assert set(fold_df["measurement_event_id"]) == set(frame["measurement_event_id"])
        assert len(fold_df) == len(frame)


def test_t16_deterministic_fold_ordering() -> None:
    frame = _four_group_frame()
    a1 = build_assignments(_spec(), frame)
    a2 = build_assignments(_spec(), frame.sample(frac=1.0, random_state=7))
    assert a1.sort_values("measurement_event_id")[["fold", "role"]].equals(
        a2.sort_values("measurement_event_id")[["fold", "role"]]
    )


def test_t17_row_counts_reconcile() -> None:
    frame = _four_group_frame()
    assignments = build_assignments(_spec(), frame)
    counts = assignments.groupby("fold")["role"].value_counts().unstack(fill_value=0)
    # every fold reconciles to the full dataset; per fold exactly one group held out
    assert counts.sum(axis=1).eq(len(frame)).all()
    for fold, fold_df in assignments.groupby("fold"):
        held_rows = (fold_df["role"] == "HELD_OUT").sum()
        assert held_rows == len(frame) // 4


def test_t18_exact_explicit_group_holdout() -> None:
    frame = _four_group_frame()
    spec = _spec(
        strategy=SplitStrategy.GROUP_HOLDOUT,
        explicit_holdout_groups=["CG::3", "CG::4"],
    )
    assignments = build_assignments(spec, frame)
    held_out = assignments[assignments["role"] == "VALIDATION"]["cycle_group_id"].unique()
    assert set(held_out) == {"CG::3", "CG::4"}


def test_t19_dataset_unchanged(tmp_path) -> None:
    """split materialization must not touch the dataset directory."""
    frame = _four_group_frame()
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    frame.to_parquet(dataset_dir / "dataset.parquet")
    before = sorted(p.name for p in dataset_dir.iterdir())
    # (materialization test lives in persistence tests; here assert engine purity)
    build_assignments(_spec(), frame)
    after = sorted(p.name for p in dataset_dir.iterdir())
    assert before == after


# --- leakage audit ---


def test_leakage_audit_flags() -> None:
    frame = _four_group_frame()
    spec = _spec()
    assignments = build_assignments(spec, frame)
    audit = leakage_audit(spec, assignments, frame)
    assert audit["frame_random_split"] is False
    assert audit["cycle_overlap"] is False
    assert audit["target_used_for_assignment"] is False


def test_target_column_never_used_for_assignment() -> None:
    frame = _four_group_frame()
    frame["soc_reference_percent"] = [
        10.0 * (i % 4) for i in range(len(frame))
    ]  # deliberately informative target
    spec = _spec()
    a1 = build_assignments(spec, frame)
    frame2 = frame.copy()
    frame2["soc_reference_percent"] = frame2["soc_reference_percent"].iloc[::-1].values
    a2 = build_assignments(spec, frame2)
    assert a1[["measurement_event_id", "role", "fold"]].equals(
        a2[["measurement_event_id", "role", "fold"]]
    )


# --- BRW-020 FINAL: LEAVE_ONE_GROUP_OUT held-out role semantics ---


def test_loo_fold_roles_exact_train_and_held_out() -> None:
    """Fold1: TRAIN=CG::2 / HELD_OUT=CG::1; Fold2 swapped. No VALIDATION role."""
    frame = _two_cycle_frame()
    assignments = build_assignments(_spec(), frame)
    fold1 = assignments[assignments["fold"] == "fold1"]
    fold2 = assignments[assignments["fold"] == "fold2"]
    assert set(fold1[fold1["role"] == "TRAIN"]["cycle_group_id"]) == {"CG::2"}
    assert set(fold1[fold1["role"] == "HELD_OUT"]["cycle_group_id"]) == {"CG::1"}
    assert set(fold2[fold2["role"] == "TRAIN"]["cycle_group_id"]) == {"CG::1"}
    assert set(fold2[fold2["role"] == "HELD_OUT"]["cycle_group_id"]) == {"CG::2"}
    assert "VALIDATION" not in set(assignments["role"])
    assert set(assignments["role"]) == {"TRAIN", "HELD_OUT"}


def test_loo_require_roles_normalized_to_held_out() -> None:
    spec = _spec()
    assert spec.require_roles == ["TRAIN", "HELD_OUT"]


def test_k_fold_keeps_validation_role() -> None:
    frame = _four_group_frame()
    spec = _spec(strategy=SplitStrategy.K_FOLD_GROUPED, k=2)
    assignments = build_assignments(spec, frame)
    assert set(assignments["role"]) == {"TRAIN", "VALIDATION"}


def test_manifest_declares_limited_evaluation_type(tmp_path) -> None:
    from battery_workbench.splits.persistence import write_split_payload

    spec = _spec()
    assignments = build_assignments(spec, _two_cycle_frame())
    paths = write_split_payload(
        spec=spec,
        assignments=assignments,
        dataset_id=spec.dataset_id,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOC",
        output_root=tmp_path,
        group_counts={"CG::1": 10, "CG::2": 8},
        dataset_status="READY_WITH_LIMITATIONS",
    )
    manifest = json.loads((tmp_path / paths["split_manifest"]).read_text())
    assert manifest["evaluation_type"] == "LEAVE_ONE_GROUP_OUT_LIMITED_EVALUATION"
    assert manifest["evaluation_scope"] == "WITHIN_BATTERY_CROSS_CYCLE"
    role_sem = manifest["role_semantics"]
    assert role_sem["independent_validation_groups"] == 0
    assert role_sem["independent_test_groups"] == 0
    assert role_sem["three_way_structure_present"] is False
    assert role_sem["held_out_role"] == "HELD_OUT"
    # HELD_OUT target is off-limits to model selection
    assert role_sem["held_out_target_usage"] == "FORBIDDEN_FOR_MODEL_SELECTION"


def test_train_only_view_returns_only_train_rows() -> None:
    from battery_workbench.splits.engine import train_only_view

    frame = _two_cycle_frame()
    assignments = build_assignments(_spec(), frame)
    view = train_only_view(assignments, frame, fold="fold1")
    assert set(view["cycle_group_id"]) == {"CG::2"}
    assert set(view["measurement_event_id"]) <= set(frame["measurement_event_id"])


def test_held_out_target_unavailable_to_train_only_selector() -> None:
    """BRW-021 contract: the train-only selector cannot consume HELD_OUT target."""
    from battery_workbench.splits.engine import (
        assert_no_held_out_consumption,
        train_only_view,
    )

    frame = _two_cycle_frame()
    frame["soc_reference_percent"] = [10.0, 20.0] * 9
    assignments = build_assignments(_spec(), frame)
    train_view = train_only_view(assignments, frame, fold="fold1")
    # selector uses TRAIN rows only → passes
    assert assert_no_held_out_consumption(train_view, assignments, fold="fold1") is True
    # any consumption of HELD_OUT rows (even one) violates the contract
    leaked = pd.concat([train_view, frame[frame["cycle_group_id"] == "CG::1"]])
    with pytest.raises(ValueError, match="HELD_OUT"):
        assert_no_held_out_consumption(leaked, assignments, fold="fold1")


def test_held_out_target_guard_names_the_leak() -> None:
    from battery_workbench.splits.engine import (
        assert_no_held_out_consumption,
        train_only_view,
    )

    frame = _two_cycle_frame()
    assignments = build_assignments(_spec(), frame)
    train_view = train_only_view(assignments, frame, fold="fold1")
    leaked_id = frame[frame["cycle_group_id"] == "CG::1"]["measurement_event_id"].iloc[0]
    bad = pd.concat([train_view, frame[frame["measurement_event_id"] == leaked_id]])
    with pytest.raises(ValueError, match=leaked_id):
        assert_no_held_out_consumption(bad, assignments, fold="fold1")

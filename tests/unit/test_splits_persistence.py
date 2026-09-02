"""BRW-020 T20-T29: persistence contract + orchestrator SPLIT integration."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.splits.engine import build_assignments
from battery_workbench.splits.persistence import (
    write_split_payload,
)
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy


def _group_frame(groups: dict[str, int]) -> pd.DataFrame:
    rows = []
    for gid, count in groups.items():
        for i in range(count):
            rows.append({"measurement_event_id": f"{gid}::{i}", "cycle_group_id": gid})
    return pd.DataFrame(rows)


def _four_group_frame() -> pd.DataFrame:
    return _group_frame({f"CG::{i}": 5 for i in range(1, 5)})


def _spec(**overrides) -> SplitSpec:
    values = {
        "strategy": SplitStrategy.LEAVE_ONE_GROUP_OUT,
        "split_unit": "CYCLE",
        "group_column": "cycle_group_id",
        "dataset_id": "DS::test",
    }
    values.update(overrides)
    return SplitSpec(**values)


def _materialize(tmp_path: Path, frame: pd.DataFrame | None = None, **spec_overrides):
    frame = frame if frame is not None else _four_group_frame()
    spec = _spec(**spec_overrides)
    assignments = build_assignments(spec, frame)
    return write_split_payload(
        spec=spec,
        assignments=assignments,
        dataset_id=spec.dataset_id,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOC",
        output_root=tmp_path,
        group_counts=frame.groupby("cycle_group_id").size().to_dict(),
    )


def test_t20_same_spec_same_split_id(tmp_path: Path) -> None:
    p1 = _materialize(tmp_path / "a")
    p2 = _materialize(tmp_path / "b")
    assert p1["split_id"] == p2["split_id"]


def test_output_contract_layout(tmp_path: Path) -> None:
    paths = _materialize(tmp_path)
    split_dir = tmp_path / "splits/CELL_001/EXP_001/DS::test" / paths["split_id"]
    for name in (
        "split_assignments.parquet",
        "split_manifest.json",
        "split_schema.json",
        "evaluation_readiness.json",
        "leakage_audit.json",
    ):
        assert (split_dir / name).exists(), f"missing {name}"
    assert (
        tmp_path / "artifacts/CELL_001/EXP_001/splits" / paths["split_id"] / "split_report.json"
    ).exists()
    assert (
        tmp_path / "artifacts/CELL_001/EXP_001/splits" / paths["split_id"] / "split_report.html"
    ).exists()


def test_dataset_directory_untouched(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "splits/CELL_001/EXP_001/DS::test"
    dataset_dir.mkdir(parents=True)
    marker = dataset_dir / "keep.txt"
    marker.write_text("dataset stays here")
    _materialize(tmp_path)
    assert marker.exists() and marker.read_text() == "dataset stays here"


def test_manifest_records_provenance(tmp_path: Path) -> None:
    paths = _materialize(tmp_path)
    manifest = json.loads((tmp_path / paths["split_manifest"]).read_text())
    assert manifest["dataset_id"] == "DS::test"
    assert manifest["split_id"] == paths["split_id"]
    assert manifest["strategy"] == "LEAVE_ONE_GROUP_OUT"
    assert manifest["split_unit"] == "CYCLE"
    assert manifest["group_column"] == "cycle_group_id"
    assert manifest["evaluation_scope"] == "WITHIN_BATTERY_CROSS_CYCLE"
    assert manifest["leakage_audit"]["frame_random_split"] is False


# --- orchestrator integration (T21-T25, T29) ---


@pytest.mark.skipif(
    not Path("data/processed/datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e").exists(),
    reason="real CELL_001/EXP_001 dataset not available",
)
class TestOrchestratorSplit:
    def _engine(self, tmp_path: Path):
        from battery_workbench.orchestrator.engine import PipelineOrchestrator

        return PipelineOrchestrator(
            raw_root=Path("data/raw"),
            processed_root=Path("data/processed"),
            runs_root=tmp_path / "runs",
        )

    def test_t21_split_depends_on_dataset(self, tmp_path: Path) -> None:
        from battery_workbench.orchestrator.dag import NODE_DEPENDENCIES

        assert NODE_DEPENDENCIES["SPLIT"] == ["DATASET"]

    def test_t22_existing_split_reused(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        plan = engine.plan_run(
            profile="BUILD_DATASET",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=True,
            stages=["DATASET", "SPLIT"],
            target="soc_reference_percent",
            features={"selected_features": ["amplitude_a_u"]},
            analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
            parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
            split={
                "strategy": "LEAVE_ONE_GROUP_OUT",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
            },
        )
        # first materialize the split via a real (non-dry) run
        plan_real = plan.model_copy(
            update={"execution": plan.execution.model_copy(update={"dry_run": False})}
        )
        run1 = engine.start_run(plan_real)
        split_state = next(n for n in run1["nodes"] if n["node_id"] == "SPLIT")
        assert split_state["state"] in {"SUCCEEDED", "REUSED"}
        # second identical run: SPLIT reuses
        run2 = engine.start_run(plan_real)
        split2 = next(n for n in run2["nodes"] if n["node_id"] == "SPLIT")
        assert split2["state"] == "REUSED"

    def test_t23_dataset_change_reevaluates_split(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        common = {
            "profile": "BUILD_DATASET",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dry_run": True,
            "stages": ["DATASET", "SPLIT"],
            "target": "soc_reference_percent",
            "analysis_slice": {"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
            "parameters": {"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
            "split": {
                "strategy": "LEAVE_ONE_GROUP_OUT",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
            },
        }
        p1 = engine.plan_run(features={"selected_features": ["amplitude_a_u"]}, **common)
        p2 = engine.plan_run(features={"selected_features": ["waveform_rms_a_u"]}, **common)
        e1 = engine.dry_run(p1)
        e2 = engine.dry_run(p2)
        s1 = next(n for n in e1.nodes if n.node_id == "SPLIT")
        s2 = next(n for n in e2.nodes if n.node_id == "SPLIT")
        assert s1.state == "REUSED"
        assert s2.state == "RUNNING"  # different dataset → split re-evaluated

    def test_t24_impossible_three_way_waits_for_user(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        plan = engine.plan_run(
            profile="BUILD_DATASET",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=False,
            stages=["DATASET", "SPLIT"],
            target="soc_reference_percent",
            features={"selected_features": ["amplitude_a_u"]},
            analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
            parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
            split={
                "strategy": "GROUP_HOLDOUT",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
                "explicit_holdout_groups": ["CG::CELL_001::EXP_001::1"],
                "require_roles": ["TRAIN", "VALIDATION", "TEST"],
            },
        )
        run = engine.start_run(plan)
        split_state = next(n for n in run["nodes"] if n["node_id"] == "SPLIT")
        assert split_state["state"] == "WAITING_FOR_USER"
        actions = engine.list_user_actions(run["run_id"])
        assert any(a["action_type"] == "SELECT_SPLIT_SCHEME" for a in actions)
        assert any("LEAVE_ONE_GROUP_OUT" in json.dumps(a["options"]) for a in actions)
        # resume with a legal choice
        action = next(a for a in actions if a["action_type"] == "SELECT_SPLIT_SCHEME")
        resumed = engine.resume_run(
            run["run_id"],
            user_inputs={
                "split": {
                    "strategy": "LEAVE_ONE_GROUP_OUT",
                    "split_unit": "CYCLE",
                    "group_column": "cycle_group_id",
                }
            },
            action_id=action["action_id"],
        )
        split_state = next(n for n in resumed["nodes"] if n["node_id"] == "SPLIT")
        assert split_state["state"] in {"SUCCEEDED", "REUSED"}

    def test_t29_frame_random_prohibition_preserved(self, tmp_path: Path) -> None:
        from battery_workbench.splits.schemas import SplitSpec

        with pytest.raises(ValueError, match="prohibited"):
            SplitSpec(
                strategy="RANDOM_FRAME_SPLIT", split_unit="FRAME", group_column="frame_index_raw"
            )
        engine = self._engine(tmp_path)
        plan = engine.plan_run(
            profile="BUILD_DATASET",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=False,
            stages=["DATASET", "SPLIT"],
            target="soc_reference_percent",
            features={"selected_features": ["amplitude_a_u"]},
            analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
            parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
            split={
                "strategy": "RANDOM_FRAME_SPLIT",
                "split_unit": "FRAME",
                "group_column": "frame_index_raw",
            },
        )
        run = engine.start_run(plan)
        split_state = next(n for n in run["nodes"] if n["node_id"] == "SPLIT")
        # prohibited strategy → the orchestrator asks for a legal scheme
        # (never silently executes a random split)
        assert split_state["state"] == "WAITING_FOR_USER"
        actions = engine.list_user_actions(run["run_id"])
        assert any("prohibited" in a["message"] for a in actions)

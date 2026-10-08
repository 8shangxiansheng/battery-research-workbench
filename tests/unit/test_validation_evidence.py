from __future__ import annotations

import hashlib
import json

import pandas as pd

from battery_workbench.splits.engine import build_assignments
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy
from battery_workbench.splits.validation_evidence import inspect_independent_validation_evidence


def _write_verified_fixture(root):
    groups = [f"CG::{index}" for index in range(1, 6)]
    dataset = pd.DataFrame(
        [
            {"measurement_event_id": f"{group}::{row}", "cycle_group_id": group, "y": float(row)}
            for group in groups
            for row in range(2)
        ]
    )
    dataset_id = "DS::fixture"
    dataset_dir = root / "datasets/CELL_001/EXP_001/SOC" / dataset_id
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    dataset.to_parquet(dataset_path, index=False)
    dataset_checksum = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "dataset_status": "READY_FOR_SPLIT",
                "output_checksum": dataset_checksum,
            }
        )
    )
    spec = SplitSpec(
        strategy=SplitStrategy.GROUP_HOLDOUT,
        split_unit="CYCLE",
        group_column="cycle_group_id",
        dataset_id=dataset_id,
        explicit_holdout_groups=[groups[-1]],
        require_roles=["TRAIN", "VALIDATION", "HELD_OUT"],
    )
    assignments = build_assignments(spec, dataset)
    split_dir = root / "splits/CELL_001/EXP_001" / dataset_id / spec.split_id
    split_dir.mkdir(parents=True)
    assignment_path = split_dir / "split_assignments.parquet"
    assignments.to_parquet(assignment_path, index=False)
    checksum = hashlib.sha256(assignment_path.read_bytes()).hexdigest()
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "split_id": spec.split_id,
                "dataset_id": dataset_id,
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "strategy": "GROUP_HOLDOUT",
                "group_column": "cycle_group_id",
                "output_checksums": {"split_assignments": checksum},
            }
        )
    )
    return assignment_path


def test_accepts_only_checksum_verified_three_role_artifacts(tmp_path):
    _write_verified_fixture(tmp_path)
    result = inspect_independent_validation_evidence(
        tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
    )
    assert result["available"] is True
    assert len(result["verified_split_ids"]) == 1
    assert result["evidence"][0]["group_counts"] == {
        "TRAIN": 3,
        "VALIDATION": 1,
        "HELD_OUT": 1,
    }


def test_rejects_assignment_checksum_mismatch(tmp_path):
    assignment_path = _write_verified_fixture(tmp_path)
    assignment_path.write_bytes(assignment_path.read_bytes() + b"corrupt")
    result = inspect_independent_validation_evidence(
        tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
    )
    assert result["available"] is False
    assert "checksum-mismatched" in result["rejected"][0]["reason"]


def test_does_not_treat_existing_leave_one_group_out_as_validation(tmp_path):
    _write_verified_fixture(tmp_path)
    for path in (tmp_path / "splits").rglob("split_manifest.json"):
        manifest = json.loads(path.read_text())
        manifest["strategy"] = "LEAVE_ONE_GROUP_OUT"
        path.write_text(json.dumps(manifest))
    result = inspect_independent_validation_evidence(
        tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
    )
    assert result["available"] is False
    assert "GROUP_HOLDOUT" in result["rejected"][0]["reason"]

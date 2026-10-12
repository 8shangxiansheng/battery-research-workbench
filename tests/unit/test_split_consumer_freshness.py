from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from battery_workbench.orchestrator import nodes as orchestrator_nodes
from battery_workbench.orchestrator.nodes import (
    FeatureAnalysisNode,
    SocModelingNode,
    SplitNode,
    _require_current_split_assignments_path,
)
from battery_workbench.orchestrator.schemas import AnalysisPlan, ArtifactRef, PlanProject
from battery_workbench.splits.integrity import split_assignment_reasons


def _current_split(tmp_path: Path) -> tuple[ArtifactRef, SimpleNamespace, Path]:
    processed_root = tmp_path / "processed"
    dataset_dir = processed_root / "datasets" / "CELL_TEST" / "EXP_TEST" / "SOC" / "DS::test"
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_TEST"],
            "experiment_id": ["EXP_TEST"],
            "measurement_event_id": ["ME::1"],
            "cycle_group_id": ["CYCLE::1"],
            "soc_reference_percent": [50.0],
            "peak_to_peak_v": [0.5],
        }
    ).to_parquet(dataset_path, index=False)
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_manifest_path.write_text('{"dataset_id":"DS::test"}', encoding="utf-8")
    split_dir = (
        processed_root
        / "splits"
        / "CELL_TEST"
        / "EXP_TEST"
        / "DS::test"
        / "SPLIT::test"
    )
    split_dir.mkdir(parents=True)
    outputs = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    checksums: dict[str, str] = {}
    for key, name in outputs.items():
        path = split_dir / name
        if key == "split_assignments":
            pd.DataFrame(
                {
                    "measurement_event_id": ["ME::1"],
                    "cycle_group_id": ["CYCLE::1"],
                    "fold": ["fold1"],
                    "role": ["TRAIN"],
                    "strategy": ["TRAIN_ONLY"],
                    "dataset_id": ["DS::test"],
                    "split_id": ["SPLIT::test"],
                }
            ).to_parquet(path, index=False)
        else:
            path.write_bytes((key + "\n").encode())
        checksums[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = split_dir / "split_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "split_id": "SPLIT::test",
                "dataset_id": "DS::test",
                "battery_id": "CELL_TEST",
                "experiment_id": "EXP_TEST",
                "group_column": "cycle_group_id",
                "split_unit": "CYCLE",
                "strategy": "TRAIN_ONLY",
                "group_counts": {"CYCLE::1": 1},
                "group_count": 1,
                "role_semantics": {
                    "held_out_role": "",
                    "independent_validation_groups": None,
                    "independent_test_groups": None,
                    "three_way_structure_present": False,
                    "held_out_target_usage": "NOT_APPLICABLE",
                    "note": "",
                },
                "row_count": 1,
                "fold_count": 1,
                "source_checksums": {
                    "dataset_parquet": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                    "dataset_manifest": hashlib.sha256(dataset_manifest_path.read_bytes()).hexdigest(),
                },
                "output_checksums": checksums,
            }
        ),
        encoding="utf-8",
    )
    ref = ArtifactRef(
        artifact_type="SPLIT",
        artifact_id="SPLIT::test",
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        path=str(split_dir),
        manifest_path=str(manifest_path),
    )
    return ref, SimpleNamespace(
        processed_root=processed_root,
        dataset_path=dataset_path,
        dataset_manifest_path=dataset_manifest_path,
    ), split_dir


def _assignments_path(split_ref: ArtifactRef, ctx: SimpleNamespace) -> Path:
    return _require_current_split_assignments_path(
        split_ref,
        ctx,
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        dataset_id="DS::test",
        dataset_path=ctx.dataset_path,
        dataset_manifest_path=ctx.dataset_manifest_path,
    )


def test_split_consumer_accepts_current_identity_and_outputs(tmp_path: Path) -> None:
    split_ref, ctx, split_dir = _current_split(tmp_path)

    actual = _assignments_path(split_ref, ctx)

    assert actual == split_dir / "split_assignments.parquet"


def test_split_consumer_blocks_tampered_assignment_bytes(tmp_path: Path) -> None:
    split_ref, ctx, split_dir = _current_split(tmp_path)
    (split_dir / "split_assignments.parquet").write_bytes(b"changed after manifest")

    with pytest.raises(ValueError, match="Split outputs are stale or unverifiable"):
        _assignments_path(split_ref, ctx)


def test_split_consumer_blocks_wrong_event_set_even_when_output_checksum_is_resealed(
    tmp_path: Path,
) -> None:
    split_ref, ctx, split_dir = _current_split(tmp_path)
    assignments_path = split_dir / "split_assignments.parquet"
    assignments = pd.read_parquet(assignments_path)
    assignments.loc[0, "measurement_event_id"] = "ME::not-in-dataset"
    assignments.to_parquet(assignments_path, index=False)
    manifest_path = Path(split_ref.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_checksums"]["split_assignments"] = hashlib.sha256(
        assignments_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:fold1"):
        _assignments_path(split_ref, ctx)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("duplicate", "SPLIT_ASSIGNMENT_DUPLICATE_EVENT:fold1"),
        ("group", "SPLIT_ASSIGNMENT_GROUP_MAPPING_MISMATCH:fold1"),
        ("group_counts", "SPLIT_GROUP_COUNTS_MISMATCH"),
        ("role", "SPLIT_TRAIN_ONLY_ROLE_SEMANTICS_INVALID"),
        ("role_manifest", "SPLIT_ROLE_SEMANTICS_MISMATCH"),
        ("row_count", "SPLIT_ASSIGNMENT_ROW_COUNT_MISMATCH"),
    ],
)
def test_split_consumer_blocks_semantically_invalid_assignment_inventory(
    tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    split_ref, ctx, split_dir = _current_split(tmp_path)
    assignments_path = split_dir / "split_assignments.parquet"
    assignments = pd.read_parquet(assignments_path)
    manifest_path = Path(split_ref.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "duplicate":
        assignments = pd.concat([assignments, assignments], ignore_index=True)
        manifest["row_count"] = len(assignments)
    elif mutation == "group":
        assignments.loc[0, "cycle_group_id"] = "CYCLE::wrong"
    elif mutation == "group_counts":
        manifest["group_counts"] = {"CYCLE::wrong": 1}
    elif mutation == "role":
        assignments.loc[0, "role"] = "HELD_OUT"
    elif mutation == "role_manifest":
        manifest["role_semantics"]["held_out_role"] = "HELD_OUT"
    else:
        manifest["row_count"] = 2
    assignments.to_parquet(assignments_path, index=False)
    manifest["output_checksums"]["split_assignments"] = hashlib.sha256(
        assignments_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_reason):
        _assignments_path(split_ref, ctx)


@pytest.mark.parametrize("strategy", ["LEAVE_ONE_GROUP_OUT", "GROUP_HOLDOUT"])
def test_split_assignment_semantics_accept_valid_grouped_strategies(
    tmp_path: Path, strategy: str
) -> None:
    processed_root = tmp_path / "processed"
    dataset_path = processed_root / "datasets/CELL/EXP/SOC/DS::grouped/dataset.parquet"
    dataset_path.parent.mkdir(parents=True)
    event_ids = ["ME::1", "ME::2"]
    cycle_ids = ["CYCLE::1", "CYCLE::2"]
    pd.DataFrame(
        {"measurement_event_id": event_ids, "cycle_group_id": cycle_ids}
    ).to_parquet(dataset_path, index=False)
    split_id = "SPLIT::grouped"
    rows = []
    if strategy == "LEAVE_ONE_GROUP_OUT":
        fold_roles = {
            "fold1": {"CYCLE::1": "HELD_OUT", "CYCLE::2": "TRAIN"},
            "fold2": {"CYCLE::1": "TRAIN", "CYCLE::2": "HELD_OUT"},
        }
        held_out = True
        require_roles = ["TRAIN", "HELD_OUT"]
        explicit_holdout_groups: list[str] = []
    else:
        fold_roles = {"fold1": {"CYCLE::1": "TRAIN", "CYCLE::2": "VALIDATION"}}
        held_out = False
        require_roles = ["TRAIN", "VALIDATION"]
        explicit_holdout_groups = ["CYCLE::2"]
    for fold, roles in fold_roles.items():
        for event_id, cycle_id in zip(event_ids, cycle_ids, strict=True):
            rows.append(
                {
                    "measurement_event_id": event_id,
                    "cycle_group_id": cycle_id,
                    "fold": fold,
                    "role": roles[cycle_id],
                    "strategy": strategy,
                    "dataset_id": "DS::grouped",
                    "split_id": split_id,
                }
            )
    assignments_path = (
        processed_root / "splits/CELL/EXP/DS::grouped" / split_id / "split_assignments.parquet"
    )
    assignments_path.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(assignments_path, index=False)
    manifest = {
        "split_id": split_id,
        "dataset_id": "DS::grouped",
        "strategy": strategy,
        "split_unit": "CYCLE",
        "group_column": "cycle_group_id",
        "group_counts": {"CYCLE::1": 1, "CYCLE::2": 1},
        "group_count": 2,
        "fold_count": len(fold_roles),
        "row_count": len(rows),
        "k": None,
        "explicit_holdout_groups": explicit_holdout_groups,
        "require_roles": require_roles,
        "role_semantics": {
            "held_out_role": "HELD_OUT" if held_out else "",
            "independent_validation_groups": 0 if held_out else None,
            "independent_test_groups": 0 if held_out else None,
            "three_way_structure_present": False,
            "held_out_target_usage": (
                "FORBIDDEN_FOR_MODEL_SELECTION" if held_out else "NOT_APPLICABLE"
            ),
            "note": (
                "independent cycles only; no simultaneous independent validation + test groups exist"
                if held_out
                else ""
            ),
        },
    }

    assert split_assignment_reasons(
        processed_root,
        manifest,
        assignments_path=assignments_path,
        dataset_path=dataset_path,
    ) == []


def test_split_cache_reuse_rejects_semantically_forged_assignments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed_root = tmp_path / "processed"
    dataset_dir = processed_root / "datasets/CELL_TEST/EXP_TEST/SOC/DS::cache"
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::1"],
            "cycle_group_id": ["CYCLE::1"],
        }
    ).to_parquet(dataset_path, index=False)
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_manifest_path.write_text("{}", encoding="utf-8")
    split_dir = processed_root / "splits/CELL_TEST/EXP_TEST/DS::cache/SPLIT::cache"
    split_dir.mkdir(parents=True)
    assignments_path = split_dir / "split_assignments.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::forged"],
            "cycle_group_id": ["CYCLE::1"],
            "fold": ["fold1"],
            "role": ["TRAIN"],
            "strategy": ["TRAIN_ONLY"],
            "dataset_id": ["DS::cache"],
            "split_id": ["SPLIT::cache"],
        }
    ).to_parquet(assignments_path, index=False)
    outputs = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    for output_name in ("leakage_audit", "evaluation_readiness"):
        (split_dir / outputs[output_name]).write_text("{}", encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "split_id": "SPLIT::cache",
        "dataset_id": "DS::cache",
        "battery_id": "CELL_TEST",
        "experiment_id": "EXP_TEST",
        "strategy": "TRAIN_ONLY",
        "split_unit": "CYCLE",
        "group_column": "cycle_group_id",
        "group_counts": {"CYCLE::1": 1},
        "group_count": 1,
        "fold_count": 1,
        "row_count": 1,
        "role_semantics": {
            "held_out_role": "",
            "independent_validation_groups": None,
            "independent_test_groups": None,
            "three_way_structure_present": False,
            "held_out_target_usage": "NOT_APPLICABLE",
            "note": "",
        },
        "source_checksums": {
            "dataset_parquet": digest(dataset_path),
            "dataset_manifest": digest(dataset_manifest_path),
        },
        "output_checksums": {
            output_name: digest(split_dir / filename)
            for output_name, filename in outputs.items()
        },
    }
    manifest_path = split_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    split_ref = ArtifactRef(
        artifact_type="SPLIT",
        artifact_id="SPLIT::cache",
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        path=str(split_dir),
        manifest_path=str(manifest_path),
    )
    dataset_ref = ArtifactRef(
        artifact_type="DATASET",
        artifact_id="DS::cache",
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        path=str(dataset_dir),
        manifest_path=str(dataset_manifest_path),
    )
    monkeypatch.setattr(
        orchestrator_nodes,
        "find_existing_artifact",
        lambda *_args, **_kwargs: split_ref,
    )
    plan = AnalysisPlan(
        profile="BUILD_DATASET",
        project=PlanProject(battery_id="CELL_TEST", experiment_id="EXP_TEST"),
        stages=["SPLIT"],
        split={
            "strategy": "TRAIN_ONLY",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
    )

    ref, reason = SplitNode().resolve_existing_output(
        plan, {"DATASET": dataset_ref}, processed_root
    )

    assert ref is None
    assert "SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:fold1" in reason


def test_split_consumer_blocks_split_bound_to_another_dataset(tmp_path: Path) -> None:
    split_ref, ctx, _ = _current_split(tmp_path)

    with pytest.raises(ValueError, match="Split identity does not match"):
        _require_current_split_assignments_path(
            split_ref,
            ctx,
            battery_id="CELL_TEST",
            experiment_id="EXP_TEST",
            dataset_id="DS::other",
            dataset_path=ctx.dataset_path,
            dataset_manifest_path=ctx.dataset_manifest_path,
        )


def test_split_consumer_blocks_legacy_manifest_without_output_checksums(tmp_path: Path) -> None:
    split_ref, ctx, _ = _current_split(tmp_path)
    manifest_path = Path(split_ref.manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("output_checksums")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="Split outputs are stale or unverifiable"):
        _assignments_path(split_ref, ctx)


@pytest.mark.parametrize("changed_source", ["dataset_parquet", "dataset_manifest"])
def test_split_consumer_blocks_same_dataset_id_with_changed_dataset_bytes(
    tmp_path: Path, changed_source: str
) -> None:
    split_ref, ctx, _ = _current_split(tmp_path)
    source_path = (
        ctx.dataset_path
        if changed_source == "dataset_parquet"
        else ctx.dataset_manifest_path
    )
    source_path.write_bytes(source_path.read_bytes() + b"changed under same ID")

    with pytest.raises(ValueError, match="Split is stale or unverifiable for the current Dataset"):
        _assignments_path(split_ref, ctx)


@pytest.mark.parametrize(
    "node",
    [FeatureAnalysisNode(), SocModelingNode()],
    ids=["ml-safe-feature-analysis", "soc-modeling"],
)
def test_scientific_consumers_block_tampered_split_before_assignments_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, node
) -> None:
    split_ref, ctx, split_dir = _current_split(tmp_path)
    (split_dir / "split_assignments.parquet").write_bytes(b"tampered")
    dataset_ref = ArtifactRef(
        artifact_type="DATASET",
        artifact_id="DS::test",
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        path=str(ctx.dataset_path.parent),
        manifest_path=str(ctx.dataset_manifest_path),
    )
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_TEST", experiment_id="EXP_TEST"),
        stages=["FEATURE_ANALYSIS" if isinstance(node, FeatureAnalysisNode) else "SOC_MODELING"],
        target="soc_reference_percent",
        feature_analysis={"analysis_mode": "TRAIN_ONLY_ML_SAFE"},
    )
    monkeypatch.setattr(
        orchestrator_nodes,
        "_require_current_dataset_path",
        lambda *_args, **_kwargs: ctx.dataset_path,
    )

    with pytest.raises(ValueError, match="Split outputs are stale or unverifiable"):
        node.run(plan, {"DATASET": dataset_ref, "SPLIT": split_ref}, ctx)

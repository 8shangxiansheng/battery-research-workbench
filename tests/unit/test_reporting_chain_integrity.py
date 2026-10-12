from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.modeling.persistence import fold_coverage, write_model_comparison
from battery_workbench.reporting.collector import _verify_chain_outputs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _chain(
    root: Path,
    *,
    expected_folds: tuple[int, ...] = (1,),
    evaluated_folds: tuple[int, ...] = (1,),
) -> tuple[Path, Path]:
    battery, experiment, dataset, split, model = "CELL_X", "EXP_X", "DS_X", "SPLIT_X", "MODEL_X"
    split_dir = root / "splits" / battery / experiment / dataset / split
    split_dir.mkdir(parents=True)
    dataset_dir = root / "datasets" / battery / experiment / "SOC" / dataset
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    event_ids = [f"ME::{index}" for index in range(1, max(expected_folds) + 1)]
    cycle_ids = [f"CYCLE::{index}" for index in range(1, max(expected_folds) + 1)]
    pd.DataFrame(
        {"measurement_event_id": event_ids, "cycle_group_id": cycle_ids}
    ).to_parquet(dataset_path, index=False)
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_manifest_path.write_text('{"dataset_id":"DS_X"}', encoding="utf-8")
    outputs = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    strategy = "LEAVE_ONE_GROUP_OUT" if len(cycle_ids) > 1 else "TRAIN_ONLY"
    assignment_rows = []
    for fold in expected_folds:
        held_out_cycle = cycle_ids[fold - 1] if strategy == "LEAVE_ONE_GROUP_OUT" else None
        for event_id, cycle_id in zip(event_ids, cycle_ids, strict=True):
            assignment_rows.append(
                {
                    "measurement_event_id": event_id,
                    "cycle_group_id": cycle_id,
                    "fold": f"fold{fold}",
                    "role": "HELD_OUT" if cycle_id == held_out_cycle else "TRAIN",
                    "strategy": strategy,
                    "dataset_id": dataset,
                    "split_id": split,
                }
            )
    pd.DataFrame(assignment_rows).to_parquet(
        split_dir / outputs["split_assignments"], index=False
    )
    for key, filename in outputs.items():
        if key != "split_assignments":
            (split_dir / filename).write_bytes(b"split output")
    coverage = fold_coverage(list(expected_folds), list(evaluated_folds))
    _write_json(
        split_dir / "split_manifest.json",
        {
            "battery_id": battery,
            "experiment_id": experiment,
            "dataset_id": dataset,
            "split_id": split,
            "group_column": "cycle_group_id",
            "split_unit": "CYCLE",
            "strategy": strategy,
            "group_counts": dict.fromkeys(cycle_ids, 1),
            "group_count": len(cycle_ids),
            "role_semantics": (
                {
                    "held_out_role": "HELD_OUT",
                    "independent_validation_groups": 0,
                    "independent_test_groups": 0,
                    "three_way_structure_present": False,
                    "held_out_target_usage": "FORBIDDEN_FOR_MODEL_SELECTION",
                    "note": "independent cycles only; no simultaneous independent validation + test groups exist",
                }
                if strategy == "LEAVE_ONE_GROUP_OUT"
                else {
                    "held_out_role": "",
                    "independent_validation_groups": None,
                    "independent_test_groups": None,
                    "three_way_structure_present": False,
                    "held_out_target_usage": "NOT_APPLICABLE",
                    "note": "",
                }
            ),
            "row_count": len(assignment_rows),
            "fold_count": len(expected_folds),
            "source_checksums": {
                "dataset_parquet": _sha256(dataset_path),
                "dataset_manifest": _sha256(dataset_manifest_path),
            },
            "output_checksums": {
                key: _sha256(split_dir / filename) for key, filename in outputs.items()
            },
        },
    )

    model_dir = root / "models" / battery / experiment / dataset / split / model
    model_dir.mkdir(parents=True)
    (model_dir / "model.joblib").write_bytes(b"estimator")
    (model_dir / "held_out_predictions.parquet").write_bytes(b"predictions")
    _write_json(
        model_dir / "model_manifest.json",
        {
            "model_id": model,
            "dataset_id": dataset,
            "split_id": split,
            "fold_index": 1,
            "strategy": "DUMMY_MEAN",
            "scientific_claims": {
                "readiness": coverage["readiness"],
                "fold_coverage": coverage,
            },
            "output_checksums": {
                "model": _sha256(model_dir / "model.joblib"),
                "held_out_predictions": _sha256(model_dir / "held_out_predictions.parquet"),
            },
        },
    )
    comparison = write_model_comparison(
        comparison_rows=[
            {"model_id": model, "strategy": "DUMMY_MEAN", "fold_index": fold}
            for fold in evaluated_folds
        ],
        battery_id=battery,
        experiment_id=experiment,
        dataset_id=dataset,
        split_id=split,
        output_root=root,
    )
    comparison_manifest = json.loads(
        Path(comparison["model_comparison_manifest"]).read_text(encoding="utf-8")
    )
    _write_json(
        Path(comparison["model_comparison_json"]).parent / "model_set_manifest.json",
        {
            "model_set_id": "MODELSET_X",
            "battery_id": battery,
            "experiment_id": experiment,
            "dataset_id": dataset,
            "split_id": split,
            "strategies": ["DUMMY_MEAN"],
            "readiness": coverage["readiness"],
            "fold_coverage": coverage,
            "model_artifacts": [
                {"model_id": model, "manifest_sha256": _sha256(model_dir / "model_manifest.json")}
            ],
            "output_checksums": comparison_manifest["output_checksums"],
        },
    )
    return split_dir / "split_assignments.parquet", Path(comparison["model_comparison_parquet"])


def test_model_comparison_writer_seals_outputs_and_integrity_verifies_chain(tmp_path: Path) -> None:
    _chain(tmp_path)

    reasons, model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert reasons == []
    assert model_ids == {"MODEL_X"}


def test_reporting_accepts_honestly_declared_partial_fold_coverage(tmp_path: Path) -> None:
    _chain(tmp_path, expected_folds=(1, 2), evaluated_folds=(1,))

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert reasons == []


def test_model_comparison_writer_seals_final_summary_json(tmp_path: Path) -> None:
    paths = write_model_comparison(
        comparison_rows=[{"model_id": "MODEL_X", "strategy": "RIDGE"}],
        summary_rows=[{"strategy": "RIDGE", "macro_MAE": 12.5}],
        battery_id="CELL_X",
        experiment_id="EXP_X",
        dataset_id="DS_X",
        split_id="SPLIT_X",
        output_root=tmp_path,
    )

    summary = json.loads(Path(paths["model_comparison_json"]).read_text(encoding="utf-8"))
    manifest = json.loads(
        Path(paths["model_comparison_manifest"]).read_text(encoding="utf-8")
    )
    assert summary == [{"strategy": "RIDGE", "macro_MAE": 12.5}]
    assert manifest["output_checksums"]["model_comparison_json"] == _sha256(
        Path(paths["model_comparison_json"])
    )


def test_reporting_chain_integrity_blocks_tampered_split_and_comparison(tmp_path: Path) -> None:
    split_assignment, comparison = _chain(tmp_path)
    split_assignment.write_bytes(b"tampered split")
    comparison.write_bytes(b"tampered comparison")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "SPLIT_OUTPUT_CHECKSUM_MISMATCH:split_assignments" in reasons
    assert "MODEL_COMPARISON_CHECKSUM_MISMATCH:model_comparison_parquet" in reasons


def test_reporting_blocks_split_from_previous_dataset_content_version(
    tmp_path: Path,
) -> None:
    _chain(tmp_path)
    dataset_dir = tmp_path / "datasets/CELL_X/EXP_X/SOC/DS_X"
    dataset_path = dataset_dir / "dataset.parquet"
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_path.write_bytes(b"new dataset bytes under same id")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path,
        "CELL_X",
        "EXP_X",
        "DS_X",
        "SPLIT_X",
        dataset_path=dataset_path,
        dataset_manifest_path=dataset_manifest_path,
    )

    assert "SPLIT_SOURCE_DATASET_CHANGED:dataset_parquet" in reasons


def test_reporting_blocks_assignment_event_mismatch_after_checksum_reseal(
    tmp_path: Path,
) -> None:
    assignment_path, _comparison = _chain(tmp_path)
    split_manifest_path = assignment_path.parent / "split_manifest.json"
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    assignments = pd.read_parquet(assignment_path)
    assignments.loc[0, "measurement_event_id"] = "ME::unknown"
    assignments.to_parquet(assignment_path, index=False)
    split_manifest["output_checksums"]["split_assignments"] = _sha256(assignment_path)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")
    dataset_path = tmp_path / "datasets/CELL_X/EXP_X/SOC/DS_X/dataset.parquet"
    dataset_manifest_path = dataset_path.parent / "dataset_manifest.json"

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path,
        "CELL_X",
        "EXP_X",
        "DS_X",
        "SPLIT_X",
        dataset_path=dataset_path,
        dataset_manifest_path=dataset_manifest_path,
    )

    assert "SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:fold1" in reasons


def test_model_predictions_tampering_blocks_chain_even_if_comparison_is_intact(
    tmp_path: Path,
) -> None:
    _chain(tmp_path)
    predictions = (
        tmp_path / "models" / "CELL_X" / "EXP_X" / "DS_X" / "SPLIT_X"
        / "MODEL_X" / "held_out_predictions.parquet"
    )
    predictions.write_bytes(b"tampered predictions")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "MODEL_OUTPUT_CHECKSUM_MISMATCH:MODEL_X:held_out_predictions" in reasons


def test_model_set_manifest_must_bind_exact_model_members(tmp_path: Path) -> None:
    _chain(tmp_path)
    model_set_path = (
        tmp_path / "models" / "CELL_X" / "EXP_X" / "DS_X" / "SPLIT_X"
        / "model_set_manifest.json"
    )
    model_set = json.loads(model_set_path.read_text(encoding="utf-8"))
    model_set["model_artifacts"][0]["manifest_sha256"] = "0" * 64
    model_set_path.write_text(json.dumps(model_set), encoding="utf-8")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "MODEL_SET_MEMBER_MANIFEST_MISMATCH" in reasons


def test_reporting_recomputes_fold_coverage_from_split_and_model_artifacts(
    tmp_path: Path,
) -> None:
    split_assignments, _comparison = _chain(tmp_path)
    split_dir = split_assignments.parent
    pd.DataFrame(
        [
            {"measurement_event_id": "ME::1", "fold": "fold1", "role": "HELD_OUT"},
            {"measurement_event_id": "ME::2", "fold": "fold2", "role": "HELD_OUT"},
        ]
    ).to_parquet(split_assignments, index=False)
    split_manifest_path = split_dir / "split_manifest.json"
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    split_manifest["output_checksums"]["split_assignments"] = _sha256(split_assignments)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "MODEL_SET_FOLD_COVERAGE_MISMATCH" in reasons
    assert "MODEL_MANIFEST_FOLD_COVERAGE_MISMATCH" in reasons


def test_reporting_blocks_tampered_model_set_fold_coverage(tmp_path: Path) -> None:
    _chain(tmp_path)
    model_set_path = (
        tmp_path / "models" / "CELL_X" / "EXP_X" / "DS_X" / "SPLIT_X"
        / "model_set_manifest.json"
    )
    model_set = json.loads(model_set_path.read_text(encoding="utf-8"))
    model_set["fold_coverage"] = fold_coverage([1, 2], [1, 2])
    model_set["readiness"] = "READY_FOR_LIMITED_EVALUATION"
    model_set_path.write_text(json.dumps(model_set), encoding="utf-8")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "MODEL_SET_FOLD_COVERAGE_MISMATCH" in reasons


def test_reporting_requires_each_declared_strategy_for_each_evaluated_fold(
    tmp_path: Path,
) -> None:
    _chain(tmp_path)
    model_set_path = (
        tmp_path / "models" / "CELL_X" / "EXP_X" / "DS_X" / "SPLIT_X"
        / "model_set_manifest.json"
    )
    model_set = json.loads(model_set_path.read_text(encoding="utf-8"))
    model_set["strategies"] = ["DUMMY_MEAN", "RIDGE"]
    model_set_path.write_text(json.dumps(model_set), encoding="utf-8")

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "MODEL_SET_STRATEGY_FOLD_COVERAGE_MISMATCH" in reasons


def test_reporting_chain_integrity_rejects_split_directory_escape(tmp_path: Path) -> None:
    _chain(tmp_path)
    split_parent = tmp_path / "splits" / "CELL_X" / "EXP_X" / "DS_X"
    split_dir = split_parent / "SPLIT_X"
    split_dir.rename(tmp_path / "split-backup")
    split_dir.symlink_to(tmp_path.parent, target_is_directory=True)

    reasons, _model_ids = _verify_chain_outputs(
        tmp_path, "CELL_X", "EXP_X", "DS_X", "SPLIT_X"
    )

    assert "SPLIT_PATH_INVALID" in reasons

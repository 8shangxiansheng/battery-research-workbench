from __future__ import annotations

import hashlib
import json
from pathlib import Path

from battery_workbench.api.routes.features_v2 import _analysis_freshness_status
from battery_workbench.feature_analysis.output import write_analysis_payload
from battery_workbench.feature_analysis.schemas import AnalysisMode, FeatureAnalysisSpec


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_materialized_train_analysis_is_current_until_source_changes(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    dataset_dir = processed / "datasets/CELL_001/EXP_001/SOC/DS::d1"
    dataset_path = dataset_dir / "dataset.parquet"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_bytes(b"dataset-v1")
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    _write(
        dataset_manifest_path,
        json.dumps({
            "dataset_id": "DS::d1",
            "dataset_status": "READY",
            "output_checksum": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        }),
    )
    split_dir = processed / "splits/CELL_001/EXP_001/DS::d1/SPLIT::s1"
    assignments_path = split_dir / "split_assignments.parquet"
    assignments_path.parent.mkdir(parents=True)
    assignments_path.write_bytes(b"assignments-v1")
    split_manifest_path = split_dir / "split_manifest.json"
    _write(
        split_manifest_path,
        json.dumps({
            "dataset_id": "DS::d1",
            "split_id": "SPLIT::s1",
            "output_checksums": {
                "split_assignments": hashlib.sha256(assignments_path.read_bytes()).hexdigest(),
            },
        }),
    )
    spec = FeatureAnalysisSpec(
        analysis_mode=AnalysisMode.TRAIN_ONLY_ML_SAFE,
        target="soc_reference_percent",
        candidate_features=["feature_x"],
        split_id="SPLIT::s1",
        fold_index=1,
    )
    selection = {
        "selection_id": "SEL::s1",
        "analysis_mode": "TRAIN_ONLY_ML_SAFE",
        "selection_requested": True,
        "selected_features": ["feature_x"],
        "rejected_features": {},
        "selection_basis": "TRAIN_ONLY_ML_SAFE",
        "selection_mode": "USER_EXPLICIT",
        "ml_safe_selection": True,
        "split_id": "SPLIT::s1",
        "fold_index": 1,
        "policy": {},
        "policy_version": "0.1.0",
        "auto_removed_features": [],
        "commit_status": "WAITING_FOR_USER",
    }
    paths = write_analysis_payload(
        spec=spec,
        analysis={
            "descriptive": [{"feature_locator": "feature_x", "mean": 1.0}],
            "correlations": [],
            "pairwise": None,
            "subgroups": {},
            "gate_comparison": {},
            "redundancy": [],
        },
        selection=selection,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_id="DS::d1",
        output_root=processed,
    )
    analysis_dir = Path(paths["analysis_dir"])
    manifest_path = Path(paths["analysis_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["input_checksums"]) == {
        "dataset_manifest", "dataset_parquet", "split_manifest", "split_assignments"
    }
    assert _analysis_freshness_status(
        manifest, analysis_dir, processed, "CELL_001", "EXP_001"
    ) == "CURRENT"

    dataset_path.write_bytes(b"dataset-v2")
    _write(
        dataset_manifest_path,
        json.dumps({
            "dataset_id": "DS::d1",
            "dataset_status": "READY",
            "output_checksum": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        }),
    )

    assert _analysis_freshness_status(
        manifest, analysis_dir, processed, "CELL_001", "EXP_001"
    ) == "STALE_SOURCE"


def test_analysis_with_corrupt_output_checksum_is_integrity_blocked(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    analysis_dir = processed / "feature_analysis/CELL_001/EXP_001/DS::d1/AN::a1"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "feature_summary.parquet").write_bytes(b"changed")

    status = _analysis_freshness_status(
        {"output_checksums": {"feature_summary": "0" * 64}},
        analysis_dir,
        processed,
        "CELL_001",
        "EXP_001",
    )

    assert status == "INTEGRITY_BLOCKED"


def test_analysis_with_missing_source_dataset_is_stale(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    analysis_dir = processed / "feature_analysis/CELL_001/EXP_001/DS::missing/AN::a1"
    analysis_dir.mkdir(parents=True)
    payload = b"parquet placeholder"
    (analysis_dir / "feature_summary.parquet").write_bytes(payload)

    status = _analysis_freshness_status(
        {
            "dataset_id": "DS::missing",
            "output_checksums": {"feature_summary": hashlib.sha256(payload).hexdigest()},
        },
        analysis_dir,
        processed,
        "CELL_001",
        "EXP_001",
    )

    assert status == "STALE_SOURCE"


def test_analysis_without_output_checksums_is_legacy(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    analysis_dir = processed / "feature_analysis/CELL_001/EXP_001/EXPLORATORY/AN::legacy"
    analysis_dir.mkdir(parents=True)
    status = _analysis_freshness_status(
        {}, analysis_dir, processed, "CELL_001", "EXP_001"
    )

    assert status == "LEGACY"

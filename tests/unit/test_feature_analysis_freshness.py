from __future__ import annotations

import hashlib
import json
from pathlib import Path

from battery_workbench.api.routes.features_v2 import _analysis_freshness_status


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_analysis_with_unverifiable_source_fingerprint_is_legacy(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    analysis_dir = processed / "feature_analysis/CELL_001/EXP_001/DS::d1/AN::a1"
    payload = b"parquet placeholder"
    (analysis_dir / "feature_summary.parquet").parent.mkdir(parents=True)
    (analysis_dir / "feature_summary.parquet").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    dataset_path = processed / "datasets/CELL_001/EXP_001/SOC/DS::d1/dataset_manifest.json"
    _write(dataset_path, json.dumps({"dataset_id": "DS::d1", "dataset_status": "READY"}))
    split_path = processed / "splits/CELL_001/EXP_001/DS::d1/SPLIT::s1/split_manifest.json"
    _write(split_path, json.dumps({"dataset_id": "DS::d1", "split_id": "SPLIT::s1"}))

    status = _analysis_freshness_status(
        {
            "dataset_id": "DS::d1",
            "split_id": "SPLIT::s1",
            "output_checksums": {"feature_summary": digest},
        },
        analysis_dir,
        processed,
        "CELL_001",
        "EXP_001",
    )

    assert status == "LEGACY"


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

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from battery_workbench.api.research_overview import _leading_exploratory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _analysis(
    root: Path,
    *,
    analysis_id: str,
    manifest_mtime_ns: int,
    coefficient: float,
    tamper_correlation_after_manifest: bool = False,
) -> None:
    analysis_dir = root / "feature_analysis" / "B1" / "E1" / "DS::1" / analysis_id
    analysis_dir.mkdir(parents=True, exist_ok=True)
    source = root / "features" / "B1" / "E1" / "FS::1" / "ultrasound_features.parquet"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        pd.DataFrame({"feature": [1.0]}).to_parquet(source, index=False)
    correlation_path = analysis_dir / "feature_target_correlation.parquet"
    pd.DataFrame(
        [{"feature_name": "SWA", "method": "spearman", "coefficient": coefficient, "n": 10}]
    ).to_parquet(correlation_path, index=False)
    selection = {
        "selection_id": f"SEL::{analysis_id}",
        "analysis_id": analysis_id,
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "selection_requested": False,
        "selected_features": [],
        "rejected_features": [],
        "selection_basis": "EXPLORATORY_FULL_DATA",
        "selection_mode": "DESCRIPTIVE_ONLY",
        "ml_safe_selection": False,
        "split_id": None,
        "fold_index": None,
        "policy": "NONE",
        "policy_version": "1",
        "auto_removed_features": [],
        "commit_status": "NOT_REQUESTED",
    }
    (analysis_dir / "feature_selection.json").write_text(
        json.dumps(selection), encoding="utf-8"
    )
    (analysis_dir / "analysis_schema.json").write_text("[]\n", encoding="utf-8")
    outputs = {
        "feature_target_correlation.parquet": _sha256(correlation_path),
        "feature_selection.json": _sha256(analysis_dir / "feature_selection.json"),
        "analysis_schema.json": _sha256(analysis_dir / "analysis_schema.json"),
    }
    manifest = {
        "analysis_id": analysis_id,
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "battery_id": "B1",
        "experiment_id": "E1",
        "dataset_id": "DS::1",
        "selection": selection,
        "input_paths": {"feature_table": source.relative_to(root).as_posix()},
        "input_checksums": {"feature_table": _sha256(source)},
        "output_checksums": outputs,
    }
    manifest_path = analysis_dir / "analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    os.utime(manifest_path, ns=(manifest_mtime_ns, manifest_mtime_ns))
    if tamper_correlation_after_manifest:
        pd.DataFrame(
            [{"feature_name": "SWA", "method": "spearman", "coefficient": -0.99, "n": 10}]
        ).to_parquet(correlation_path, index=False)


def _model_and_dataset(root: Path) -> None:
    dataset_dir = root / "datasets" / "B1" / "E1" / "SOC" / "DS::1"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "dataset_manifest.json").write_text("{}", encoding="utf-8")
    comparison = root / "models" / "B1" / "E1" / "DS::1" / "SPLIT::1" / "model_comparison.json"
    comparison.parent.mkdir(parents=True)
    comparison.write_text("{}", encoding="utf-8")


def test_leading_exploratory_uses_latest_current_analysis_and_skips_tampered_output(
    tmp_path: Path, monkeypatch
) -> None:
    from battery_workbench.reporting import collector

    root = tmp_path / "processed"
    root.mkdir()
    _model_and_dataset(root)
    _analysis(root, analysis_id="AN::z", manifest_mtime_ns=100, coefficient=0.2)
    _analysis(root, analysis_id="AN::a", manifest_mtime_ns=200, coefficient=0.7)
    _analysis(
        root,
        analysis_id="AN::latest-but-tampered",
        manifest_mtime_ns=300,
        coefficient=0.99,
        tamper_correlation_after_manifest=True,
    )
    monkeypatch.setattr(collector, "latest_evaluated_chain", lambda *_: ("DS::1", "SPLIT::1"))

    result = _leading_exploratory(root, "B1", "E1")

    assert result is not None
    assert result["analysis_id"] == "AN::a"
    assert result["coefficient"] == 0.7


def test_leading_exploratory_hides_legacy_analysis_without_current_input_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    from battery_workbench.reporting import collector

    root = tmp_path / "processed"
    root.mkdir()
    _model_and_dataset(root)
    _analysis(root, analysis_id="AN::legacy", manifest_mtime_ns=100, coefficient=0.2)
    manifest_path = (
        root / "feature_analysis" / "B1" / "E1" / "DS::1" / "AN::legacy" / "analysis_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("input_paths")
    manifest.pop("input_checksums")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(collector, "latest_evaluated_chain", lambda *_: ("DS::1", "SPLIT::1"))

    assert _leading_exploratory(root, "B1", "E1") is None

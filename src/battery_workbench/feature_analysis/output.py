"""BRW-021 canonical outputs (§25)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.feature_analysis.engine import REDUNDANCY_POLICY_VERSION
from battery_workbench.feature_analysis.schemas import FeatureAnalysisSpec


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


def write_analysis_payload(
    *,
    spec: FeatureAnalysisSpec,
    analysis: dict[str, Any],
    selection: dict[str, Any],
    battery_id: str,
    experiment_id: str,
    dataset_id: str,
    output_root: Path,
) -> dict[str, str]:
    output_root = Path(output_root)
    scope_dir = dataset_id if dataset_id else "EXPLORATORY"
    analysis_dir = (
        output_root / "feature_analysis" / battery_id / experiment_id / scope_dir / spec.analysis_id
    )
    analysis_dir.mkdir(parents=True, exist_ok=True)

    def _df_to_file(rows: Any, name: str) -> str:
        df = pd.DataFrame(rows if isinstance(rows, list) else [])
        p = analysis_dir / name
        df.to_parquet(p, index=False)
        return str(p)

    written: dict[str, str] = {}
    if analysis.get("descriptive"):
        written["feature_summary"] = _df_to_file(analysis["descriptive"], "feature_summary.parquet")
    if analysis.get("correlations"):
        written["feature_target_correlation"] = _df_to_file(
            analysis["correlations"], "feature_target_correlation.parquet"
        )
    if isinstance(analysis.get("pairwise"), pd.DataFrame) and not analysis["pairwise"].empty:
        pairwise = analysis["pairwise"].copy()
        pairwise["analysis_id"] = spec.analysis_id
        written["feature_feature_correlation"] = _df_to_file(
            pairwise, "feature_feature_correlation.parquet"
        )
    sub_rows = [{**row} for group in (analysis.get("subgroups") or {}).values() for row in group]
    if sub_rows:
        written["subgroup_analysis"] = _df_to_file(sub_rows, "subgroup_analysis.parquet")
    gate_rows = [
        {**row, "feature_name": name}
        for name, group in (analysis.get("gate_comparison") or {}).items()
        for row in group
    ]
    if gate_rows:
        written["gate_comparison"] = _df_to_file(gate_rows, "gate_comparison.parquet")

    selection_payload = {
        "selection_id": selection["selection_id"],
        "analysis_id": spec.analysis_id,
        "analysis_mode": selection["analysis_mode"],
        "selection_requested": selection["selection_requested"],
        "selected_features": selection["selected_features"],
        "rejected_features": selection["rejected_features"],
        "selection_basis": selection["selection_basis"],
        "selection_mode": selection["selection_mode"],
        "ml_safe_selection": selection["ml_safe_selection"],
        "split_id": selection["split_id"],
        "fold_index": selection["fold_index"],
        "policy": selection["policy"],
        "policy_version": selection["policy_version"],
        "auto_removed_features": selection["auto_removed_features"],
        "commit_status": selection["commit_status"],
    }
    selection_path = analysis_dir / "feature_selection.json"
    _write_json(selection_path, selection_payload)

    manifest = {
        "analysis_id": spec.analysis_id,
        "analysis_version": spec.analysis_version,
        "analysis_mode": spec.analysis_mode.value,
        "target": spec.target,
        "candidate_features": spec.candidate_features,
        "resolved_availability": analysis.get("availability", []),
        "split_id": spec.split_id,
        "fold_index": spec.fold_index,
        "dataset_id": dataset_id,
        "methods": spec.methods,
        "subgroup_by": spec.subgroup_by,
        "redundancy_policy_version": REDUNDANCY_POLICY_VERSION,
        "selection": selection_payload,
        "held_out_target_accessed": False,
        "limitations": [],
        "provenance": {"engine": "brw021_feature_analysis", "output_root": str(analysis_dir)},
        "output_checksums": {Path(k).name: _sha256_file(Path(v)) for k, v in written.items()},
    }
    manifest_path = analysis_dir / "analysis_manifest.json"
    _write_json(manifest_path, manifest)

    schema_entries = [{"file": Path(v).name, "kind": "parquet"} for v in written.values()]
    schema_path = analysis_dir / "analysis_schema.json"
    _write_json(schema_path, schema_entries)

    # reports
    report_dir = (
        output_root.parent
        / "artifacts"
        / battery_id
        / experiment_id
        / "feature_analysis"
        / spec.analysis_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "analysis_id": spec.analysis_id,
        "analysis_mode": spec.analysis_mode.value,
        "target": spec.target,
        "split_id": spec.split_id,
        "fold_index": spec.fold_index,
        "selection": selection_payload,
        "held_out_target_accessed": False,
        "redundancy": analysis.get("redundancy", []),
    }
    report_json = report_dir / "feature_analysis_report.json"
    _write_json(report_json, report)
    report_html = report_dir / "feature_analysis_report.html"
    report_html.write_text(
        "<html><body><h1>Feature Analysis Report</h1><pre>"
        + json.dumps(report, indent=2, ensure_ascii=False, default=str)
        + "</pre></body></html>\n"
    )
    figures_dir = report_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    return {
        "analysis_id": spec.analysis_id,
        "analysis_dir": str(analysis_dir),
        "analysis_manifest": str(manifest_path),
        "analysis_schema": str(schema_path),
        "feature_selection": str(selection_path),
        "report_json": str(report_json),
        "report_html": str(report_html),
        **written,
    }

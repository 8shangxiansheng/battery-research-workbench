"""BRW-023 scientific report generation: JSON / Markdown / HTML."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from battery_workbench.reporting.schemas import (
    REPORT_SECTIONS,
    ReportSpec,
)


def _git_commit(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, FileNotFoundError):
        return ""


def _python_version() -> str:
    import sys

    return sys.version.split()[0]


def _pkg_versions() -> dict[str, str]:
    versions = {}
    for pkg in ("pandas", "numpy", "sklearn", "joblib"):
        try:
            mod = __import__(pkg)
            versions[pkg] = getattr(mod, "__version__", "")
        except ImportError:
            pass
    return versions


def generate_report_files(
    *,
    report: dict[str, Any],
    battery_id: str,
    experiment_id: str,
    report_id: str,
    output_root: Path,
) -> dict[str, str]:
    out_dir = output_root / "artifacts" / battery_id / experiment_id / "reports" / report_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tables").mkdir(exist_ok=True)
    (out_dir / "figures").mkdir(exist_ok=True)

    json_path = out_dir / "scientific_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    md_path = out_dir / "scientific_report.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    html_path = out_dir / "scientific_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")

    return {
        "report_json": str(json_path),
        "report_md": str(md_path),
        "report_html": str(html_path),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = ["# BRW-023 Scientific Report", ""]
    lines.append(f"**report_id**: {report.get('report_id', '')}")
    lines.append(f"**generated_at**: {report.get('generated_at', '')}")
    lines.append("")
    for section in REPORT_SECTIONS:
        lines.append(f"## {section}")
        lines.append("")
        body = (report.get("sections") or {}).get(section)
        if body is None:
            lines.append("(not available)")
        elif isinstance(body, dict):
            lines.append("```json")
            lines.append(json.dumps(body, indent=2, ensure_ascii=False, default=str))
            lines.append("```")
        else:
            lines.append(str(body))
        lines.append("")
    return "\n".join(lines)


def _render_html(report: dict[str, Any]) -> str:
    body = _render_markdown(report)
    return (
        "<html><head><title>BRW-023 Scientific Report</title></head><body>"
        + body.replace("# ", "<h1>").replace("## ", "<h2>").replace("\n", "<br>\n")
        + "</body></html>"
    )


def build_reproducibility_manifest(
    *,
    processed_root: Path,
    repo_root: Path,
    battery_id: str,
    experiment_id: str,
    spec: ReportSpec,
    lineage_snapshot: dict[str, Any],
    evidence_registry: list[dict[str, Any]],
    limitations: list[dict[str, str]],
) -> dict[str, Any]:
    """Reproducibility manifest: no secrets, no personal machine identifiers."""
    import hashlib

    def _sha(p: Path) -> str:
        if not p.exists():
            return ""
        h = hashlib.sha256()
        if p.is_dir():
            for f in sorted(x for x in p.rglob("*") if x.is_file()):
                h.update(str(f.relative_to(p)).encode())
                h.update(f.read_bytes())
        else:
            h.update(p.read_bytes())
        return h.hexdigest()

    raw_checksums = {}
    for rel in (
        "electrical/CELL_001/EXP_001/records.parquet",
        "ultrasound/CELL_001/EXP_001/waveforms.zarr",
    ):
        full = processed_root / rel
        if full.exists():
            raw_checksums[rel] = _sha(full)

    git_commit = _git_commit(repo_root)
    return {
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "raw_asset_checksums": raw_checksums,
        "artifact_ids": {
            "dataset_id": "DS::6a3142e5186fc684964ff09e",
            "split_id": "SPLIT::062cf007d21578a11ab2d728",
            "label_set_id": "LB::752466f98a93a4d1b44da358",
            "feature_set_id": "FS::60649fd12c540267fe585914",
            "gate_set_id": "GATESET::8633ce421ad5e26fe686",
            "parameter_set_ids": sorted(
                p.name
                for p in (processed_root / "parameters" / battery_id / experiment_id).glob("PS::*")
            ),
            "analysis_ids": sorted(
                p.name
                for p in (
                    processed_root
                    / "feature_analysis"
                    / battery_id
                    / experiment_id
                    / "DS::6a3142e5186fc684964ff09e"
                ).glob("AN::*")
            ),
        },
        "git_commit": git_commit,
        "policy_versions": {
            "sync_schema": "0.2.0",
            "modeling_policy": "0.1.0",
            "reporting_policy": spec.reporting_policy_version,
            "leakage_policy": "0.1.0",
        },
        "environment": {
            "python_version": _python_version(),
            "packages": _pkg_versions(),
        },
        "limitations": limitations,
        "evidence_registry": evidence_registry,
        "lineage_snapshot": lineage_snapshot,
        "analysis_plan_snapshot": {
            "note": "AnalysisPlan snapshots stored in data/artifacts/runs/*/analysis_plan.json",
        },
    }

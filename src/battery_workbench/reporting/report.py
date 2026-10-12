"""BRW-023 scientific report generation: JSON / Markdown / HTML."""

from __future__ import annotations

import hashlib
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
    manifest_path = out_dir / "scientific_report_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "scientific-report-integrity/1.0",
                "report_id": report_id,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "output_checksums": {
                    path.name: _sha256_file(path)
                    for path in (json_path, md_path, html_path)
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "report_json": str(json_path),
        "report_md": str(md_path),
        "report_html": str(html_path),
        "report_manifest": str(manifest_path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_report_outputs(
    report_json_path: Path,
    *,
    battery_id: str | None = None,
    experiment_id: str | None = None,
    reports_root: Path | None = None,
) -> tuple[str, list[str]]:
    """Verify a frozen report and its rendered copies; never repairs files."""
    report_json_path = Path(report_json_path)
    report_dir = report_json_path.parent
    manifest_path = report_dir / "scientific_report_manifest.json"
    if not manifest_path.is_file():
        return "LEGACY", ["REPORT_OUTPUT_MANIFEST_MISSING"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_MANIFEST_INVALID"]
    if not isinstance(manifest, dict):
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_MANIFEST_INVALID"]
    expected_report_id = report_dir.name
    if (
        manifest.get("report_id") != expected_report_id
        or (battery_id is not None and manifest.get("battery_id") != battery_id)
        or (experiment_id is not None and manifest.get("experiment_id") != experiment_id)
    ):
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_IDENTITY_MISMATCH"]
    checksums = manifest.get("output_checksums")
    required = {"scientific_report.json", "scientific_report.md", "scientific_report.html"}
    if not isinstance(checksums, dict):
        return "LEGACY", ["REPORT_OUTPUT_CHECKSUMS_MISSING"]
    if set(checksums) != required:
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_CHECKSUM_SET_INVALID"]
    reasons: list[str] = []
    root = report_dir.resolve()
    if reports_root is not None:
        try:
            relative_dir = root.relative_to(Path(reports_root).resolve())
        except (OSError, RuntimeError, ValueError):
            return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_OUTSIDE_ROOT"]
        if len(relative_dir.parts) != 1 or relative_dir.name != expected_report_id:
            return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_PATH_IDENTITY_MISMATCH"]
    try:
        manifest_path.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_MANIFEST_OUTSIDE_ROOT"]
    for name in sorted(required):
        expected = checksums.get(name)
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected)
        ):
            reasons.append(f"REPORT_OUTPUT_CHECKSUM_INVALID:{name}")
            continue
        path = report_dir / name
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file() or _sha256_file(resolved) != expected.lower():
                reasons.append(f"REPORT_OUTPUT_CHECKSUM_MISMATCH:{name}")
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"REPORT_OUTPUT_MISSING_OR_OUTSIDE:{name}")
    if reasons:
        return "INTEGRITY_BLOCKED", reasons
    try:
        report = json.loads(report_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_JSON_INVALID"]
    if not isinstance(report, dict) or report.get("report_id") != expected_report_id:
        return "INTEGRITY_BLOCKED", ["REPORT_OUTPUT_IDENTITY_MISMATCH"]
    return "CURRENT", []


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
        f"electrical/{battery_id}/{experiment_id}/records.parquet",
        f"ultrasound/{battery_id}/{experiment_id}/waveforms.zarr",
    ):
        full = processed_root / rel
        if full.exists():
            raw_checksums[rel] = _sha(full)

    git_commit = _git_commit(repo_root)
    from battery_workbench.reporting.collector import collect_experiment_record

    record = collect_experiment_record(processed_root, battery_id, experiment_id)
    artifacts = record.latest_canonical_artifacts
    dataset_id = artifacts.get("dataset_id", "")
    return {
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "raw_asset_checksums": raw_checksums,
        "artifact_ids": {
            "dataset_id": dataset_id,
            "split_id": artifacts.get("split_id", ""),
            "label_set_id": artifacts.get("label_set_id", ""),
            "feature_set_id": artifacts.get("feature_set_id", ""),
            "gate_set_id": artifacts.get("gate_set_id", ""),
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
                    / dataset_id
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

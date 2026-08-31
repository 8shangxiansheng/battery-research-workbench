"""Persist BRW-012 analysis-slice outputs.

Writes ``analysis_slice.parquet`` and ``analysis_slice_manifest.json`` under
``data/processed/analysis_slices/{battery}/{exp}/{slice_id}``, plus JSON/HTML
report under ``data/artifacts/...``. Inputs are never mutated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.analysis.schemas import (
    AnalysisSliceConfig,
    AnalysisSliceManifest,
    AnalysisSliceReport,
    SliceStatus,
)


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_scalar) + "\n",
        encoding="utf-8",
    )


def _render_html(report: AnalysisSliceReport) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Analysis Slice Report</title></head>\n"
        "<body>\n"
        f"<h1>Analysis Slice Report</h1>\n"
        f"<p>slice_id: {report.analysis_slice_id}</p>\n"
        f"<p>battery_id: {report.battery_id} — experiment_id: {report.experiment_id}</p>\n"
        f"<p>status: {report.status}</p>\n"
        f"<p>input: {report.input_row_count} output: {report.output_row_count} "
        f"excluded: {report.excluded_row_count}</p>\n"
        f"<p>analysis_eligible_only: {report.analysis_eligible_only}</p>\n"
        "</body></html>\n"
    )


def write_slice_payload(
    *,
    sliced: pd.DataFrame,
    battery_id: str,
    experiment_id: str,
    analysis_slice_id: str,
    events_path: Path,
    input_checksum: str,
    input_row_count: int,
    output_row_count: int,
    excluded_row_count: int,
    breakdown: dict[str, int],
    requested_spec: dict[str, Any],
    normalized_spec: dict[str, Any],
    analysis_eligible_only: bool,
    status: SliceStatus,
    warnings: list[str],
    config: AnalysisSliceConfig,
    output_root: Path,
    identity_cols: list[str],
) -> AnalysisSliceReport:
    """Write the canonical slice + manifest + report; returns the report."""
    output_root = Path(output_root)
    slice_dir = output_root / "analysis_slices" / battery_id / experiment_id / analysis_slice_id
    slice_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = slice_dir / "analysis_slice.parquet"
    sliced.to_parquet(parquet_path, index=False)

    included_statuses: list[str] = []
    if not sliced.empty and "event_quality_status" in sliced.columns:
        included_statuses = sorted(str(s) for s in sliced["event_quality_status"].unique())

    manifest = AnalysisSliceManifest(
        analysis_slice_id=analysis_slice_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        input_path=str(events_path),
        input_checksum=input_checksum,
        input_row_count=input_row_count,
        requested_spec=requested_spec,
        normalized_spec=normalized_spec,
        output_path=str(parquet_path),
        output_checksum=_sha256(parquet_path),
        output_row_count=output_row_count,
        excluded_row_count=excluded_row_count,
        filter_breakdown=breakdown,
        included_quality_statuses=included_statuses,
        analysis_eligible_only=analysis_eligible_only,
        warnings=warnings or [],
        limitations=_slice_limitations(sliced, identity_cols),
    )
    manifest_path = slice_dir / "analysis_slice_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    report = AnalysisSliceReport(
        analysis_slice_id=analysis_slice_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        slice_engine_version=config.version,
        status=status,
        input_row_count=input_row_count,
        output_row_count=output_row_count,
        excluded_row_count=excluded_row_count,
        filter_breakdown=breakdown,
        requested_spec=requested_spec,
        normalized_spec=normalized_spec,
        analysis_eligible_only=analysis_eligible_only,
        warnings=warnings or [],
        limitations=_slice_limitations(sliced, identity_cols),
        artifacts={"slice": str(parquet_path), "manifest": str(manifest_path)},
        configuration=config.model_dump(),
    )
    report_dir = (
        output_root
        / "artifacts"
        / battery_id
        / experiment_id
        / "analysis_slices"
        / analysis_slice_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "analysis_slice_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "analysis_slice_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    report.artifacts["report_json"] = str(json_path)
    report.artifacts["report_html"] = str(html_path)
    return report


def _slice_limitations(sliced: pd.DataFrame, identity_cols: list[str]) -> list[str]:
    limitations: list[str] = []
    # Ensure identity columns are present (data selection guarantee).
    present = set(sliced.columns)
    missing = [c for c in identity_cols if c not in present]
    if missing:
        limitations.append(f"missing identity columns: {missing}")
    return limitations

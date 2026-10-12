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


def verify_analysis_slice_artifact(
    processed_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    battery_id: str,
    experiment_id: str,
) -> list[str]:
    """Verify slice identity, canonical event input, and persisted Parquet bytes."""
    from battery_workbench.analysis.slice_id import build_analysis_slice_id, normalize_spec
    from battery_workbench.provenance.processed_manifest import verify_manifest_files

    root = Path(processed_root).resolve()
    manifest_file = Path(manifest_path)
    try:
        manifest_file = manifest_file.resolve(strict=True)
        artifact_dir = manifest_file.parent
        artifact_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["ANALYSIS_SLICE_MANIFEST_INVALID"]
    reasons: list[str] = []
    if manifest.get("battery_id") != battery_id:
        reasons.append("ANALYSIS_SLICE_BATTERY_ID_MISMATCH")
    if manifest.get("experiment_id") != experiment_id:
        reasons.append("ANALYSIS_SLICE_EXPERIMENT_ID_MISMATCH")
    slice_id = manifest.get("analysis_slice_id")
    if not isinstance(slice_id, str) or slice_id != artifact_dir.name:
        reasons.append("ANALYSIS_SLICE_ID_MISMATCH")

    expected_input = (
        root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    ).resolve()
    expected_output = (artifact_dir / "analysis_slice.parquet").resolve()
    input_path = _resolve_processed_reference(root, manifest.get("input_path"))
    output_path = _resolve_processed_reference(root, manifest.get("output_path"))
    if input_path != expected_input:
        reasons.append("ANALYSIS_SLICE_INPUT_PATH_MISMATCH")
    if output_path != expected_output:
        reasons.append("ANALYSIS_SLICE_OUTPUT_PATH_MISMATCH")
    translated = {
        "battery_id": manifest.get("battery_id"),
        "experiment_id": manifest.get("experiment_id"),
        "input_paths": {"measurement_events": manifest.get("input_path")},
        "input_checksums": {"measurement_events": manifest.get("input_checksum")},
        "output_paths": {"analysis_slice": manifest.get("output_path")},
        "output_checksums": {"analysis_slice": manifest.get("output_checksum")},
    }
    reasons.extend(
        verify_manifest_files(
            root,
            translated,
            battery_id=battery_id,
            experiment_id=experiment_id,
            required_inputs={"measurement_events"},
            required_outputs={"analysis_slice"},
        )
    )
    requested = manifest.get("requested_spec")
    normalized = manifest.get("normalized_spec")
    if not isinstance(requested, dict) or not isinstance(normalized, dict):
        reasons.append("ANALYSIS_SLICE_SPEC_MISSING")
    else:
        normalized_from_request = normalize_spec(requested)
        if normalized_from_request != normalized:
            reasons.append("ANALYSIS_SLICE_SPEC_MISMATCH")
        input_checksum = manifest.get("input_checksum")
        if (
            isinstance(input_checksum, str)
            and len(input_checksum) == 64
            and build_analysis_slice_id(input_checksum, normalized) != slice_id
        ):
            reasons.append("ANALYSIS_SLICE_CONTENT_ID_MISMATCH")
    return list(dict.fromkeys(reasons))


def _resolve_processed_reference(root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    root = Path(root).resolve()
    candidate = Path(reference)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            normalized = reference.replace("\\", "/").split("/")
            marker = next(
                (
                    index
                    for index in range(len(normalized) - 1)
                    if normalized[index : index + 2] == ["data", "processed"]
                ),
                None,
            )
            if marker is None:
                return None
            parts = normalized[marker + 2 :]
    else:
        parts = candidate.parts
        if parts[:2] == ("data", "processed"):
            parts = parts[2:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    resolved = root.joinpath(*parts).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


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

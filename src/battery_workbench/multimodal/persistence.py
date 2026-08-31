"""Persist BRW-011 measurement-event outputs.

Writes ``measurement_events.parquet``, ``measurement_event_candidates.parquet``,
``measurement_event_manifest.json``, and JSON/HTML report under
``data/processed/multimodal/{battery}/{experiment}``. Inputs are never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.multimodal.schemas import (
    MeasurementEventConfig,
    MeasurementEventManifest,
    MeasurementEventReport,
)


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
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


def _render_html(report: MeasurementEventReport) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Measurement Event Report</title></head>\n"
        "<body>\n"
        f"<h1>Measurement Event Report</h1>\n"
        f"<p>experiment_id: {report.experiment_id} — battery_id: {report.battery_id}</p>\n"
        f"<p>events: {report.event_count} — READY: {report.quality_counts.get('READY', 0)}</p>\n"
        f"<p>analysis_eligible: {report.analysis_eligible_count} "
        f"({report.analysis_eligible_fraction:.4f})</p>\n"
        f"<p>source: {report.synced_source}</p>\n"
        "</body></html>\n"
    )


def write_measurement_event_payload(
    *,
    events: pd.DataFrame,
    candidates: pd.DataFrame,
    aligned: pd.DataFrame,
    candidates_input: pd.DataFrame | None,
    records: pd.DataFrame,
    aux_row_count: int,
    battery_id: str,
    experiment_id: str,
    config: MeasurementEventConfig,
    aligned_frames_path: Path,
    sync_candidates_path: Path,
    electrical_records_path: Path,
    aux_temperature_path: Path | None,
    output_dir: Path,
) -> MeasurementEventReport:
    """Write canonical outputs + manifest + report; returns the report."""
    output_dir = Path(output_dir)
    multimodal_dir = output_dir / "multimodal" / battery_id / experiment_id
    multimodal_dir.mkdir(parents=True, exist_ok=True)

    events_path = multimodal_dir / "measurement_events.parquet"
    events.to_parquet(events_path, index=False)
    candidates_path = multimodal_dir / "measurement_event_candidates.parquet"
    candidates.to_parquet(candidates_path, index=False)

    quality_counts = (
        events["event_quality_status"].value_counts().to_dict() if not events.empty else {}
    )
    eligible_count = int(events["analysis_eligible"].sum()) if not events.empty else 0
    fraction = (eligible_count / len(events)) if len(events) else 0.0

    aligned_path = aligned_frames_path
    cand_in_path = sync_candidates_path
    rec_path = electrical_records_path

    manifest = MeasurementEventManifest(
        battery_id=battery_id,
        experiment_id=experiment_id,
        input_paths={
            "aligned": str(aligned_path),
            "sync_candidates": str(cand_in_path),
            "electrical_records": str(rec_path),
            "aux_temperature": str(aux_temperature_path) if aux_temperature_path else "",
        },
        input_checksums={
            "aligned": _sha256(aligned_path),
            "sync_candidates": _sha256(cand_in_path),
            "electrical_records": _sha256(rec_path),
            "aux_temperature": _sha256(aux_temperature_path) if aux_temperature_path else "",
        },
        aligned_row_count=len(aligned),
        sync_candidate_row_count=len(candidates_input) if candidates_input is not None else 0,
        electrical_row_count=len(records),
        aux_temperature_row_count=aux_row_count,
        event_row_count=len(events),
        event_candidate_row_count=len(candidates),
        quality_counts=quality_counts,
        analysis_eligible_count=eligible_count,
        analysis_eligible_fraction=fraction,
        electrical_enrichment_fields=list(config.electrical_enrichment.fields),
        aux_temperature_coverage={"total": aux_row_count},
        matching_recomputed=False,
        validated_sync=False,
        output_paths={
            "events": str(events_path),
            "candidates": str(candidates_path),
        },
        output_checksums={
            "events": _sha256(events_path),
            "candidates": _sha256(candidates_path),
        },
        warnings=[],
        limitations=[],
    )
    manifest_path = multimodal_dir / "measurement_event_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    report = MeasurementEventReport(
        battery_id=battery_id,
        experiment_id=experiment_id,
        builder_version=config.version,
        event_count=len(events),
        quality_counts=quality_counts,
        analysis_eligible_count=eligible_count,
        analysis_eligible_fraction=fraction,
        electrical_enrichment_fields=list(config.electrical_enrichment.fields),
        synced_source=str(aligned_path),
        configuration=config.model_dump(),
        artifacts={
            "events": str(events_path),
            "candidates": str(candidates_path),
            "manifest": str(manifest_path),
        },
    )
    report_dir = output_dir / "artifacts" / battery_id / experiment_id / "measurement_events"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "measurement_event_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "measurement_event_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    report.artifacts["report_json"] = str(json_path)
    report.artifacts["report_html"] = str(html_path)
    return report

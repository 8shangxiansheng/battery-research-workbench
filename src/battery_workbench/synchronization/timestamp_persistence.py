"""Persist BRW-009 timestamp engine outputs.

Writes the canonical ``timestamped_ultrasound_frames.parquet``, the
``timestamp_engine_manifest.json``, and JSON/HTML QA reports, all under the
standard synchronization output root. Inputs are never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.schemas import TimeAnchorState
from battery_workbench.synchronization.timestamp_schemas import (
    TimestampEngineConfig,
    TimestampEngineReport,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_or_none(path: Path) -> str | None:
    """Checksum if the file exists, otherwise None (builder is usable standalone)."""
    if not path.exists():
        return None
    return _sha256(path)


def _json_scalar(value):
    """Turn non-JSON-serializable scalar values into JSON-safe primitives."""
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


def write_timestamp_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Write one canonical timestamped frame table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def build_timestamp_manifest(
    *,
    battery_id: str,
    experiment_id: str,
    engine_version: str,
    frames_path: Path,
    time_anchor_state_path: Path,
    output_path: Path,
    asset_row_counts: dict[str, int],
    warnings: list[str],
    clock_model_type: str = "OFFSET_ONLY",
    drift_enabled: bool = False,
) -> dict:
    """Build the timestamp engine manifest with input/output checksums."""
    return {
        "engine_name": "timestamp_engine",
        "engine_version": engine_version,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "input_paths": {
            "frames": str(frames_path),
            "time_anchor_state": str(time_anchor_state_path),
        },
        "input_checksums": {
            "frames": _sha256_or_none(frames_path),
            "time_anchor_state": _sha256_or_none(time_anchor_state_path),
        },
        "output_path": str(output_path),
        "output_checksum": _sha256_or_none(output_path),
        "clock_model_type": clock_model_type,
        "drift_enabled": drift_enabled,
        "asset_row_counts": asset_row_counts,
        "warnings": list(warnings),
    }


def write_timestamp_payload(
    report: TimestampEngineReport,
    combined: pd.DataFrame,
    *,
    state: TimeAnchorState,
    frames_path: Path,
    time_anchor_state_path: Path,
    output_dir: Path,
    config: TimestampEngineConfig,
) -> dict[str, str]:
    """Write parquet + manifest + JSON/HTML report; return artifact path map."""
    output_dir = Path(output_dir)
    sync_dir = output_dir / "synchronization" / state.battery_id / state.experiment_id
    parquet_path = sync_dir / "timestamped_ultrasound_frames.parquet"
    write_timestamp_parquet(combined, parquet_path)

    asset_row_counts = {a.asset_id: a.frame_count for a in report.assets}
    manifest = build_timestamp_manifest(
        battery_id=state.battery_id,
        experiment_id=state.experiment_id,
        engine_version=config.version,
        frames_path=frames_path,
        time_anchor_state_path=time_anchor_state_path,
        output_path=parquet_path,
        asset_row_counts=asset_row_counts,
        warnings=report.warnings,
        clock_model_type=config.clock.model_type,
        drift_enabled=config.clock.drift_enabled,
    )
    manifest_path = sync_dir / "timestamp_engine_manifest.json"
    _write_json(manifest_path, manifest)

    # QA report artifacts.
    report_dir = (
        output_dir / "artifacts" / state.battery_id / state.experiment_id / "timestamp_engine"
    )
    json_path = report_dir / "timestamp_engine_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "timestamp_engine_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")

    return {
        "timestamped_frames": str(parquet_path),
        "timestamp_manifest": str(manifest_path),
        "report_json": str(json_path),
        "report_html": str(html_path),
    }


def _render_html(report: TimestampEngineReport) -> str:
    asset_rows = "\n".join(
        f"<li>{a.asset_id}: frames={a.frame_count}, "
        f"available={a.timestamp_available_count}, "
        f"anchor={a.anchor_status or 'N/A'}</li>"
        for a in report.assets
    )
    warnings = "\n".join(f"<li>{w}</li>" for w in report.warnings) or "<li>none</li>"
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Timestamp Engine Report</title></head>\n"
        "<body>\n"
        f"<h1>Timestamp Engine Report</h1>\n"
        f"<p>experiment_id: {report.experiment_id} — battery_id: {report.battery_id}</p>\n"
        f"<p>status: {report.status} — validated_sync: {report.validated_sync}</p>\n"
        f"<p>frames: in={report.input_frame_count} out={report.output_frame_count}</p>\n"
        "<h2>Assets</h2>\n"
        f"<ul>{asset_rows}</ul>\n"
        "<h2>Warnings</h2>\n"
        f"<ul>{warnings}</ul>\n"
        "</body></html>\n"
    )

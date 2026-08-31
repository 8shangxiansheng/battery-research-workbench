"""Persist BRW-010 synchronization outputs.

Writes ``aligned_ultrasound_frames.parquet``, ``synchronization_candidates.parquet``,
``synchronization_manifest.json``, and JSON/HTML reports plus four diagnostic
figures. Inputs are never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.synchronization.sync_schemas import SynchronizationReport

_FIG_FUNCS = (
    "sync_error_vs_time",
    "sync_error_histogram",
    "candidate_record_count_vs_time",
    "match_status_timeline",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return ""
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


def _render_html(report: SynchronizationReport) -> str:
    rows = "\n".join(f"<li>{r}</li>" for r in report.metrics.model_dump().items())
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Synchronization Report</title></head>\n"
        "<body>\n"
        f"<h1>Synchronization Report</h1>\n"
        f"<p>experiment_id: {report.experiment_id} — battery_id: {report.battery_id}</p>\n"
        f"<p>status: {report.status} — validated_sync: {report.validated_sync}</p>\n"
        f"<p>frames: {report.ultrasound_frame_count} — electrical records: {report.electrical_record_count}</p>\n"
        "<h2>Metrics</h2>\n"
        f"<ul>{rows}</ul>\n"
        "</body></html>\n"
    )


def _build_manifest(
    *,
    battery_id: str,
    experiment_id: str,
    sync_version: str,
    ultrasound_frames_path: Path,
    electrical_records_path: Path,
    aligned_path: Path,
    candidates_path: Path,
    aligned_row_count: int,
    candidates_row_count: int,
    report: SynchronizationReport | None,
    checksums: dict[str, str] | None,
) -> dict:
    checksums = checksums or {}
    manifest: dict[str, Any] = {
        "sync_engine_name": "synchronization_engine",
        "sync_engine_version": sync_version,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "matching_method": report.matching_method if report else "nearest",
        "max_sync_error_s": report.max_sync_error_s if report else 1.0,
        "tie_tolerance_s": report.tie_tolerance_s if report else 1e-9,
        "matches_frames": aligned_row_count,
        "ultrasound_row_count": aligned_row_count,
        "electrical_row_count": report.electrical_record_count if report else 0,
        "candidate_rows": candidates_row_count,
        "input_paths": {
            "ultrasound_timestamped": str(ultrasound_frames_path),
            "electrical_records": str(electrical_records_path),
        },
        "input_checksums": {
            "ultrasound_timestamped": checksums.get(
                "ultrasound_timestamped", _sha256(ultrasound_frames_path)
            ),
            "electrical_records": checksums.get(
                "electrical_records", _sha256(electrical_records_path)
            ),
        },
        "output_paths": {
            "aligned": str(aligned_path),
            "candidates": str(candidates_path),
        },
        "output_checksums": {
            "aligned": _sha256(aligned_path),
            "candidates": _sha256(candidates_path),
        },
        "matching_performed": report.matching_performed if report else True,
        "validated_sync": report.validated_sync if report else False,
        "sync_semantics": report.sync_semantics if report else "MATCHED_USING_PROVISIONAL_TIMEBASE",
        "quality_metrics": report.metrics.model_dump() if report else {},
        "warnings": report.warnings if report else [],
        "errors": report.errors if report else [],
    }
    return manifest


def write_sync_payload(
    aligned: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    battery_id: str,
    experiment_id: str,
    sync_version: str,
    ultrasound_frames_path: Path,
    electrical_records_path: Path,
    output_dir: Path,
    report: SynchronizationReport | None = None,
    checksums: dict[str, str] | None = None,
) -> dict[str, str]:
    """Write aligned + candidates parquet, manifest, and report/figures."""
    output_dir = Path(output_dir)
    sync_dir = output_dir / "synchronization" / battery_id / experiment_id
    sync_dir.mkdir(parents=True, exist_ok=True)

    aligned_path = sync_dir / "aligned_ultrasound_frames.parquet"
    aligned.to_parquet(aligned_path, index=False)
    candidates_path = sync_dir / "synchronization_candidates.parquet"
    candidates.to_parquet(candidates_path, index=False)

    manifest = _build_manifest(
        battery_id=battery_id,
        experiment_id=experiment_id,
        sync_version=sync_version,
        ultrasound_frames_path=Path(ultrasound_frames_path),
        electrical_records_path=Path(electrical_records_path),
        aligned_path=aligned_path,
        candidates_path=candidates_path,
        aligned_row_count=len(aligned),
        candidates_row_count=len(candidates),
        report=report,
        checksums=checksums,
    )
    manifest_path = sync_dir / "synchronization_manifest.json"
    _write_json(manifest_path, manifest)

    result = {
        "aligned": str(aligned_path),
        "candidates": str(candidates_path),
        "synchronization_manifest": str(manifest_path),
    }

    if report is not None:
        report_dir = output_dir / "artifacts" / battery_id / experiment_id / "synchronization"
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "synchronization_report.json"
        _write_json(json_path, report.model_dump(mode="json"))
        html_path = report_dir / "synchronization_report.html"
        html_path.write_text(_render_html(report), encoding="utf-8")
        result["report_json"] = str(json_path)
        result["report_html"] = str(html_path)
        figures_dir = report_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        _write_figures(aligned, figures_dir, result)

    return result


def _write_figures(aligned: pd.DataFrame, figures_dir: Path, result: dict[str, str]) -> None:
    """Write the four required diagnostic figures (no waveform plots)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001 - matplotlib is an optional runtime dependency
        # Without matplotlib we gracefully skip figures; the path map stays absent.
        return

    has_ts = "provisional_absolute_timestamp" in aligned.columns
    has_err = "sync_error_s" in aligned.columns

    def _save(fig, name: str) -> None:
        path = figures_dir / f"{name}.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        result[name] = str(path)

    # F01 sync_error vs time
    if has_ts and has_err:
        x = aligned["provisional_absolute_timestamp"]
        y = aligned["sync_error_s"]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(x, y, marker=".", linestyle="none", markersize=2)
        ax.set_xlabel("provisional_absolute_timestamp")
        ax.set_ylabel("sync_error_s")
        ax.set_title("F01 sync_error_vs_time")
        _save(fig, "sync_error_vs_time")

    # F02 sync_error histogram
    if has_err:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(aligned["sync_error_s"].dropna(), bins=40)
        ax.set_xlabel("sync_error_s")
        ax.set_ylabel("count")
        ax.set_title("F02 sync_error_histogram")
        _save(fig, "sync_error_histogram")

    # F03 candidate_record_count vs time
    if has_ts and "candidate_record_count" in aligned.columns:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(
            aligned["provisional_absolute_timestamp"],
            aligned["candidate_record_count"],
            marker=".",
            linestyle="none",
            markersize=2,
        )
        ax.set_xlabel("provisional_absolute_timestamp")
        ax.set_ylabel("candidate_record_count")
        ax.set_title("F03 candidate_record_count_vs_time")
        _save(fig, "candidate_record_count_vs_time")

    # F04 match_status timeline
    if "match_status" in aligned.columns:
        statuses = aligned["match_status"].astype("category")
        codes = statuses.cat.codes
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(range(len(aligned)), codes, marker=".", linestyle="none", markersize=2)
        ax.set_yticks(range(len(statuses.cat.categories)))
        ax.set_yticklabels(statuses.cat.categories)
        ax.set_xlabel("frame index")
        ax.set_ylabel("match_status")
        ax.set_title("F04 match_status_timeline")
        _save(fig, "match_status_timeline")

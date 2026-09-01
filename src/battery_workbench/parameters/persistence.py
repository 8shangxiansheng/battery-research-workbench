"""Persist BRW-015 parameter outputs.

Writes ``parameter_records.parquet``, ``effective_parameters.json``,
``parameter_set_manifest.json``, and ``capability_matrix.json`` under
``data/processed/parameters/{battery}/{exp}/{parameter_set_id}``, plus a
JSON/HTML report. Raw parser manifests are never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.parameters.schemas import (
    ParameterConfig,
    ParameterReport,
    ParameterSetManifest,
)


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
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


def _render_html(report: ParameterReport) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Parameter Report</title></head>\n"
        "<body>\n"
        f"<h1>Experiment Parameter Report</h1>\n"
        f"<p>parameter_set_id: {report.parameter_set_id}</p>\n"
        f"<p>battery: {report.battery_id} — experiment: {report.experiment_id}</p>\n"
        f"<p>status: {report.status}</p>\n"
        f"<p>records: {report.record_count} — known: {report.known_count} "
        f"unknown: {report.unknown_count} verified: {report.verified_count} "
        f"unverified: {report.unverified_count} conflict: {report.conflict_count}</p>\n"
        f"<p>sampling_rate_hz: {report.sampling_rate_hz} — TOF level: {report.tof_level}</p>\n"
        "</body></html>\n"
    )


def write_parameter_payload(
    *,
    records: pd.DataFrame,
    effective: dict[str, dict],
    capability_matrix: dict[str, dict],
    battery_id: str,
    experiment_id: str,
    parameter_set_id: str,
    input_paths: dict[str, Path],
    config: ParameterConfig,
    output_root: Path,
) -> ParameterReport:
    output_root = Path(output_root)
    out_dir = output_root / "parameters" / battery_id / experiment_id / parameter_set_id
    out_dir.mkdir(parents=True, exist_ok=True)

    records_path = out_dir / "parameter_records.parquet"
    records.to_parquet(records_path, index=False)
    effective_path = out_dir / "effective_parameters.json"
    _write_json(effective_path, effective)
    capability_path = out_dir / "capability_matrix.json"
    _write_json(capability_path, capability_matrix)

    known = sum(1 for v in effective.values() if v.get("status") == "RESOLVED")
    unknown = sum(1 for v in effective.values() if v.get("status") == "UNKNOWN")
    verified = sum(1 for v in effective.values() if v.get("verification_status") == "VERIFIED")
    unverified = sum(1 for v in effective.values() if v.get("verification_status") == "UNVERIFIED")
    conflicts = sum(1 for v in effective.values() if v.get("status") == "CONFLICT")

    sampling = effective.get("ultrasound.sampling_rate_hz", {})
    sampling_value = sampling.get("value")
    tof_level = capability_matrix.get("sample_time_conversion", {}).get("status") == "AVAILABLE"

    manifest = ParameterSetManifest(
        parameter_set_id=parameter_set_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        input_paths={k: str(v) for k, v in input_paths.items()},
        input_checksums={k: _sha256(v) for k, v in input_paths.items()},
        resolution_policy_version=config.resolution_policy_version,
        unit_policy_version=config.unit_policy_version,
        record_count=len(records),
        known_count=known,
        unknown_count=unknown,
        verified_count=verified,
        unverified_count=unverified,
        conflict_count=conflicts,
        sampling_rate_hz=sampling_value if isinstance(sampling_value, (int, float)) else None,
        sampling_rate_status=str(sampling.get("status", "UNKNOWN")),
        tof_level=1 if tof_level else 0,
        output_paths={
            "records": str(records_path),
            "effective_parameters": str(effective_path),
            "capability_matrix": str(capability_path),
            "manifest": str(out_dir / "parameter_set_manifest.json"),
        },
        output_checksums={"records": _sha256(records_path)},
        warnings=[],
        limitations=[
            "registry provides parameters only; it never recomputes SOC/SOH",
            "absolute TOF is not calculated in this task",
        ],
    )
    manifest_path = out_dir / "parameter_set_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    report = ParameterReport(
        parameter_set_id=parameter_set_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        registry_version=config.version,
        status="READY" if known > 0 else "EMPTY",
        record_count=len(records),
        known_count=known,
        unknown_count=unknown,
        verified_count=verified,
        unverified_count=unverified,
        conflict_count=conflicts,
        sampling_rate_hz=sampling_value if isinstance(sampling_value, (int, float)) else None,
        tof_level=1 if tof_level else 0,
        artifacts={
            "records": str(records_path),
            "effective_parameters": str(effective_path),
            "capability_matrix": str(capability_path),
            "manifest": str(manifest_path),
        },
        configuration=config.model_dump(),
    )
    report_dir = (
        output_root / "artifacts" / battery_id / experiment_id / "parameters" / parameter_set_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "parameter_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "parameter_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    report.artifacts["report_json"] = str(json_path)
    report.artifacts["report_html"] = str(html_path)
    return report

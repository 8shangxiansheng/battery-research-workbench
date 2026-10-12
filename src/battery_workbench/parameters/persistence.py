"""Persist BRW-015 parameter outputs.

Writes ``parameter_records.parquet``, ``effective_parameters.json``,
``parameter_set_manifest.json``, and ``capability_matrix.json`` under
``data/processed/parameters/{battery}/{exp}/{parameter_set_id}``, plus a
JSON/HTML report. Raw parser manifests are never mutated.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

from battery_workbench.parameters.schemas import (
    ParameterConfig,
    ParameterReport,
    ParameterSetManifest,
)
from battery_workbench.provenance.processed_manifest import content_sha256


def _resolve_processed_path(processed_root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    root = Path(processed_root).resolve()
    candidate = Path(reference)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            parts = PurePosixPath(reference.replace("\\", "/")).parts
            anchor = next(
                (i for i in range(len(parts) - 1) if parts[i : i + 2] == ("data", "processed")),
                None,
            )
            if anchor is None:
                return None
            suffix = parts[anchor + 2 :]
    else:
        suffix = candidate.parts
        if suffix[:2] == ("data", "processed"):
            suffix = suffix[2:]
    if not suffix or any(part in {"", ".", ".."} for part in suffix):
        return None
    resolved = root.joinpath(*suffix).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def verify_parameter_set_artifact(
    processed_root: Path,
    manifest_path: Path,
    manifest: Any,
    *,
    battery_id: str,
    experiment_id: str,
    parameter_set_id: str,
) -> list[str]:
    """Verify parameter-set identity and all scientific input/output bytes."""
    if not isinstance(manifest, dict):
        return ["MANIFEST_INVALID"]
    reasons: list[str] = []
    if manifest.get("battery_id") != battery_id:
        reasons.append("MANIFEST_BATTERY_ID_MISMATCH")
    if manifest.get("experiment_id") != experiment_id:
        reasons.append("MANIFEST_EXPERIMENT_ID_MISMATCH")
    if manifest.get("parameter_set_id") != parameter_set_id:
        reasons.append("PARAMETER_SET_ID_MISMATCH")

    root = Path(processed_root).resolve()
    canonical_dir = root / "parameters" / battery_id / experiment_id / parameter_set_id
    try:
        Path(manifest_path).resolve().relative_to(canonical_dir.resolve())
    except (OSError, ValueError):
        reasons.append("MANIFEST_PATH_INVALID")

    required_inputs = {
        "measurement_events": root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet",
        "cycles": root / "electrical" / battery_id / experiment_id / "cycles.parquet",
        "waveform_store": root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr",
        "label_manifest": root / "labels" / battery_id / experiment_id / "label_manifest.json",
    }
    input_paths = manifest.get("input_paths")
    input_checksums = manifest.get("input_checksums")
    if not isinstance(input_paths, dict) or not isinstance(input_checksums, dict):
        reasons.append("INPUT_MANIFEST_INVALID")
    else:
        for key, expected_path in required_inputs.items():
            actual_path = _resolve_processed_path(root, input_paths.get(key))
            expected = input_checksums.get(key)
            if actual_path is None:
                reasons.append(f"INPUT_PATH_INVALID:{key}")
            elif actual_path != expected_path.resolve():
                reasons.append(f"INPUT_PATH_NONCANONICAL:{key}")
            elif not (actual_path.is_dir() if key == "waveform_store" else actual_path.is_file()):
                reasons.append(f"INPUT_MISSING:{key}")
            elif not isinstance(expected, str) or len(expected) != 64:
                reasons.append(f"INPUT_CHECKSUM_MISSING:{key}")
            elif content_sha256(actual_path) != expected.lower():
                reasons.append(f"INPUT_CHECKSUM_MISMATCH:{key}")

    output_files = {
        "records": "parameter_records.parquet",
        "effective_parameters": "effective_parameters.json",
        "capability_matrix": "capability_matrix.json",
    }
    output_paths = manifest.get("output_paths")
    output_checksums = manifest.get("output_checksums")
    if not isinstance(output_paths, dict) or not isinstance(output_checksums, dict):
        reasons.append("OUTPUT_MANIFEST_INVALID")
    else:
        for key, filename in output_files.items():
            actual_path = _resolve_processed_path(root, output_paths.get(key))
            expected_path = canonical_dir / filename
            expected = output_checksums.get(key)
            if actual_path is None:
                reasons.append(f"OUTPUT_PATH_INVALID:{key}")
            elif actual_path != expected_path.resolve():
                reasons.append(f"OUTPUT_PATH_NONCANONICAL:{key}")
            elif not actual_path.is_file():
                reasons.append(f"OUTPUT_MISSING:{key}")
            elif not isinstance(expected, str) or len(expected) != 64:
                reasons.append(f"OUTPUT_CHECKSUM_MISSING:{key}")
            elif content_sha256(actual_path) != expected.lower():
                reasons.append(f"OUTPUT_CHECKSUM_MISMATCH:{key}")
    return list(dict.fromkeys(reasons))


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
        input_checksums={k: content_sha256(v) for k, v in input_paths.items()},
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
        output_checksums={
            "records": content_sha256(records_path),
            "effective_parameters": content_sha256(effective_path),
            "capability_matrix": content_sha256(capability_path),
        },
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

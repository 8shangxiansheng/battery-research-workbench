"""Persist BRW-014 reference-label outputs.

Writes ``event_labels.parquet``, ``cycle_labels.parquet``, ``label_definitions.json``,
``label_manifest.json``, and ``tof_readiness.json`` under
``data/processed/labels/{battery}/{experiment}``, plus a JSON/HTML report.
Inputs are never mutated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.labels.definitions import LABEL_DEFINITIONS
from battery_workbench.labels.schemas import (
    LabelConfig,
    LabelManifest,
    LabelReport,
    TofReadiness,
)
from battery_workbench.labels.soh import ReferenceCapacity


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_label_artifact(
    processed_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    battery_id: str,
    experiment_id: str,
) -> list[str]:
    """Verify label artifact inputs, outputs, identity, and canonical paths."""
    from battery_workbench.provenance.processed_manifest import verify_manifest_files

    root = Path(processed_root).resolve()
    from battery_workbench.labels.schemas import LabelConfig

    current_config = LabelConfig()
    reasons: list[str] = []
    if manifest.get("label_engine_version") != current_config.version:
        reasons.append("LABEL_ENGINE_VERSION_UNSUPPORTED")
    if manifest.get("label_definition_version") != current_config.label_definition_version:
        reasons.append("LABEL_DEFINITION_VERSION_UNSUPPORTED")
    manifest_file = Path(manifest_path)
    try:
        resolved_manifest = manifest_file.resolve(strict=True)
        artifact_dir = resolved_manifest.parent
        artifact_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return list(dict.fromkeys([*reasons, "LABEL_MANIFEST_INVALID"]))
    if artifact_dir != (root / "labels" / battery_id / experiment_id).resolve():
        reasons.append("LABEL_ARTIFACT_PATH_MISMATCH")

    canonical_inputs = {
        "measurement_events": root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet",
        "records": root / "electrical" / battery_id / experiment_id / "records.parquet",
        "cycles": root / "electrical" / battery_id / experiment_id / "cycles.parquet",
        "steps": root / "electrical" / battery_id / experiment_id / "steps.parquet",
        "ultrasound_manifest": root / "ultrasound" / battery_id / experiment_id / "parser_manifest.json",
    }
    input_paths = manifest.get("input_paths")
    for key, expected in canonical_inputs.items():
        actual = _resolve_label_reference(root, input_paths.get(key) if isinstance(input_paths, dict) else None)
        if actual != expected.resolve():
            reasons.append(f"LABEL_INPUT_PATH_MISMATCH:{key}")

    translated = {
        "battery_id": manifest.get("battery_id"),
        "experiment_id": manifest.get("experiment_id"),
        "input_paths": input_paths,
        "input_checksums": manifest.get("input_checksums"),
        "output_paths": manifest.get("output_paths"),
        "output_checksums": manifest.get("output_checksums"),
    }
    reasons.extend(
        verify_manifest_files(
            root,
            translated,
            battery_id=battery_id,
            experiment_id=experiment_id,
            required_inputs=set(canonical_inputs),
            required_outputs={"event_labels", "cycle_labels", "definitions", "tof_readiness"},
        )
    )
    return list(dict.fromkeys(reasons))


def _resolve_label_reference(root: Path, reference: Any) -> Path | None:
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


def _render_html(report: LabelReport) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Reference Label Report</title></head>\n"
        "<body>\n"
        f"<h1>Reference Label Report</h1>\n"
        f"<p>label_set_id: {report.label_set_id}</p>\n"
        f"<p>battery: {report.battery_id} — experiment: {report.experiment_id}</p>\n"
        f"<p>status: {report.status}</p>\n"
        f"<p>event labels: {report.event_label_count} — cycle labels: {report.cycle_label_count}</p>\n"
        f"<p>SOC valid: {report.soc_valid_count} — ineligible: {report.soc_ineligible_count}</p>\n"
        f"<p>independent SOH states: {report.soh_independent_state_count}</p>\n"
        f"<p>frame_random_split_prohibited: {report.frame_random_split_prohibited}</p>\n"
        "</body></html>\n"
    )


def write_label_payload(
    *,
    event_labels: pd.DataFrame,
    cycle_labels: pd.DataFrame,
    tof: TofReadiness,
    battery_id: str,
    experiment_id: str,
    label_set_id: str,
    measurement_events_path: Path,
    records_path: Path,
    cycles_path: Path,
    steps_path: Path,
    ultrasound_manifest_path: Path,
    soc_valid_count: int,
    soc_ineligible_count: int,
    soh_state_count: int,
    soh_readiness: Any,
    reference: ReferenceCapacity,
    vendor_diagnostic: dict[str, Any],
    ce_diagnostic: dict[str, Any],
    config: LabelConfig,
    output_root: Path,
    supersedes_label_set_id: str | None = None,
) -> LabelReport:
    output_root = Path(output_root)
    out_dir = output_root / "labels" / battery_id / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)

    events_path = out_dir / "event_labels.parquet"
    event_labels.to_parquet(events_path, index=False)
    cycle_path = out_dir / "cycle_labels.parquet"
    cycle_labels.to_parquet(cycle_path, index=False)
    defs_path = out_dir / "label_definitions.json"
    _write_json(
        defs_path,
        {"label_definition_version": config.label_definition_version, "labels": LABEL_DEFINITIONS},
    )
    tof_path = out_dir / "tof_readiness.json"
    _write_json(tof_path, tof.model_dump(mode="json"))

    manifest = LabelManifest(
        label_set_id=label_set_id,
        label_engine_version=config.version,
        label_definition_version=config.label_definition_version,
        battery_id=battery_id,
        experiment_id=experiment_id,
        input_paths={
            "measurement_events": str(measurement_events_path),
            "records": str(records_path),
            "cycles": str(cycles_path),
            "steps": str(steps_path),
            "ultrasound_manifest": str(ultrasound_manifest_path),
        },
        input_checksums={
            "measurement_events": _sha256(measurement_events_path),
            "records": _sha256(records_path),
            "cycles": _sha256(cycles_path),
            "steps": _sha256(steps_path),
            "ultrasound_manifest": _sha256(ultrasound_manifest_path),
        },
        soc_method=config.soc.method,
        soc_formula_version=config.soc.formula_version,
        soc_temporality="RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE",
        soc_anchor="CHARGE_SEGMENT_START(empty) / DISCHARGE_SEGMENT_START(full) / REST_PROPAGATED",
        soc_q_ref=reference.q_ref_ah,
        soc_valid_count=soc_valid_count,
        soc_null_count=soc_ineligible_count,
        soc_ineligible_count=soc_ineligible_count,
        soh_method=config.soh.method,
        soh_formula_version=config.soh.formula_version,
        soh_reference_source=reference.reference_capacity_source,
        soh_reference_cycle=reference.reference_cycle_index,
        soh_reference_capacity_ah=reference.q_ref_ah,
        soh_independent_state_count=soh_state_count,
        soh_model_readiness=soh_readiness.readiness,
        supersedes_label_set_id=supersedes_label_set_id,
        frame_random_split_prohibited=config.leakage.frame_random_split_prohibited,
        group_fields=[
            "battery_group_id",
            "experiment_group_id",
            "cycle_group_id",
            "label_group_id",
        ],
        reference_scope="WITHIN_EXPERIMENT_BASELINE",
        tof_readiness=tof.model_dump(mode="json"),
        output_paths={
            "event_labels": str(events_path),
            "cycle_labels": str(cycle_path),
            "definitions": str(defs_path),
            "tof_readiness": str(tof_path),
        },
        output_checksums={
            "event_labels": _sha256(events_path),
            "cycle_labels": _sha256(cycle_path),
            "definitions": _sha256(defs_path),
            "tof_readiness": _sha256(tof_path),
        },
        warnings=[],
        limitations=[
            "SOC V2 is RETROSPECTIVE_SEGMENT_NORMALIZED: denominators are segment totals known only after segment completion; not online-causal",
            "SOH independent states are cycle-level; readiness=" + soh_readiness.readiness,
            "vendor soc_dod_percent is a mixed field and is never promoted",
        ],
    )
    manifest_path = out_dir / "label_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    report = LabelReport(
        label_set_id=label_set_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        label_engine_version=config.version,
        status="READY" if soc_valid_count > 0 else "PARTIAL",
        event_label_count=len(event_labels),
        cycle_label_count=len(cycle_labels),
        soc_valid_count=soc_valid_count,
        soc_ineligible_count=soc_ineligible_count,
        soh_independent_state_count=soh_state_count,
        vendor_diagnostic=vendor_diagnostic,
        apparent_coulombic_efficiency=ce_diagnostic,
        frame_random_split_prohibited=config.leakage.frame_random_split_prohibited,
        warnings=[],
        limitations=manifest.limitations,
        artifacts={
            "event_labels": str(events_path),
            "cycle_labels": str(cycle_path),
            "manifest": str(manifest_path),
        },
        configuration=config.model_dump(),
    )
    report_dir = output_root / "artifacts" / battery_id / experiment_id / "labels"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "label_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "label_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    report.artifacts["report_json"] = str(json_path)
    report.artifacts["report_html"] = str(html_path)
    return report

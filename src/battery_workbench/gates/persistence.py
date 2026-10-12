"""BRW-018 gated feature persistence.

Writes gated_features.parquet, gate_specs.json, gated_feature_manifest.json,
and gated_feature_schema.json under
``data/processed/gated_features/{battery}/{experiment}/{gate_set_id}/``.
Waveform samples are never copied into the parquet.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.gates.schemas import GateSpec, TOFDefinitionSpec, gate_set_ml_ready


def _sha256(path: Path) -> str:
    if path.is_dir():
        h = hashlib.sha256()
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(str(f.relative_to(path)).encode())
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
        return h.hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_gated_feature_artifact(
    processed_root: Path, artifact_dir: Path, manifest: dict[str, Any]
) -> list[str]:
    """Verify gate payload outputs and the waveform store used to derive them."""
    root = Path(processed_root).resolve()
    directory = Path(artifact_dir)
    try:
        resolved_dir = directory.resolve(strict=True)
        resolved_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["GATED_FEATURE_PATH_INVALID"]
    if not resolved_dir.is_dir():
        return ["GATED_FEATURE_PATH_INVALID"]

    checksums = manifest.get("output_checksums")
    required_outputs = {
        "gated_features": "gated_features.parquet",
        "gate_specs": "gate_specs.json",
        "gated_feature_schema": "gated_feature_schema.json",
    }
    reasons: list[str] = []
    if not isinstance(checksums, dict):
        reasons.append("GATED_FEATURE_OUTPUT_CHECKSUMS_MISSING")
    else:
        for key, filename in required_outputs.items():
            expected = checksums.get(key)
            path = resolved_dir / filename
            if not isinstance(expected, str) or len(expected) != 64:
                reasons.append(f"GATED_FEATURE_OUTPUT_CHECKSUM_MISSING:{key}")
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                actual = _sha256(resolved)
            except (OSError, RuntimeError, ValueError):
                reasons.append(f"GATED_FEATURE_OUTPUT_MISSING_OR_OUTSIDE:{key}")
                continue
            if actual.lower() != expected.lower():
                reasons.append(f"GATED_FEATURE_OUTPUT_CHECKSUM_MISMATCH:{key}")

    waveform_path_raw = manifest.get("waveform_store_path")
    waveform_checksum = manifest.get("waveform_store_checksum")
    if not isinstance(waveform_path_raw, str) or not waveform_path_raw.strip():
        reasons.append("GATED_FEATURE_WAVEFORM_PROVENANCE_MISSING")
    elif not isinstance(waveform_checksum, str) or len(waveform_checksum) != 64:
        reasons.append("GATED_FEATURE_WAVEFORM_CHECKSUM_MISSING")
    else:
        waveform_path = Path(waveform_path_raw)
        if waveform_path.is_absolute():
            candidate = waveform_path
        elif waveform_path.parts[:2] == ("data", "processed"):
            candidate = root.joinpath(*waveform_path.parts[2:])
        elif ".." in waveform_path.parts:
            candidate = root / "__invalid_waveform_path__"
        else:
            candidate = root / waveform_path
        try:
            resolved_waveforms = candidate.resolve(strict=True)
            resolved_waveforms.relative_to(root)
            actual_waveform_checksum = _sha256(resolved_waveforms)
        except (OSError, RuntimeError, ValueError):
            reasons.append("GATED_FEATURE_WAVEFORM_MISSING_OR_OUTSIDE")
        else:
            if actual_waveform_checksum.lower() != waveform_checksum.lower():
                reasons.append("GATED_FEATURE_WAVEFORM_CHECKSUM_MISMATCH")

    try:
        specs = json.loads((resolved_dir / "gate_specs.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        specs = None
        reasons.append("GATED_FEATURE_GATE_SPECS_UNREADABLE")
    if not isinstance(specs, list) or specs != manifest.get("gates"):
        reasons.append("GATED_FEATURE_GATE_SPECS_MANIFEST_MISMATCH")
    else:
        try:
            gates = [GateSpec.model_validate(item) for item in specs]
            if build_gate_set_id(gates) != manifest.get("gate_set_id"):
                reasons.append("GATED_FEATURE_GATE_SET_ID_MISMATCH")
        except (TypeError, ValueError):
            reasons.append("GATED_FEATURE_GATE_SPECS_INVALID")
    return list(dict.fromkeys(reasons))


def build_gate_set_id(gate_specs: list[GateSpec]) -> str:
    """Deterministic id for an ordered set of gates."""
    canonical = json.dumps([g.gate_id for g in gate_specs], sort_keys=False, separators=(",", ":"))
    return "GATESET::" + hashlib.sha256(canonical.encode()).hexdigest()[:20]


def write_gated_feature_payload(
    *,
    gated_features: pd.DataFrame,
    gate_specs: list[GateSpec],
    tof_definitions: list[TOFDefinitionSpec],
    gate_selection_basis: str,
    battery_id: str,
    experiment_id: str,
    output_root: Path,
    waveform_store_path: str = "",
) -> dict[str, str]:
    """Persist gated features + specs + manifest + schema; returns paths."""
    output_root = Path(output_root)
    gate_set_id = build_gate_set_id(gate_specs)
    out_dir = output_root / "gated_features" / battery_id / experiment_id / gate_set_id
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "gated_features.parquet"
    gated_features.to_parquet(parquet_path, index=False)

    specs_path = out_dir / "gate_specs.json"
    specs_path.write_text(
        json.dumps([g.model_dump(mode="json") for g in gate_specs], indent=2) + "\n",
        encoding="utf-8",
    )

    schema_entries = [
        {"column": c, "dtype": str(gated_features[c].dtype)} for c in gated_features.columns
    ]
    schema_path = out_dir / "gated_feature_schema.json"
    schema_path.write_text(json.dumps(schema_entries, indent=2) + "\n", encoding="utf-8")

    waveform_path = Path(waveform_store_path) if waveform_store_path else None
    waveform_relative_path = ""
    waveform_checksum = ""
    if waveform_path is not None and waveform_path.exists():
        resolved_waveform_path = waveform_path.resolve(strict=True)
        resolved_waveform_path.relative_to(output_root.resolve())
        waveform_relative_path = resolved_waveform_path.relative_to(
            output_root.resolve()
        ).as_posix()
        waveform_checksum = _sha256(resolved_waveform_path)
    output_checksums = {
        "gated_features": _sha256(parquet_path),
        "gate_specs": _sha256(specs_path),
        "gated_feature_schema": _sha256(schema_path),
    }
    manifest = {
        "gate_set_id": gate_set_id,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "gate_selection_basis": gate_selection_basis,
        "ml_ready": gate_set_ml_ready(gate_specs),
        "gates": [g.model_dump(mode="json") for g in gate_specs],
        "tof_definitions": [t.model_dump(mode="json") for t in tof_definitions],
        "row_count": len(gated_features),
        "waveform_store_path": waveform_relative_path,
        "waveform_store_checksum": waveform_checksum,
        "output_checksums": output_checksums,
    }
    manifest_path = out_dir / "gated_feature_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "gate_set_id": gate_set_id,
        "gated_features": str(parquet_path),
        "gate_specs": str(specs_path),
        "gated_feature_manifest": str(manifest_path),
        "gated_feature_schema": str(schema_path),
    }


def write_gated_analysis_payload(
    *,
    analysis_df: pd.DataFrame,
    manifest: dict[str, Any],
    report: dict[str, Any],
    battery_id: str,
    experiment_id: str,
    gate_set_id: str,
    output_root: Path,
    input_files: dict[str, Path] | None = None,
) -> dict[str, str]:
    """Output contract: feature_analysis/{battery}/{experiment}/{gate_set_id}/."""
    out_dir = Path(output_root) / "feature_analysis" / battery_id / experiment_id / gate_set_id
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "gated_feature_label_analysis.parquet"
    analysis_df.to_parquet(parquet_path, index=False)
    manifest_path = out_dir / "gated_analysis_manifest.json"
    report_path = out_dir / "gated_analysis_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    root = Path(output_root).resolve()
    input_paths: dict[str, str] = {}
    input_checksums: dict[str, str] = {}
    for key, source_path in (input_files or {}).items():
        resolved = Path(source_path).resolve(strict=True)
        resolved.relative_to(root)
        input_paths[key] = resolved.relative_to(root).as_posix()
        input_checksums[key] = _sha256(resolved)
    manifest.update(
        {
            "output_checksums": {
                "analysis": _sha256(parquet_path),
                "report": _sha256(report_path),
            },
            "input_paths": input_paths,
            "input_checksums": input_checksums,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "analysis_parquet": str(parquet_path.relative_to(output_root)),
        "analysis_manifest": str(manifest_path.relative_to(output_root)),
        "analysis_report": str(report_path.relative_to(output_root)),
    }


def verify_gated_analysis_artifact(
    processed_root: Path, artifact_dir: Path, manifest: dict[str, Any]
) -> list[str]:
    """Verify gated feature-label analysis inputs and persisted outputs."""
    from battery_workbench.provenance.processed_manifest import (
        verify_manifest_inputs,
        verify_output_checksums_in_directory,
    )

    root = Path(processed_root).resolve()
    directory = Path(artifact_dir)
    try:
        resolved = directory.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["GATED_ANALYSIS_PATH_INVALID"]
    reasons = verify_output_checksums_in_directory(
        root,
        resolved,
        manifest.get("output_checksums"),
        {
            "analysis": "gated_feature_label_analysis.parquet",
            "report": "gated_analysis_report.json",
        },
    )
    reasons.extend(
        verify_manifest_inputs(
            root,
            manifest,
            required_inputs={
                "gated_features",
                "gated_feature_manifest",
                "gate_specs",
                "event_labels",
                "cycle_labels",
                "label_manifest",
            },
        )
    )
    if manifest.get("gate_set_id") != resolved.name:
        reasons.append("GATED_ANALYSIS_GATE_SET_ID_MISMATCH")
    return list(dict.fromkeys(reasons))


def write_gate_report_artifacts(
    *,
    report: dict[str, Any],
    plots: dict[str, bytes],
    battery_id: str,
    experiment_id: str,
    gate_set_id: str,
    output_root: Path,
) -> dict[str, str]:
    """Recommended report: artifacts/{battery}/{experiment}/gates/{gate_set_id}/."""
    out_dir = Path(output_root) / "artifacts" / battery_id / experiment_id / "gates" / gate_set_id
    plots_dir = out_dir / "representative_waveforms"
    plots_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in plots.items():
        (plots_dir / f"{name}.png").write_bytes(payload)
    report_json = out_dir / "waveform_gate_report.json"
    report_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_html = out_dir / "waveform_gate_report.html"
    report_html.write_text(
        "<html><body><h1>Waveform Gate Report</h1><pre>"
        + json.dumps(report, indent=2, ensure_ascii=False)
        + "</pre></body></html>\n",
        encoding="utf-8",
    )
    return {
        "report_json": str(report_json.relative_to(output_root)),
        "report_html": str(report_html.relative_to(output_root)),
        "representative_waveforms": str(plots_dir.relative_to(output_root)),
    }

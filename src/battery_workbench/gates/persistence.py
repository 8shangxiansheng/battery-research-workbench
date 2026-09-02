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

    manifest = {
        "gate_set_id": gate_set_id,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "gate_selection_basis": gate_selection_basis,
        "ml_ready": gate_set_ml_ready(gate_specs),
        "gates": [g.model_dump(mode="json") for g in gate_specs],
        "tof_definitions": [t.model_dump(mode="json") for t in tof_definitions],
        "row_count": len(gated_features),
        "waveform_store_path": waveform_store_path,
        "waveform_store_checksum": _sha256(Path(waveform_store_path))
        if waveform_store_path and Path(waveform_store_path).exists()
        else "",
        "output_checksums": {
            "gated_features": _sha256(parquet_path),
            "gate_specs": _sha256(specs_path),
        },
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
) -> dict[str, str]:
    """Output contract: feature_analysis/{battery}/{experiment}/{gate_set_id}/."""
    out_dir = Path(output_root) / "feature_analysis" / battery_id / experiment_id / gate_set_id
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "gated_feature_label_analysis.parquet"
    analysis_df.to_parquet(parquet_path, index=False)
    manifest_path = out_dir / "gated_analysis_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = out_dir / "gated_analysis_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "analysis_parquet": str(parquet_path.relative_to(output_root)),
        "analysis_manifest": str(manifest_path.relative_to(output_root)),
        "analysis_report": str(report_path.relative_to(output_root)),
    }


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

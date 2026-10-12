"""BRW-017R2 — Canonical envelope-peak TOF series computation.

Thin orchestration over the deterministic envelope_peak_tof function:
reads fs from the effective parameter set (never guessed), applies the
calibrated TOF gate bindings, and computes a per-frame series. Missing fs
keeps sample-domain results and leaves tof_us null. XCorr quantities are
never consumed here and never populate canonical tof_us.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.features.gate_calibration import (
    CANONICAL_TOF_METHOD,
    TOF_DEFINITION_VERSION,
    TOF_POLICY_VERSION,
    TOFGateBinding,
)
from battery_workbench.features_physical.envelope_peak_tof import envelope_peak_tof
from battery_workbench.provenance.processed_manifest import (
    verify_manifest_files,
)

CANONICAL_TOF_OUTPUT_COLUMNS = [
    "measurement_event_id",
    "frame_index_raw",
    "tof_method_id",
    "tof_definition_version",
    "tof_policy_version",
    "surface_gate_id",
    "bottom_gate_id",
    "gate_calibration_id",
    "surface_peak_sample_index",
    "bottom_peak_sample_index",
    "surface_peak_local_index",
    "bottom_peak_local_index",
    "surface_envelope_peak_amplitude_a_u",
    "bottom_envelope_peak_amplitude_a_u",
    "tof_samples",
    "sampling_rate_hz",
    "tof_s",
    "tof_us",
    "tof_status",
    "tof_quality_reason",
    "parameter_set_id",
]


def verify_canonical_tof_artifact(
    processed_root: Path,
    manifest_path: Path,
    manifest: Any,
    *,
    battery_id: str,
    experiment_id: str,
    feature_set_id: str,
    feature_table_path: Path,
    parameter_set_id: str,
    gate_calibration: dict[str, Any],
) -> list[str]:
    """Check canonical TOF identity, active sources, and persisted outputs."""
    root = Path(processed_root).resolve()
    artifact_dir = root / "features_physical" / battery_id / experiment_id
    expected_manifest = artifact_dir / "canonical_tof_manifest.json"
    reasons: list[str] = []
    if Path(manifest_path).resolve() != expected_manifest.resolve():
        reasons.append("MANIFEST_PATH_INVALID")
    if not isinstance(manifest, dict):
        return [*reasons, "MANIFEST_INVALID"]
    if manifest.get("battery_id") != battery_id:
        reasons.append("MANIFEST_BATTERY_ID_MISMATCH")
    if manifest.get("experiment_id") != experiment_id:
        reasons.append("MANIFEST_EXPERIMENT_ID_MISMATCH")
    if manifest.get("feature_set_id") != feature_set_id:
        reasons.append("FEATURE_SET_ID_MISMATCH")
    if manifest.get("parameter_set_id") != parameter_set_id:
        reasons.append("PARAMETER_SET_ID_MISMATCH")
    if not feature_set_id:
        reasons.append("FEATURE_SET_ID_MISSING")
    if not parameter_set_id:
        reasons.append("PARAMETER_SET_ID_MISSING")
    if manifest.get("gate_calibration") != gate_calibration:
        reasons.append("GATE_CALIBRATION_CHANGED")

    input_paths = manifest.get("input_paths")
    expected_inputs = {
        "ultrasound_features": Path(feature_table_path),
        "feature_set_manifest": Path(feature_table_path).parent / "feature_set_manifest.json",
        "analysis_slice": root
        / "analysis_slices"
        / battery_id
        / experiment_id
        / Path(feature_table_path).parent.parent.name
        / "analysis_slice.parquet",
        "measurement_events": root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_events.parquet",
        "waveform_store": root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr",
        "effective_parameters": root
        / "parameters"
        / battery_id
        / experiment_id
        / parameter_set_id
        / "effective_parameters.json",
        "parameter_set_manifest": root
        / "parameters"
        / battery_id
        / experiment_id
        / parameter_set_id
        / "parameter_set_manifest.json",
    }
    if gate_calibration.get("source") == "EXPERIMENT_CONFIRMED":
        expected_inputs["gate_calibration_record"] = (
            root
            / "gate_calibrations"
            / battery_id
            / experiment_id
            / f"{gate_calibration.get('gate_calibration_id')}.json"
        )
    if not isinstance(input_paths, dict):
        reasons.append("INPUT_PATHS_INVALID")
    else:
        for key, expected_path in expected_inputs.items():
            try:
                actual_path = Path(input_paths.get(key, "")).resolve()
                actual_path.relative_to(root)
            except (OSError, RuntimeError, TypeError, ValueError):
                reasons.append(f"INPUT_PATH_INVALID:{key}")
                continue
            if actual_path != expected_path.resolve():
                reasons.append(f"INPUT_PATH_NONCANONICAL:{key}")

    required_inputs = set(expected_inputs)
    if "gate_calibration_record" in expected_inputs:
        required_inputs.add("gate_calibration_record")
    reasons.extend(
        verify_manifest_files(
            root,
            manifest,
            battery_id=battery_id,
            experiment_id=experiment_id,
            required_inputs=required_inputs,
            required_outputs={"canonical_tof", "audit"},
        )
    )
    expected_outputs = {
        "canonical_tof": artifact_dir / "canonical_tof.parquet",
        "audit": artifact_dir / "canonical_tof_audit.json",
    }
    output_paths = manifest.get("output_paths")
    if isinstance(output_paths, dict):
        for key, expected_path in expected_outputs.items():
            try:
                actual_path = Path(output_paths.get(key, "")).resolve()
            except (OSError, RuntimeError, TypeError, ValueError):
                reasons.append(f"OUTPUT_PATH_INVALID:{key}")
                continue
            if actual_path != expected_path.resolve():
                reasons.append(f"OUTPUT_PATH_NONCANONICAL:{key}")
    return list(dict.fromkeys(reasons))


def canonical_tof_integrity_reasons(
    processed_root: Path, battery_id: str, experiment_id: str
) -> list[str]:
    """Assess the persisted canonical TOF against its current byte sources."""
    root = Path(processed_root)
    manifest_path = (
        root
        / "features_physical"
        / battery_id
        / experiment_id
        / "canonical_tof_manifest.json"
    )
    try:
        manifest_path.resolve(strict=True).relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return ["CANONICAL_TOF_MANIFEST_MISSING_OR_INVALID"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["CANONICAL_TOF_MANIFEST_UNREADABLE"]
    if not isinstance(manifest, dict):
        return ["MANIFEST_INVALID"]
    input_paths = manifest.get("input_paths")
    if not isinstance(input_paths, dict):
        return ["INPUT_PATHS_INVALID"]
    from battery_workbench.features.gate_calibration import resolve_tof_gate_calibration

    calibration = resolve_tof_gate_calibration(battery_id, experiment_id, root)
    try:
        feature_table_path = Path(input_paths.get("ultrasound_features", ""))
    except (TypeError, ValueError):
        return ["INPUT_PATH_INVALID:ultrasound_features"]
    return verify_canonical_tof_artifact(
        root,
        manifest_path,
        manifest,
        battery_id=battery_id,
        experiment_id=experiment_id,
        feature_set_id=str(manifest.get("feature_set_id") or ""),
        feature_table_path=feature_table_path,
        parameter_set_id=str(manifest.get("parameter_set_id") or ""),
        gate_calibration=calibration,
    )


def canonical_tof_values_by_event(
    event_ids: list[str], canonical_rows: pd.DataFrame
) -> list[float | None]:
    """Return canonical TOF values aligned by stable MeasurementEvent identity.

    Raw frame indices are local to a DataAsset and may repeat across files; they
    must never be used as a cross-asset lookup key.
    """
    required = {"measurement_event_id", "tof_us", "tof_status"}
    if not required <= set(canonical_rows.columns):
        raise ValueError(f"canonical TOF rows require columns: {sorted(required)}")
    valid = canonical_rows[canonical_rows["tof_status"] == "VALID"].dropna(
        subset=["measurement_event_id", "tof_us"]
    )
    if valid["measurement_event_id"].astype(str).duplicated().any():
        raise ValueError("canonical TOF contains duplicate MeasurementEvent identities")
    values = {
        str(row.measurement_event_id): float(row.tof_us)
        for row in valid.itertuples(index=False)
    }
    return [values.get(str(event_id)) for event_id in event_ids]


def effective_fs(
    effective_parameters: dict[str, Any], *, require_verified: bool = True
) -> tuple[float | None, bool]:
    """fs from the Experiment Parameter Registry — the ONLY legal source.

    Returns (fs_hz, verified). Never reads cadence/sample counts/filenames.
    """
    entry = (effective_parameters or {}).get("ultrasound.sampling_rate_hz") or {}
    value = entry.get("value")
    status = str(entry.get("status", ""))
    verified = bool(entry.get("verification_status") == "VERIFIED") or (
        not require_verified and status == "RESOLVED"
    )
    if value is None or status != "RESOLVED":
        return None, False
    try:
        fs = float(value)
    except (TypeError, ValueError):
        return None, False
    if fs <= 0 or not np.isfinite(fs):
        return None, False
    return fs, verified


def compute_canonical_tof_series(
    frames: np.ndarray,
    measurement_event_ids: list[str],
    *,
    surface_gate: TOFGateBinding,
    bottom_gate: TOFGateBinding,
    gate_calibration_id: str,
    sampling_rate_hz: float | None,
    parameter_set_id: str | None,
    frame_index_offset: int = 0,
) -> pd.DataFrame:
    """Per-frame canonical TOF series (deterministic; pure computation)."""
    rows: list[dict[str, Any]] = []
    for i, event_id in enumerate(measurement_event_ids):
        waveform = np.asarray(frames[i], dtype=np.float64)
        result = envelope_peak_tof(
            waveform,
            surface_gate.python_start,
            surface_gate.python_end_exclusive,
            bottom_gate.python_start,
            bottom_gate.python_end_exclusive,
            sampling_rate_hz=sampling_rate_hz,
        )
        tof_s = (
            result.tof_samples / sampling_rate_hz
            if result.tof_samples is not None and sampling_rate_hz
            else None
        )
        rows.append(
            {
                "measurement_event_id": event_id,
                "frame_index_raw": frame_index_offset + i,
                "tof_method_id": CANONICAL_TOF_METHOD,
                "tof_definition_version": TOF_DEFINITION_VERSION,
                "tof_policy_version": TOF_POLICY_VERSION,
                "surface_gate_id": surface_gate.gate_id,
                "bottom_gate_id": bottom_gate.gate_id,
                "gate_calibration_id": gate_calibration_id,
                "surface_peak_sample_index": result.surface_peak_sample_index,
                "bottom_peak_sample_index": result.bottom_peak_sample_index,
                "surface_peak_local_index": result.surface_peak_local_index,
                "bottom_peak_local_index": result.bottom_peak_local_index,
                "surface_envelope_peak_amplitude_a_u": result.surface_peak_amplitude_a_u,
                "bottom_envelope_peak_amplitude_a_u": result.bottom_peak_amplitude_a_u,
                "tof_samples": result.tof_samples,
                "sampling_rate_hz": sampling_rate_hz,
                "tof_s": tof_s,
                "tof_us": result.tof_us,
                "tof_status": result.status,
                "tof_quality_reason": result.quality_reason or result.reason,
                "parameter_set_id": parameter_set_id,
            }
        )
    return pd.DataFrame(rows, columns=CANONICAL_TOF_OUTPUT_COLUMNS)

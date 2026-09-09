"""BRW-017R2 — Canonical envelope-peak TOF series computation.

Thin orchestration over the deterministic envelope_peak_tof function:
reads fs from the effective parameter set (never guessed), applies the
calibrated TOF gate bindings, and computes a per-frame series. Missing fs
keeps sample-domain results and leaves tof_us null. XCorr quantities are
never consumed here and never populate canonical tof_us.
"""

from __future__ import annotations

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

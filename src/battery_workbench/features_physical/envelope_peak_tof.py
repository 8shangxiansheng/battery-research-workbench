"""BRW-017R2 — Canonical Envelope-Peak Surface-to-Bottom TOF (V1).

method_id = SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1

    e[n] = abs(Hilbert(x[n]))
    surface_local = argmax(e[s0:s1]); surface_global = s0 + surface_local
    bottom_local  = argmax(e[b0:b1]); bottom_global = b0 + bottom_local
    tof_samples = bottom_global - surface_global
    tof_us = tof_samples / fs * 1e6

Invariants (task pack §24):
- local peaks are converted to global indices BEFORE subtraction — never
  local-to-local differencing
- bottom_global > surface_global else INVALID (BOTTOM_NOT_AFTER_SURFACE)
- fs must come from the Experiment Parameter Registry — never from
  cadence/sample count/filename; missing fs keeps tof_samples and leaves
  tof_us null (PARTIAL), never fabricated
- pure deterministic function; no I/O, no parameter lookup
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel
from scipy.signal import hilbert

TOF_METHOD_ID = "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
TOF_DEFINITION_VERSION = "0.3.0"
TOF_POLICY_VERSION = "ENVELOPE_PEAK_V1"

STATUS_OK = "OK"
STATUS_BOTTOM_NOT_AFTER_SURFACE = "BOTTOM_NOT_AFTER_SURFACE"
STATUS_SAMPLING_RATE_MISSING = "SAMPLING_RATE_MISSING"
STATUS_SAMPLING_RATE_INVALID = "SAMPLING_RATE_INVALID"
STATUS_INVALID_GATE = "INVALID_GATE"
STATUS_SURFACE_PEAK_AT_GATE_EDGE = "SURFACE_PEAK_AT_GATE_EDGE"
STATUS_BOTTOM_PEAK_AT_GATE_EDGE = "BOTTOM_PEAK_AT_GATE_EDGE"


def hilbert_envelope(waveform: np.ndarray) -> np.ndarray:
    """e[n] = abs(Hilbert(x[n])) — the canonical envelope definition."""
    return np.abs(hilbert(np.asarray(waveform, dtype=np.float64)))


class GateError(ValueError):
    pass


def envelope_peak_in_gate(
    waveform: np.ndarray, start: int, end: int
) -> tuple[int, float]:
    """Argmax of the Hilbert envelope inside [start, end); returns GLOBAL index.

    Raises GateError on invalid bounds. Ties resolve deterministically to the
    first occurrence (numpy argmax semantics, stable across runs).
    """
    x = np.asarray(waveform, dtype=np.float64)
    if start < 0 or end > x.size or start >= end:
        raise GateError(STATUS_INVALID_GATE)
    env = hilbert_envelope(x)
    local = int(np.argmax(env[start:end]))
    return start + local, float(env[start + local])


def _edge_policy_hit(global_index: int, start: int, end: int, margin: int = 2) -> bool:
    """Versioned edge policy: a peak within `margin` samples of a gate edge.

    Reported as a quality reason (edge policy is versioned here); it does NOT
    silently invalidate — no hidden thresholds.
    """
    return global_index < start + margin or global_index >= end - margin


class EnvelopePeakTOFResult(BaseModel):
    status: Literal["VALID", "PARTIAL", "INVALID_FOR_FRAME", "BLOCKED"]
    reason: str
    surface_peak_sample_index: int | None = None
    bottom_peak_sample_index: int | None = None
    surface_peak_amplitude_a_u: float | None = None
    bottom_peak_amplitude_a_u: float | None = None
    surface_peak_local_index: int | None = None
    bottom_peak_local_index: int | None = None
    tof_samples: int | None = None
    sampling_rate_hz: float | None = None
    tof_us: float | None = None
    quality_reason: str = ""


def envelope_peak_tof(
    waveform: np.ndarray,
    surface_start: int,
    surface_end: int,
    bottom_start: int,
    bottom_end: int,
    *,
    sampling_rate_hz: float | None = None,
    edge_margin: int = 2,
) -> EnvelopePeakTOFResult:
    """Canonical envelope-peak surface→bottom TOF for one waveform frame."""
    x = np.asarray(waveform, dtype=np.float64)
    quality: list[str] = []

    if surface_start < 0 or surface_end > x.size or surface_start >= surface_end:
        return EnvelopePeakTOFResult(status="BLOCKED", reason=STATUS_INVALID_GATE)
    if bottom_start < 0 or bottom_end > x.size or bottom_start >= bottom_end:
        return EnvelopePeakTOFResult(status="BLOCKED", reason=STATUS_INVALID_GATE)

    env = hilbert_envelope(x)
    surface_local = int(np.argmax(env[surface_start:surface_end]))
    surface_global = surface_start + surface_local
    s_amp = float(env[surface_global])
    bottom_local = int(np.argmax(env[bottom_start:bottom_end]))
    bottom_global = bottom_start + bottom_local
    b_amp = float(env[bottom_global])

    if _edge_policy_hit(surface_global, surface_start, surface_end, edge_margin):
        quality.append(STATUS_SURFACE_PEAK_AT_GATE_EDGE)
    if _edge_policy_hit(bottom_global, bottom_start, bottom_end, edge_margin):
        quality.append(STATUS_BOTTOM_PEAK_AT_GATE_EDGE)

    if bottom_global <= surface_global:
        return EnvelopePeakTOFResult(
            status="INVALID_FOR_FRAME",
            reason=STATUS_BOTTOM_NOT_AFTER_SURFACE,
            surface_peak_sample_index=surface_global,
            bottom_peak_sample_index=bottom_global,
            surface_peak_amplitude_a_u=s_amp,
            bottom_peak_amplitude_a_u=b_amp,
            surface_peak_local_index=surface_local,
            bottom_peak_local_index=bottom_local,
            quality_reason=";".join(quality),
        )

    tof_samples = bottom_global - surface_global

    if sampling_rate_hz is None:
        return EnvelopePeakTOFResult(
            status="PARTIAL",
            reason=STATUS_SAMPLING_RATE_MISSING,
            surface_peak_sample_index=surface_global,
            bottom_peak_sample_index=bottom_global,
            surface_peak_amplitude_a_u=s_amp,
            bottom_peak_amplitude_a_u=b_amp,
            surface_peak_local_index=surface_local,
            bottom_peak_local_index=bottom_local,
            tof_samples=tof_samples,
            quality_reason=";".join(quality),
        )

    if not np.isfinite(sampling_rate_hz) or sampling_rate_hz <= 0:
        return EnvelopePeakTOFResult(
            status="BLOCKED",
            reason=STATUS_SAMPLING_RATE_INVALID,
            surface_peak_sample_index=surface_global,
            bottom_peak_sample_index=bottom_global,
            surface_peak_amplitude_a_u=s_amp,
            bottom_peak_amplitude_a_u=b_amp,
            surface_peak_local_index=surface_local,
            bottom_peak_local_index=bottom_local,
            tof_samples=tof_samples,
            quality_reason=";".join(quality),
        )

    tof_us = tof_samples / float(sampling_rate_hz) * 1e6
    return EnvelopePeakTOFResult(
        status="VALID",
        reason=STATUS_OK,
        surface_peak_sample_index=surface_global,
        bottom_peak_sample_index=bottom_global,
        surface_peak_amplitude_a_u=s_amp,
        bottom_peak_amplitude_a_u=b_amp,
        surface_peak_local_index=surface_local,
        bottom_peak_local_index=bottom_local,
        tof_samples=tof_samples,
        sampling_rate_hz=float(sampling_rate_hz),
        tof_us=tof_us,
        quality_reason=";".join(quality),
    )

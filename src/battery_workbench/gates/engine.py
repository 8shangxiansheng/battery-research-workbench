"""BRW-018 gate engine: gated feature extraction + between-gate delay.

Reuses the existing BRW-013 feature algorithms on the gate segment. Features
are keyed by ``feature_name + gate_id`` — no new feature names are invented.
Raw waveforms are never modified.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from battery_workbench.features.envelope import compute_envelope_features
from battery_workbench.features.raw_features import compute_raw_amplitude_features
from battery_workbench.gates.schemas import GateSpec, TOFDefinitionSpec

_GATE_STRIP = {
    "waveform_abs_peak_sample_index",
    "envelope_peak_sample_index",
}


def _validate_wave(waveform: np.ndarray, gate: GateSpec) -> None:
    if len(waveform) != gate.waveform_length:
        raise ValueError(
            f"waveform length {len(waveform)} != gate.waveform_length {gate.waveform_length}"
        )


def extract_gated_features(waveform: np.ndarray, gate: GateSpec) -> dict[str, Any]:
    """Apply existing feature algorithms to waveform[start:end]."""
    _validate_wave(waveform, gate)
    segment = np.asarray(waveform)[gate.start_sample : gate.end_sample]
    raw = compute_raw_amplitude_features(segment)
    env = compute_envelope_features(segment)
    feats: dict[str, Any] = {}
    for name, value in {**raw, **env}.items():
        if name in _GATE_STRIP:
            # within-gate indices are relative to the gate, not the waveform
            feats[name] = None if value is None else value + gate.start_sample
            continue
        feats[name] = value
    feats["amplitude_a_u"] = raw["waveform_abs_peak_a_u"]  # user-visible core alias
    feats["gate_id"] = gate.gate_id
    feats["gate_name"] = gate.gate_name
    feats["gate_start_sample"] = gate.start_sample
    feats["gate_end_sample"] = gate.end_sample
    feats["gate_scope"] = gate.scope.value
    return feats


def gate_time_us(gate: GateSpec, *, sampling_rate_hz: float | None) -> dict[str, float | None]:
    """Sample-domain locators stay canonical; time display needs fs."""
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        return {"start_time_us": None, "end_time_us": None}
    scale = 1e6 / sampling_rate_hz
    return {
        "start_time_us": gate.start_sample * scale,
        "end_time_us": gate.end_sample * scale,
    }


def _gate_peak_position(waveform: np.ndarray, gate: GateSpec) -> int:
    """Absolute sample index of |max| inside the gate (first tie wins)."""
    _validate_wave(waveform, gate)
    segment = np.abs(np.asarray(waveform, dtype=float)[gate.start_sample : gate.end_sample])
    return gate.start_sample + int(np.argmax(segment))


def between_gate_delay(
    waveform: np.ndarray, reference_gate: GateSpec, received_gate: GateSpec
) -> int:
    """Between-gate delay in samples: peak(reference) -> peak(received).

    Diagnostic only — never automatically called TOF.
    """
    ref_pos = _gate_peak_position(waveform, reference_gate)
    rcv_pos = _gate_peak_position(waveform, received_gate)
    return rcv_pos - ref_pos


def compute_gate_delay_column(
    *,
    waveform: np.ndarray,
    reference_gate: GateSpec,
    received_gate: GateSpec,
    sampling_rate_hz: float | None,
    physical_interpretation_confirmed: bool = False,
) -> tuple[str, list[float | None], str | None]:
    """One-event delay column; unconfirmed mode never yields tof_us.

    Returns ``(column_name, values, tof_definition_id_or_None)``.
    """
    delay_samples = between_gate_delay(waveform, reference_gate, received_gate)
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        return "delay_samples", [None], None
    delay_us = delay_samples / sampling_rate_hz * 1e6
    if physical_interpretation_confirmed:
        # Promotion is the caller's explicit choice (see promote_tof_column);
        # this function stays in delay semantics regardless.
        return "delay_us", [delay_us], None
    return "delay_us", [delay_us], None


def promote_tof_column(
    *,
    waveform: np.ndarray,
    reference_gate: GateSpec,
    received_gate: GateSpec,
    sampling_rate_hz: float | None,
    tof_definition: TOFDefinitionSpec,
) -> tuple[str, list[float | None]]:
    """Promote a between-gate delay to canonical tof_us.

    Allowed ONLY when the TOFDefinitionSpec explicitly confirms the physical
    interpretation (reference pulse -> received pulse is the studied TOF).
    """
    if (
        tof_definition.mode != "BETWEEN_GATES"
        or not tof_definition.physical_interpretation_confirmed
    ):
        raise ValueError(
            "between-gate delay may only be named tof_us after explicit "
            "physical_interpretation_confirmed=true"
        )
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        return "tof_us", [None]
    delay_samples = between_gate_delay(waveform, reference_gate, received_gate)
    return "tof_us", [delay_samples / sampling_rate_hz * 1e6]


SATURATION_LIMIT = 32000
AUDIT_ROI_MARGIN = 200
EDGE_HIT_TOLERANCE = 2
EDGE_HIT_WARN_RATE = 0.05


def gate_stability_audit(gate: GateSpec, *, waves: np.ndarray) -> dict[str, Any]:
    """Gate stability audit over a stack of waveforms (n x waveform_length).

    peak_inside_gate_rate: does the dominant |max| of the gate's ±200-sample
    ROI sit inside the gate (the global waveform peak would always sit in the
    strongest gate, making the global metric meaningless for weaker gates)?
    """
    _validate_wave(waves[0], gate)
    lo = max(0, gate.start_sample - AUDIT_ROI_MARGIN)
    hi = min(gate.waveform_length, gate.end_sample + AUDIT_ROI_MARGIN)
    roi = np.abs(waves[:, lo:hi])
    roi_peak = lo + np.argmax(roi, axis=1)
    inside = ((roi_peak >= gate.start_sample) & (roi_peak < gate.end_sample)).mean()
    near_edge = (
        (np.abs(roi_peak - gate.start_sample) <= EDGE_HIT_TOLERANCE)
        | (np.abs(roi_peak - (gate.end_sample - 1)) <= EDGE_HIT_TOLERANCE)
    ).mean()
    segments = np.abs(waves[:, gate.start_sample : gate.end_sample])
    full_peaks = np.abs(waves).max(axis=1)
    missing = (segments.max(axis=1) < 0.05 * full_peaks).mean()
    saturation = (
        (waves[:, gate.start_sample : gate.end_sample] >= SATURATION_LIMIT).any(axis=1).mean()
    )
    warnings: list[str] = []
    if near_edge > EDGE_HIT_WARN_RATE:
        warnings.append("GATE_MAY_BE_TOO_NARROW")
    return {
        "gate_id": gate.gate_id,
        "gate_name": gate.gate_name,
        "bounds": [gate.start_sample, gate.end_sample],
        "peak_inside_gate_rate": round(float(inside), 4),
        "edge_hit_rate": round(float(near_edge), 4),
        "missing_signal_rate": round(float(missing), 4),
        "saturation_rate": round(float(saturation), 4),
        "warnings": warnings,
    }

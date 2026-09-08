"""BRW-013X V2.1 — Source-backed physical / gate-local features.

Direct translation of user-supplied MATLAB snippets (source_formula_id
USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1):

1. Bottom-wave Amplitude  — MATLAB gate 750:1100, Hilbert envelope max
2. Surface Wave Amplitude — MATLAB gate 90:200, Hilbert envelope max
3. Surface–Bottom XCorr TOF — ref 60:260, bottom 750:1200, full xcorr,
   peak of abs(r), tof_samples = length(y) - peak_idx(1-based)
4. Bottom-wave Attenuation — gate 750:1150: env max/mean/energy, half-width;
   feature 5 (1–10 MHz energy) stays SOURCE_FORMULA_INCOMPLETE
5. BPS — gate 750:1150, fixed first-frame reference, Hilbert phase
   difference, unwrap, region mean, movmean5

All series are computed in canonical source frame order; movmean5 is
MATLAB-centered with shrinking endpoints and is EXPLORATORY by default
(predictor_eligible=false, see smoothing leakage policy).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel
from scipy.signal import correlate, correlation_lags, hilbert

SOURCE_FORMULA_ID = "USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1"
METHOD_BOTTOM_AMP = "BOTTOM_WAVE_AMPLITUDE_ENVELOPE_MAX_V1"
METHOD_SWA = "SURFACE_WAVE_AMPLITUDE_ENVELOPE_MAX_V1"
METHOD_TOF_XCORR = "SURFACE_BOTTOM_XCORR_LAG_V1"
METHOD_ATTENUATION = "BOTTOM_WAVE_ATTENUATION_SOURCE_V1"
METHOD_BPS = "BOTTOM_WAVE_HILBERT_MEAN_PHASE_SHIFT_V1"
METHOD_MOVMEAN = "MOVMEAN_5_SOURCE_ORDER_V1"


class GateTemplateDefinition(BaseModel):
    """Source gate template with exact MATLAB→Python index provenance."""

    gate_template_id: str
    role_en: str
    role_zh: str
    matlab_start: int
    matlab_end: int
    python_start: int
    python_end_exclusive: int
    length_samples: int

    def source_indices(self) -> dict[str, int]:
        return {
            "matlab_start_1based_inclusive": self.matlab_start,
            "matlab_end_1based_inclusive": self.matlab_end,
            "python_start_0based": self.python_start,
            "python_end_exclusive": self.python_end_exclusive,
        }


#: Canonical templates from task pack 26_GATE_TEMPLATE_DEFINITIONS.yaml.
#: universal=false — these windows are battery/probe/configuration dependent
#: and REQUIRE recalibration for a new configuration (GateCalibrationRecord).
GATE_TEMPLATES: tuple[GateTemplateDefinition, ...] = (
    GateTemplateDefinition(
        gate_template_id="BOTTOM_AMPLITUDE_GATE", role_en="Bottom-wave amplitude",
        role_zh="底波幅值", matlab_start=750, matlab_end=1100,
        python_start=749, python_end_exclusive=1100, length_samples=351,
    ),
    GateTemplateDefinition(
        gate_template_id="SWA_SURFACE_GATE", role_en="Surface wave amplitude",
        role_zh="表面波幅值", matlab_start=90, matlab_end=200,
        python_start=89, python_end_exclusive=200, length_samples=111,
    ),
    GateTemplateDefinition(
        gate_template_id="TOF_SURFACE_REFERENCE_GATE", role_en="TOF surface reference",
        role_zh="TOF表面波参考", matlab_start=60, matlab_end=260,
        python_start=59, python_end_exclusive=260, length_samples=201,
    ),
    GateTemplateDefinition(
        gate_template_id="TOF_BOTTOM_GATE", role_en="TOF bottom wave",
        role_zh="TOF底波", matlab_start=750, matlab_end=1200,
        python_start=749, python_end_exclusive=1200, length_samples=451,
    ),
    GateTemplateDefinition(
        gate_template_id="ATTENUATION_BOTTOM_GATE", role_en="Bottom-wave attenuation",
        role_zh="底波衰减", matlab_start=750, matlab_end=1150,
        python_start=749, python_end_exclusive=1150, length_samples=401,
    ),
    GateTemplateDefinition(
        gate_template_id="BPS_BOTTOM_GATE", role_en="Bottom-wave phase shift",
        role_zh="底波相移", matlab_start=750, matlab_end=1150,
        python_start=749, python_end_exclusive=1150, length_samples=401,
    ),
)

_TEMPLATE_INDEX = {t.gate_template_id: t for t in GATE_TEMPLATES}


def get_gate_template(gate_template_id: str) -> GateTemplateDefinition:
    return _TEMPLATE_INDEX[gate_template_id]


def matlab_gate(
    data: np.ndarray, template: GateTemplateDefinition, *, frame_index: int | None = None
) -> np.ndarray:
    """Slice one frame's gate using the template's exact Python bounds."""
    a = np.asarray(data, dtype=np.float64)
    row = a if a.ndim == 1 else a[frame_index if frame_index is not None else 0]
    return row[template.python_start : template.python_end_exclusive]


def matlab_movmean5(values) -> np.ndarray:
    """MATLAB movmean(x,5): centered window, shrink endpoints, NaN propagates."""
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    out = np.empty_like(v)
    for i in range(v.size):
        lo = max(0, i - 2)
        hi = min(v.size, i + 3)
        out[i] = np.mean(v[lo:hi])
    return out


def _envelope_max_series(a: np.ndarray, template: GateTemplateDefinition) -> np.ndarray:
    """|hilbert(gate)| max per frame, frames on axis 0."""
    gate = np.asarray(a, dtype=np.float64)[:, template.python_start : template.python_end_exclusive]
    env = np.abs(hilbert(gate, axis=1))
    return np.max(env, axis=1)


def bottom_wave_amplitude(frames: np.ndarray) -> dict[str, Any]:
    """Feature 1 — Bottom-wave Amplitude / 底波幅值 (MATLAB 750:1100)."""
    t = get_gate_template("BOTTOM_AMPLITUDE_GATE")
    raw = _envelope_max_series(frames, t)
    return {
        "feature_code": "BOTTOM_AMP",
        "method": METHOD_BOTTOM_AMP,
        "gate_template_id": t.gate_template_id,
        "raw": raw,
        "smoothed_movmean5": matlab_movmean5(raw),
        "smoothed_method": METHOD_MOVMEAN,
    }


def surface_wave_amplitude(frames: np.ndarray) -> dict[str, Any]:
    """Feature 2 — SWA / 表面波幅值 (MATLAB 90:200). Valid only when the
    surface-wave gate role is confirmed by calibration."""
    t = get_gate_template("SWA_SURFACE_GATE")
    raw = _envelope_max_series(frames, t)
    return {
        "feature_code": "SWA",
        "method": METHOD_SWA,
        "gate_template_id": t.gate_template_id,
        "raw": raw,
        "smoothed_movmean5": matlab_movmean5(raw),
        "smoothed_method": METHOD_MOVMEAN,
    }


def surface_bottom_xcorr_tof(frames: np.ndarray) -> dict[str, Any]:
    """Feature 3 — Surface–Bottom XCorr TOF / 表面波-底波互相关TOF.

    Exact source semantics:
      r = xcorr(x, y)   (full, unnormalized; x=ref 60:260, y=bottom 750:1200)
      peak_idx = first max(abs(r)), 1-based
      tof_samples = length(y) - peak_idx
    Adopted convention assert: tof_samples = -lag_samples.
    Physical time (tof_us) requires sampling rate — null without it.
    """
    a = np.asarray(frames, dtype=np.float64)
    t_ref = get_gate_template("TOF_SURFACE_REFERENCE_GATE")
    t_bot = get_gate_template("TOF_BOTTOM_GATE")
    surface = a[:, t_ref.python_start : t_ref.python_end_exclusive]
    bottom = a[:, t_bot.python_start : t_bot.python_end_exclusive]

    lags = correlation_lags(t_ref.length_samples, t_bot.length_samples, mode="full")
    tof = np.empty(a.shape[0], dtype=np.int64)
    peak_idx0 = np.empty(a.shape[0], dtype=np.int64)
    lag_samples = np.empty(a.shape[0], dtype=np.int64)

    for i in range(a.shape[0]):
        r = correlate(surface[i], bottom[i], mode="full", method="direct")
        p0 = int(np.argmax(np.abs(r)))  # first max (argmax returns first)
        peak_idx_matlab = p0 + 1
        tof[i] = t_bot.length_samples - peak_idx_matlab
        lag_samples[i] = int(lags[p0])
        peak_idx0[i] = p0
        assert tof[i] == -lag_samples[i], "lag convention mismatch"

    return {
        "feature_code": "TOF_XCORR",
        "method": METHOD_TOF_XCORR,
        "gate_templates": [t_ref.gate_template_id, t_bot.gate_template_id],
        "tof_samples": tof,
        "correlation_peak_index_zero_based": peak_idx0,
        "correlation_lag_samples": lag_samples,
        "tof_us": None,  # requires sampling rate; never fabricated
    }


def tof_samples_to_us(tof_samples: np.ndarray, sampling_rate_hz: float) -> np.ndarray:
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        raise ValueError("A positive sampling_rate_hz is required")
    return np.asarray(tof_samples, dtype=np.float64) / float(sampling_rate_hz) * 1e6


def bottom_attenuation_explicit(
    frames: np.ndarray, sampling_rate_hz: float | None = None
) -> dict[str, Any]:
    """Feature 4 — Bottom-wave attenuation features 1–4 (gate 750:1150).

    Feature 5 (1–10 MHz energy) is BLOCKED: the supplied MATLAB
    `freq_energy = ...` line is truncated — SOURCE_FORMULA_INCOMPLETE,
    never inferred. Spectral intermediates (nfft=1024, one-sided |fft|,
    f=fs*k/nfft, band mask 1–10 MHz inclusive) are computed only when
    sampling rate is available, for future recovery of the exact line.
    """
    a = np.asarray(frames, dtype=np.float64)
    t = get_gate_template("ATTENUATION_BOTTOM_GATE")
    gate = a[:, t.python_start : t.python_end_exclusive]

    n = gate.shape[0]
    amp_max = np.empty(n)
    amp_mean = np.empty(n)
    amp_energy = np.empty(n)
    width_half = np.empty(n, dtype=np.int64)

    for i in range(n):
        signal = gate[i]
        env = np.abs(hilbert(signal))
        mx = float(np.max(env))
        amp_max[i] = mx
        amp_mean[i] = float(np.mean(env))
        amp_energy[i] = float(np.sum(env**2))
        idx = np.flatnonzero(env >= mx * 0.5)
        if idx.size == 0:
            raise ValueError("Half-height region is empty")
        width_half[i] = int(idx[-1] - idx[0] + 1)

    spectral: dict[str, Any] | None = None
    if sampling_rate_hz is not None:
        if sampling_rate_hz <= 0:
            raise ValueError("sampling_rate_hz must be positive")
        fs = float(sampling_rate_hz)
        nfft = 1024
        y_full = np.abs(np.fft.fft(gate, n=nfft, axis=1))
        y_one = y_full[:, : nfft // 2 + 1]
        f = fs * np.arange(nfft // 2 + 1, dtype=np.float64) / nfft
        band_mask = (f >= 1e6) & (f <= 10e6)
        spectral = {
            "nfft": nfft,
            "frequency_hz": f,
            "band_mask_1_10mhz": band_mask,
            "magnitude_one_sided": y_one,
            "frequency_energy": None,  # SOURCE_FORMULA_INCOMPLETE
        }

    return {
        "feature_code": "ATTENUATION",
        "method": METHOD_ATTENUATION,
        "gate_template_id": t.gate_template_id,
        "amp_max": amp_max,
        "amp_mean": amp_mean,
        "amp_energy": amp_energy,
        "width_half_samples": width_half,
        "hf_band_energy": None,
        "hf_band_status": "SOURCE_FORMULA_INCOMPLETE",
        "spectral_intermediates": spectral,
    }


def bottom_wave_phase_shift(frames: np.ndarray) -> dict[str, Any]:
    """Feature 5 — BPS / 底波相移 (gate 750:1150, METHOD_BOTTOM_WAVE_HILBERT_MEAN_PHASE_SHIFT_V1).

    Reference = the FIRST source frame (frozen, persisted, never reselected
    per analysis slice). raw = mean(unwrap(curr_phase - ref_phase)) per frame;
    smoothed = movmean5 in canonical source frame order (never resmoothed on
    a filtered subset).
    """
    a = np.asarray(frames, dtype=np.float64)
    t = get_gate_template("BPS_BOTTOM_GATE")
    gate = a[:, t.python_start : t.python_end_exclusive]

    ref_phase = np.angle(hilbert(gate[0]))
    raw = np.empty(gate.shape[0])
    for i in range(gate.shape[0]):
        delta = np.unwrap(np.angle(hilbert(gate[i])) - ref_phase)
        raw[i] = float(np.mean(delta))

    return {
        "feature_code": "BPS",
        "method": METHOD_BPS,
        "gate_template_id": t.gate_template_id,
        "reference_frame_index": 0,
        "raw_radian": raw,
        "smoothed_movmean5_radian": matlab_movmean5(raw),
        "smoothed_method": METHOD_MOVMEAN,
        "unit": "radian",
    }

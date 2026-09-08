"""BRW-013X V2 — Spectral Transform Definition + Full-wave/Gated extraction.

The FD feature formulas define statistics over (f, y) but NOT how y is
produced. SpectralTransformDefinition makes the spectrum representation
explicit and versioned — no default may be inferred from feature names.

Scope handling:
- FULL_WAVEFORM: statistics over the entire waveform sample index
- USER_SELECTED_EXPLICIT_GATE: statistics over an explicit gate slice;
  the FeatureLocator carries the gate_id so the same feature code on
  different gates is a different feature identity.

Numerical statuses follow the Numerical Status Policy (no silent zero
substitution for invalid values).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel

from battery_workbench.features.matlab_features import (
    FD_CODES,
    TD_CODES,
    compute_frequency_domain,
    compute_time_domain,
)

FULL_WAVEFORM = "FULL_WAVEFORM"

SpectralRepresentation = Literal["MAGNITUDE", "POWER", "PSD", "OTHER_EXPLICIT"]

NumericalStatus = Literal[
    "VALID",
    "MATLAB_PARITY_BLOCKED",
    "INVALID_ZERO_STD",
    "INVALID_SPECTRAL_WEIGHT",
    "INVALID_NEGATIVE_SPECTRAL_WEIGHT",
    "MISSING_SAMPLING_RATE",
    "MISSING_SPECTRAL_TRANSFORM",
    "NUMERICAL_NAN",
    "NUMERICAL_INF",
]


class SpectralTransformDefinition(BaseModel):
    """Explicit, versioned definition of how spectrum (f, y) is produced.

    Contract §08: no default may be inferred from feature names.
    """

    spectral_transform_id: str
    version: str = "1.0.0"
    input_scope: str = FULL_WAVEFORM
    gate_id: str | None = None
    sampling_rate_parameter_id: str | None = None
    remove_dc: bool = True
    window: str | None = None  # e.g. "hann"; None = rectangular
    fft_length: int | None = None
    one_sided: bool = True
    spectral_representation: SpectralRepresentation = "MAGNITUDE"
    normalization: str = "none"
    frequency_units: str = "Hz"

    def transform_id(self) -> str:
        return f"{self.spectral_transform_id}@{self.version}"


def gate_slice(
    waveform: np.ndarray,
    *,
    gate_id: str | None = None,
    python_start: int | None = None,
    python_end_exclusive: int | None = None,
) -> np.ndarray:
    """Slice an explicit gate (0-based half-open) or return the full waveform.

    A gate outside waveform bounds raises — silent truncation is forbidden.
    """
    x = np.asarray(waveform, dtype=np.float64)
    if gate_id is None:
        return x
    if python_start is None or python_end_exclusive is None:
        raise ValueError(f"gate {gate_id}: explicit bounds required")
    if python_start < 0 or python_end_exclusive > x.size or python_start >= python_end_exclusive:
        raise ValueError(
            f"gate {gate_id}: bounds [{python_start}, {python_end_exclusive}) "
            f"invalid for waveform of length {x.size}"
        )
    return x[python_start:python_end_exclusive]


def spectrum_from_waveform(
    x: np.ndarray,
    transform: SpectralTransformDefinition,
    *,
    sampling_rate_hz: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Produce (f, y) per the explicit SpectralTransformDefinition.

    Returns raw spectrum values WITHOUT any abs() coercion of negative
    weights and without frequency normalization — the formulas keep the
    source semantics.
    """
    if transform.sampling_rate_parameter_id and sampling_rate_hz is None:
        raise ValueError(
            f"MISSING_SAMPLING_RATE: parameter "
            f"{transform.sampling_rate_parameter_id} required for frequency axis"
        )

    sig = np.asarray(x, dtype=np.float64)
    if transform.remove_dc and sig.size > 0:
        sig = sig - np.mean(sig)

    if transform.window is not None:
        if transform.window == "hann":
            w = np.hanning(sig.size)
        elif transform.window == "hamming":
            w = np.hamming(sig.size)
        else:
            raise ValueError(f"unsupported window: {transform.window}")
        sig = sig * w

    nfft = transform.fft_length or sig.size
    spec_full = np.fft.fft(sig, n=nfft)

    if transform.one_sided:
        n_bins = nfft // 2 + 1
        spec = spec_full[:n_bins]
    else:
        spec = spec_full

    if transform.spectral_representation == "MAGNITUDE":
        y = np.abs(spec)
    elif transform.spectral_representation == "POWER":
        y = np.abs(spec) ** 2
    elif transform.spectral_representation == "PSD":
        y = np.abs(spec) ** 2
        if sampling_rate_hz is not None and sampling_rate_hz > 0:
            y = y / (sampling_rate_hz * nfft)
    else:
        raise ValueError(
            "OTHER_EXPLICIT requires a custom producer; refusing to guess y semantics"
        )

    if transform.one_sided and nfft % 2 == 0 and spec.size > 1:
        # do not double-count: this definition does not scale interior bins
        pass

    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        f = np.arange(spec.size, dtype=np.float64)
    else:
        f = (
            np.arange(spec.size, dtype=np.float64)
            * float(sampling_rate_hz)
            / float(nfft)
        )

    return f, y


def _fd_status(y: np.ndarray, vals: dict[str, float]) -> list[str]:
    """Numerical status policy for FD block."""
    statuses: list[str] = []
    if np.any(y < 0):
        statuses.append("INVALID_NEGATIVE_SPECTRAL_WEIGHT")
    if float(np.sum(y)) <= 0:
        statuses.append("INVALID_SPECTRAL_WEIGHT")
    if any(np.isnan(v) for v in vals.values()):
        statuses.append("NUMERICAL_NAN")
    if any(np.isinf(v) for v in vals.values()):
        statuses.append("NUMERICAL_INF")
    return statuses or ["VALID"]


def _td_status(x: np.ndarray, vals: dict[str, float]) -> list[str]:
    statuses: list[str] = []
    if float(np.std(x)) == 0.0:
        statuses.append("INVALID_ZERO_STD")
    if any(np.isnan(v) for v in vals.values()):
        statuses.append("NUMERICAL_NAN")
    if any(np.isinf(v) for v in vals.values()):
        statuses.append("NUMERICAL_INF")
    return statuses or ["VALID"]


class FeatureExtractionBlock(BaseModel):
    """One code×scope×gate extraction outcome (typed, honest statuses)."""

    code: str
    scope: str
    gate_id: str | None = None
    value: float | None
    statuses: list[str]
    spectral_transform_id: str | None = None


def extract_td_block(
    waveform: np.ndarray,
    *,
    scope: str = FULL_WAVEFORM,
    gate_id: str | None = None,
    python_start: int | None = None,
    python_end_exclusive: int | None = None,
) -> list[FeatureExtractionBlock]:
    """19 TD features over full waveform or an explicit gate slice."""
    x = gate_slice(
        waveform,
        gate_id=gate_id,
        python_start=python_start,
        python_end_exclusive=python_end_exclusive,
    )
    vals = compute_time_domain(x)
    statuses = _td_status(x, vals)
    return [
        FeatureExtractionBlock(
            code=code,
            scope=scope,
            gate_id=gate_id,
            value=vals[code],
            statuses=list(statuses),
        )
        for code in TD_CODES
    ]


def extract_fd_block(
    waveform: np.ndarray,
    transform: SpectralTransformDefinition,
    *,
    scope: str = FULL_WAVEFORM,
    gate_id: str | None = None,
    python_start: int | None = None,
    python_end_exclusive: int | None = None,
    sampling_rate_hz: float | None = None,
) -> list[FeatureExtractionBlock]:
    """14 FD features over the spectrum of full waveform or an explicit gate."""
    x = gate_slice(
        waveform,
        gate_id=gate_id,
        python_start=python_start,
        python_end_exclusive=python_end_exclusive,
    )
    f, y = spectrum_from_waveform(x, transform, sampling_rate_hz=sampling_rate_hz)
    vals = compute_frequency_domain(f, y)
    statuses = _fd_status(y, vals)
    if transform.sampling_rate_parameter_id and sampling_rate_hz is None:
        statuses = ["MISSING_SAMPLING_RATE"]
    return [
        FeatureExtractionBlock(
            code=code,
            scope=scope,
            gate_id=gate_id,
            value=vals[code],
            statuses=list(statuses),
            spectral_transform_id=transform.transform_id(),
        )
        for code in FD_CODES
    ]

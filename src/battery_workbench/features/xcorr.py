"""Relative cross-correlation features for a waveform vs a per-asset reference.

Lag sign convention (frozen, tested): using ``scipy.signal.correlate(current,
reference)`` with ``correlation_lags``, a **positive** ``xcorr_shift_samples``
means the current waveform is shifted toward **larger** sample indices relative
to the reference (i.e. appears later / delayed); a negative lag means smaller
indices (earlier). The reference itself yields shift=0 and coefficient≈1.

Only mean-centering is applied — no filtering, alignment, or resampling.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import correlate, correlation_lags


def compute_relative_xcorr_features(waveform: np.ndarray, reference: np.ndarray) -> dict:
    """Compute relative xcorr lag + normalized peak coefficient.

    Returns ``xcorr_shift_samples``, ``xcorr_peak_coefficient``, and
    ``xcorr_warning`` (None when healthy). Zero denominator or nonfinite input
    yields null shift/coefficient with a warning.
    """
    x = np.asarray(waveform, dtype=np.float64)
    r = np.asarray(reference, dtype=np.float64)
    if x.size == 0 or r.size == 0 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(r)):
        return {
            "xcorr_shift_samples": None,
            "xcorr_peak_coefficient": None,
            "xcorr_warning": "non-finite or empty waveform/reference",
        }

    x0 = x - x.mean()
    r0 = r - r.mean()

    denom = np.sqrt(np.sum(x0 * x0) * np.sum(r0 * r0))
    if denom == 0.0:
        return {
            "xcorr_shift_samples": None,
            "xcorr_peak_coefficient": None,
            "xcorr_warning": "constant waveform/reference (zero denominator)",
        }

    corr = correlate(x0, r0, mode="full", method="direct")
    lags = correlation_lags(len(x0), len(r0), mode="full")
    peak_index = int(np.argmax(np.abs(corr)))
    shift = int(lags[peak_index])
    coefficient = float(corr[peak_index] / denom)

    return {
        "xcorr_shift_samples": shift,
        "xcorr_peak_coefficient": coefficient,
        "xcorr_warning": None,
    }

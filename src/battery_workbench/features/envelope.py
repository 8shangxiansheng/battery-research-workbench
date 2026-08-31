"""Hilbert envelope features for a single waveform (Sample-Domain V1).

Uses the raw analytic signal magnitude: no smoothing, filtering, windowing,
prominence filtering, or time conversion.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert


def compute_envelope_features(waveform: np.ndarray) -> dict:
    """Compute raw Hilbert envelope peak + index for one waveform.

    Returns ``envelope_peak_a_u`` and ``envelope_peak_sample_index``. Non-finite
    waveforms yield ``None`` values.
    """
    x = np.asarray(waveform, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        return {"envelope_peak_a_u": None, "envelope_peak_sample_index": None}
    envelope = np.abs(hilbert(x))
    return {
        "envelope_peak_a_u": float(envelope.max()),
        "envelope_peak_sample_index": int(np.argmax(envelope)),  # first tie
    }

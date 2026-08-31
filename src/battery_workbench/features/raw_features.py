"""Raw amplitude features for a single waveform (Sample-Domain V1).

All numeric calculations are performed in float64 (before squaring) to avoid
integer overflow when the input is int32. ``abs_peak_sample_index`` is the
first argmax (leftmost tie wins). No filtering, no frequency, no time.
"""

from __future__ import annotations

import numpy as np


def compute_raw_amplitude_features(waveform: np.ndarray) -> dict:
    """Compute raw amplitude features for one waveform.

    Returns a dict of feature-name -> value. Values are ``None`` for
    non-finite waveforms so the row can be preserved downstream.
    """
    x = np.asarray(waveform, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        return {
            "waveform_min_a_u": None,
            "waveform_max_a_u": None,
            "waveform_mean_a_u": None,
            "waveform_std_a_u": None,
            "waveform_rms_a_u": None,
            "waveform_p2p_a_u": None,
            "waveform_abs_peak_a_u": None,
            "waveform_abs_peak_sample_index": None,
            "waveform_energy_sum_sq_a_u2": None,
        }
    x2 = x * x
    abs_x = np.abs(x)
    return {
        "waveform_min_a_u": float(x.min()),
        "waveform_max_a_u": float(x.max()),
        "waveform_mean_a_u": float(x.mean()),
        "waveform_std_a_u": float(x.std(ddof=0)),
        "waveform_rms_a_u": float(np.sqrt(x2.mean())),
        "waveform_p2p_a_u": float(x.max() - x.min()),
        "waveform_abs_peak_a_u": float(abs_x.max()),
        "waveform_abs_peak_sample_index": int(np.argmax(abs_x)),  # first tie
        "waveform_energy_sum_sq_a_u2": float(x2.sum()),
    }

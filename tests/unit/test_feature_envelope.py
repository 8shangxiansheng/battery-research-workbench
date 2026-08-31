from __future__ import annotations

import numpy as np
import pytest

from battery_workbench.features.envelope import compute_envelope_features


def test_envelope_peak_t10() -> None:
    """Envelope peak equals max |hilbert(x)|."""
    w = np.array([0.0, 1.0, 0.0, -1.0, 0.0], dtype=np.float64)
    f = compute_envelope_features(w)
    # Analytic envelope of a narrow signal; peak must be >= max abs.
    assert f["envelope_peak_a_u"] == pytest.approx(
        np.max(np.abs(__import__("scipy.signal", fromlist=["hilbert"]).hilbert(w))), rel=1e-9
    )


def test_envelope_peak_index_t11() -> None:
    w = np.array([0.0, 2.0, 0.0, -1.0, 0.0], dtype=np.float64)
    f = compute_envelope_features(w)
    env = np.abs(__import__("scipy.signal", fromlist=["hilbert"]).hilbert(w))
    assert f["envelope_peak_sample_index"] == int(np.argmax(env))


def test_no_smoothing_t12() -> None:
    """Envelope must not be smoothed/filtered — raw Hilbert magnitude only."""
    w = np.array([0.0, 5.0, 0.0, -5.0, 0.0], dtype=np.float64)
    f = compute_envelope_features(w)
    env = np.abs(__import__("scipy.signal", fromlist=["hilbert"]).hilbert(w))
    # Exact peak equals the analytic magnitude, no windowing.
    assert f["envelope_peak_a_u"] == pytest.approx(env.max())
    # No extra features beyond peak + index.
    assert set(f.keys()) == {"envelope_peak_a_u", "envelope_peak_sample_index"}

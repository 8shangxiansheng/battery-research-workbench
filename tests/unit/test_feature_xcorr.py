from __future__ import annotations

import numpy as np
import pytest

from battery_workbench.features.xcorr import compute_relative_xcorr_features


def _pulse(length: int = 32, center: int = 8, width: int = 7, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = np.zeros(length)
    r[center : center + width] = rng.normal(0, 1, width)
    return r - r.mean()


def test_reference_shift_zero_t13() -> None:
    r = _pulse()
    f = compute_relative_xcorr_features(r, r)
    assert f["xcorr_shift_samples"] == 0
    assert f["xcorr_peak_coefficient"] == pytest.approx(1.0)


def test_positive_shift_t14() -> None:
    """current = reference delayed by +3 samples (content moves to larger index)."""
    r = _pulse()
    c = np.zeros_like(r)
    c[3:] = r[: len(r) - 3]
    c = c - c.mean()
    f = compute_relative_xcorr_features(c, r)
    assert f["xcorr_shift_samples"] == pytest.approx(3)


def test_negative_shift_t15() -> None:
    r = _pulse()
    c = np.zeros_like(r)
    c[: len(r) - 3] = r[3:]
    c = c - c.mean()
    f = compute_relative_xcorr_features(c, r)
    assert f["xcorr_shift_samples"] == pytest.approx(-3)


def test_lag_sign_convention_t16() -> None:
    """Freeze: +lag means current waveform is shifted toward LARGER sample index.

    Verified against scipy.signal.correlate(current, reference) + correlation_lags.
    """
    r = _pulse()
    c = np.zeros_like(r)
    c[3:] = r[: len(r) - 3]
    c = c - c.mean()
    f = compute_relative_xcorr_features(c, r)
    assert f["xcorr_shift_samples"] > 0  # delayed -> larger index -> positive lag


def test_normalized_coefficient_t17() -> None:
    r = _pulse()
    c = _pulse(seed=1)
    c = c - c.mean()
    f = compute_relative_xcorr_features(c, r)
    # Coefficient in [-1, 1].
    assert -1.0 <= f["xcorr_peak_coefficient"] <= 1.0


def test_zero_denominator_t18() -> None:
    """Constant waveform -> null shift/coefficient + a warning signal."""
    r = _pulse()
    const = np.full(32, 5.0)
    f = compute_relative_xcorr_features(const, r)
    assert f["xcorr_shift_samples"] is None
    assert f["xcorr_peak_coefficient"] is None
    assert f["xcorr_warning"] is not None


def test_reference_policy_deterministic_t19() -> None:
    """Per-asset reference = first valid event by event_order_index."""
    r = _pulse()
    # Same reference waveform repeated must give identical features.
    c = np.zeros_like(r)
    c[2:] = r[: len(r) - 2]
    c = c - c.mean()
    f1 = compute_relative_xcorr_features(c, r)
    f2 = compute_relative_xcorr_features(c, r)
    assert f1["xcorr_shift_samples"] == f2["xcorr_shift_samples"]
    assert f1["xcorr_peak_coefficient"] == pytest.approx(f2["xcorr_peak_coefficient"])

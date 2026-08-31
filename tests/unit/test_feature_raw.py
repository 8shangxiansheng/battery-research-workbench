from __future__ import annotations

import numpy as np
import pytest

from battery_workbench.features.raw_features import compute_raw_amplitude_features


def test_min_max_t01() -> None:
    w = np.array([-5.0, 0.0, 3.0, 10.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_min_a_u"] == -5.0
    assert f["waveform_max_a_u"] == 10.0


def test_mean_t02() -> None:
    w = np.array([1.0, 2.0, 3.0, 4.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_mean_a_u"] == 2.5


def test_std_ddof0_t03() -> None:
    w = np.array([1.0, 2.0, 3.0, 4.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_std_a_u"] == pytest.approx(np.std(w, ddof=0))


def test_rms_t04() -> None:
    w = np.array([1.0, 2.0, 3.0, 4.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_rms_a_u"] == pytest.approx(np.sqrt(np.mean(w**2)))


def test_p2p_t05() -> None:
    w = np.array([-5.0, 10.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_p2p_a_u"] == 15.0


def test_abs_peak_t06() -> None:
    w = np.array([-7.0, 3.0, 4.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_abs_peak_a_u"] == 7.0


def test_abs_peak_first_tie_index_t07() -> None:
    w = np.array([-7.0, 3.0, -7.0, 2.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_abs_peak_sample_index"] == 0  # first tie wins


def test_energy_t08() -> None:
    w = np.array([1.0, 2.0, 3.0, 4.0])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_energy_sum_sq_a_u2"] == pytest.approx(np.sum(w**2))


def test_int_overflow_guard_t09() -> None:
    """int32 input must be cast to float64 before squaring to avoid overflow."""
    w = np.array([30000, 30000, 30000, 30000], dtype=np.int32)
    f = compute_raw_amplitude_features(w)
    # int32 30000^2 = 9e8 fits in int32, but sum of 4 * 9e8 = 3.6e9 overflows int32.
    assert f["waveform_energy_sum_sq_a_u2"] == pytest.approx(4 * 30000.0**2)
    assert f["waveform_rms_a_u"] == pytest.approx(30000.0)


def test_float64_calc_t06b() -> None:
    # Tiny fractional values must not be truncated by integer math.
    w = np.array([0.5, -0.5, 0.5])
    f = compute_raw_amplitude_features(w)
    assert f["waveform_mean_a_u"] == pytest.approx(1 / 6)

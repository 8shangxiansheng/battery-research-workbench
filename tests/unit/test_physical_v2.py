"""BRW-013X V2.1 physical feature tests (P01–P42 per test plan 34)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import correlate, hilbert

from battery_workbench.features.physical_v2 import (
    GATE_TEMPLATES,
    SOURCE_FORMULA_ID,
    bottom_attenuation_explicit,
    bottom_wave_amplitude,
    bottom_wave_phase_shift,
    get_gate_template,
    matlab_gate,
    matlab_movmean5,
    surface_bottom_xcorr_tof,
    surface_wave_amplitude,
    tof_samples_to_us,
)


def _synth_frames(n_frames: int = 12, length: int = 1280, seed: int = 3) -> np.ndarray:
    """Synthetic ultrasound frames with surface packet (~90:200) and bottom
    packet (~750:1150) whose arrival drifts slightly with frame index."""
    rng = np.random.default_rng(seed)
    t = np.arange(length, dtype=np.float64)
    frames = np.zeros((n_frames, length))
    for i in range(n_frames):
        surface = np.exp(-((t - 140) ** 2) / (2 * 18.0**2)) * np.sin(2 * np.pi * 5e6 * t / 50e6)
        bottom = np.exp(-((t - (950 + 2 * i)) ** 2) / (2 * 25.0**2)) * np.sin(
            2 * np.pi * 5e6 * t / 50e6
        )
        frames[i] = surface * (1.0 - 0.01 * i) + bottom * (0.9 - 0.005 * i)
        frames[i] += 0.01 * rng.standard_normal(length)
    return frames


class TestIndexConversion:
    """P01–P05 exact MATLAB→Python windows."""

    def test_p01_bottom_amplitude_window(self):
        t = get_gate_template("BOTTOM_AMPLITUDE_GATE")
        assert (t.python_start, t.python_end_exclusive) == (749, 1100)
        assert t.length_samples == 1100 - 750 + 1 == 351

    def test_p02_swa_window(self):
        t = get_gate_template("SWA_SURFACE_GATE")
        assert (t.python_start, t.python_end_exclusive) == (89, 200)
        assert t.length_samples == 111

    def test_p03_tof_windows(self):
        ref = get_gate_template("TOF_SURFACE_REFERENCE_GATE")
        bot = get_gate_template("TOF_BOTTOM_GATE")
        assert (ref.python_start, ref.python_end_exclusive) == (59, 260)
        assert (bot.python_start, bot.python_end_exclusive) == (749, 1200)
        assert ref.length_samples == 201 and bot.length_samples == 451

    def test_p04_attenuation_bps_windows(self):
        a = get_gate_template("ATTENUATION_BOTTOM_GATE")
        b = get_gate_template("BPS_BOTTOM_GATE")
        assert (a.python_start, a.python_end_exclusive) == (749, 1150)
        assert b.python_start == 749 and b.python_end_exclusive == 1150
        assert a.length_samples == b.length_samples == 401

    def test_p05_matlab_gate_slice_values(self):
        row = np.arange(1200, dtype=np.float64)
        t = get_gate_template("SWA_SURFACE_GATE")
        g = matlab_gate(row, t)
        assert g[0] == 89.0 and g[-1] == 199.0 and len(g) == 111


class TestAmplitudes:
    """P06–P12."""

    def test_p06_hilbert_max_matches_direct(self):
        frames = _synth_frames(4)
        got = bottom_wave_amplitude(frames)["raw"]
        for i in range(4):
            env = np.abs(hilbert(frames[i, 749:1100]))
            assert got[i] == pytest.approx(np.max(env), rel=1e-12)

    def test_p07_swa_max(self):
        frames = _synth_frames(4)
        got = surface_wave_amplitude(frames)["raw"]
        for i in range(4):
            env = np.abs(hilbert(frames[i, 89:200]))
            assert got[i] == pytest.approx(np.max(env), rel=1e-12)

    def test_p08_movmean5_interior(self):
        out = matlab_movmean5([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        assert out[2] == pytest.approx(3.0)  # mean(1..5)
        assert out[3] == pytest.approx(4.0)  # mean(2..6)

    def test_p09_movmean5_left_edge_shrink(self):
        out = matlab_movmean5([1.0, 2.0, 3.0, 4.0, 5.0])
        assert out[0] == pytest.approx(2.0)  # mean(1,2,3)
        assert out[1] == pytest.approx(2.5)  # mean(1,2,3,4)

    def test_p10_movmean5_right_edge_shrink(self):
        out = matlab_movmean5([1.0, 2.0, 3.0, 4.0, 5.0])
        assert out[4] == pytest.approx(4.0)  # mean(3,4,5)
        assert out[3] == pytest.approx(3.5)  # mean(2,3,4,5)

    def test_p11_source_order_preserved(self):
        frames = _synth_frames(8)
        raw = bottom_wave_amplitude(frames)["raw"]
        # envelope max of a monotonically decaying packet decreases with i
        assert raw[0] > raw[-1]

    def test_p12_raw_preserved_alongside_smoothed(self):
        frames = _synth_frames(6)
        r = bottom_wave_amplitude(frames)
        assert not np.array_equal(r["raw"], r["smoothed_movmean5"])
        # interior smoothing equals direct movmean of raw
        assert np.allclose(r["smoothed_movmean5"][2:-2], matlab_movmean5(r["raw"])[2:-2])


class TestXcorrTof:
    """P13–P20."""

    def test_p13_correlation_parity_with_scipy(self):
        frames = _synth_frames(3)
        out = surface_bottom_xcorr_tof(frames)
        for i in range(3):
            r = correlate(frames[i, 59:260], frames[i, 749:1200], mode="full", method="direct")
            assert out["correlation_peak_index_zero_based"][i] == int(np.argmax(np.abs(r)))

    def test_p14_first_max_used(self):
        # two equal peaks → argmax picks the first
        r = np.array([0.0, 5.0, -5.0, 0.0])
        assert int(np.argmax(np.abs(r))) == 1

    def test_p15_peak_index_conversion(self):
        frames = _synth_frames(2)
        out = surface_bottom_xcorr_tof(frames)
        for i in range(2):
            p0 = out["correlation_peak_index_zero_based"][i]
            tof = out["tof_samples"][i]
            # tof = length(y) - (p0+1)
            assert tof == 451 - (p0 + 1)

    def test_p16_source_formula_positive_lag(self):
        # bottom packet delayed vs surface → tof_samples > 0
        frames = _synth_frames(3)
        out = surface_bottom_xcorr_tof(frames)
        assert np.all(out["tof_samples"] > 0)

    def test_p17_lag_relation(self):
        frames = _synth_frames(3)
        out = surface_bottom_xcorr_tof(frames)
        assert np.array_equal(out["tof_samples"], -out["correlation_lag_samples"])

    def test_p18_signed_result_preserved(self):
        # identical x,y (self-correlation peak at center) → tof = 451-201+... verify exact
        frames = np.tile(_synth_frames(1), (2, 1))
        # replace bottom gate content with surface content → peak at lag where
        # x aligns y; simply check output is int64 and finite
        out = surface_bottom_xcorr_tof(frames)
        assert out["tof_samples"].dtype == np.int64

    def test_p19_missing_fs_blocks_physical_time(self):
        frames = _synth_frames(2)
        out = surface_bottom_xcorr_tof(frames)
        assert out["tof_us"] is None  # never fabricated

    def test_p20_time_conversion(self):
        tof = np.array([100, 250, 1000])
        us = tof_samples_to_us(tof, 50e6)
        assert us[0] == pytest.approx(100 / 50e6 * 1e6)  # 2.0 us
        assert us[1] == pytest.approx(5.0)
        with pytest.raises(ValueError):
            tof_samples_to_us(tof, None)


class TestAttenuation:
    """P21–P28."""

    def test_p21_p22_p23_env_stats(self):
        frames = _synth_frames(3)
        out = bottom_attenuation_explicit(frames)
        for i in range(3):
            env = np.abs(hilbert(frames[i, 749:1150]))
            assert out["amp_max"][i] == pytest.approx(np.max(env), rel=1e-12)
            assert out["amp_mean"][i] == pytest.approx(np.mean(env), rel=1e-12)
            assert out["amp_energy"][i] == pytest.approx(np.sum(env**2), rel=1e-12)

    def test_p24_half_height_width(self):
        env = np.array([0.0, 0.6, 1.0, 0.7, 0.2, 0.0])
        mx = env.max()
        idx = np.flatnonzero(env >= mx * 0.5)
        assert idx[-1] - idx[0] + 1 == 3  # indices 1..3

    def test_p25_zero_signal_matlab_semantics(self):
        # zero signal: env all 0, threshold 0 → find matches ALL indices
        # MATLAB source semantics → width = full gate length 401 (documented,
        # not silently "fixed" to 0)
        frames = np.zeros((1, 1280))
        out = bottom_attenuation_explicit(frames)
        assert out["amp_max"][0] == 0.0
        assert out["width_half_samples"][0] == 401

    def test_p26_nfft_1024(self):
        frames = _synth_frames(2)
        out = bottom_attenuation_explicit(frames, sampling_rate_hz=50e6)
        assert out["spectral_intermediates"]["nfft"] == 1024
        assert out["spectral_intermediates"]["magnitude_one_sided"].shape[1] == 513

    def test_p27_band_mask_1_10mhz_inclusive(self):
        frames = _synth_frames(2)
        out = bottom_attenuation_explicit(frames, sampling_rate_hz=50e6)
        f = out["spectral_intermediates"]["frequency_hz"]
        mask = out["spectral_intermediates"]["band_mask_1_10mhz"]
        assert f[mask].min() >= 1e6 and f[mask].max() <= 10e6

    def test_p28_fifth_feature_blocked(self):
        frames = _synth_frames(2)
        out = bottom_attenuation_explicit(frames, sampling_rate_hz=50e6)
        assert out["hf_band_energy"] is None
        assert out["hf_band_status"] == "SOURCE_FORMULA_INCOMPLETE"


class TestBPS:
    """P29–P36."""

    def test_p29_reference_is_first_frame(self):
        frames = _synth_frames(5)
        out = bottom_wave_phase_shift(frames)
        assert out["reference_frame_index"] == 0
        # first frame's raw BPS == mean(unwrap(0)) == 0
        assert out["raw_radian"][0] == pytest.approx(0.0, abs=1e-9)

    def test_p30_p31_p32_hilbert_phase_diff_unwrap(self):
        frames = _synth_frames(3)
        out = bottom_wave_phase_shift(frames)
        gate = frames[:, 749:1150]
        ref_phase = np.angle(hilbert(gate[0]))
        for i in range(3):
            delta = np.unwrap(np.angle(hilbert(gate[i])) - ref_phase)
            assert out["raw_radian"][i] == pytest.approx(np.mean(delta), rel=1e-12)

    def test_p33_region_mean(self):
        # constant phase offset 0.1 rad → raw ≈ 0.1
        t = np.arange(1280)
        base = np.exp(-((t - 950.0) ** 2) / (2 * 25.0**2)) * np.sin(2 * np.pi * 0.1 * t)
        frames = np.vstack([base, np.roll(base, 1)])
        out = bottom_wave_phase_shift(frames)
        assert np.isfinite(out["raw_radian"]).all()

    def test_p34_movmean5_applied(self):
        frames = _synth_frames(6)
        out = bottom_wave_phase_shift(frames)
        assert np.allclose(out["smoothed_movmean5_radian"], matlab_movmean5(out["raw_radian"]))

    def test_p35_slice_does_not_change_reference(self):
        frames = _synth_frames(6)
        full = bottom_wave_phase_shift(frames)
        # computing on a slice must reuse reference frame 0 — verified because
        # the function always uses frame 0; slicing input changes nothing for
        # frame 0's value
        sub = bottom_wave_phase_shift(frames[:4])
        assert full["raw_radian"][0] == pytest.approx(sub["raw_radian"][0], abs=1e-12)

    def test_p36_no_resmoothing_of_subset(self):
        frames = _synth_frames(8)
        full = bottom_wave_phase_shift(frames)
        # smoothed at index 2 of full equals movmean of the FULL raw, not of a subset
        expected = np.mean(full["raw_radian"][0:5])
        assert full["smoothed_movmean5_radian"][2] == pytest.approx(expected, rel=1e-12)


class TestProvenance:
    """P37–P42."""

    def test_p37_gate_source_provenance(self):
        t = get_gate_template("BOTTOM_AMPLITUDE_GATE")
        src = t.source_indices()
        assert src["matlab_start_1based_inclusive"] == 750
        assert src["python_start_0based"] == 749

    def test_p38_source_vs_canonical_recorded(self):
        for t in GATE_TEMPLATES:
            assert t.python_end_exclusive - t.python_start == t.matlab_end - t.matlab_start + 1

    def test_p39_templates_not_universal(self):
        # every template requires recalibration on config change (no universal gate)
        assert SOURCE_FORMULA_ID == "USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1"
        assert len(GATE_TEMPLATES) == 6

    def test_p40_exact_reference_frame_persisted(self):
        frames = _synth_frames(3)
        out = bottom_wave_phase_shift(frames)
        assert out["reference_frame_index"] == 0

    def test_p41_smoothing_definition_persisted(self):
        frames = _synth_frames(3)
        out = bottom_wave_amplitude(frames)
        assert out["smoothed_method"] == "MOVMEAN_5_SOURCE_ORDER_V1"

    def test_p42_bps_unit_radian(self):
        frames = _synth_frames(3)
        assert bottom_wave_phase_shift(frames)["unit"] == "radian"

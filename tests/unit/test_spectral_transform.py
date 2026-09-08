"""Tests for SpectralTransformDefinition + Full-wave/Gated extraction (§08/§11/§42)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from battery_workbench.features.matlab_features import compute_frequency_domain
from battery_workbench.features.spectral_transform import (
    FULL_WAVEFORM,
    SpectralTransformDefinition,
    extract_fd_block,
    extract_td_block,
    gate_slice,
    spectrum_from_waveform,
)


class TestGateSlice:
    def test_full_waveform_returns_all(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        out = gate_slice(x)
        assert out.shape == (4,)

    def test_explicit_gate_half_open(self):
        x = np.arange(10, dtype=np.float64)
        out = gate_slice(x, gate_id="G", python_start=2, python_end_exclusive=5)
        assert np.array_equal(out, np.array([2.0, 3.0, 4.0]))

    def test_gate_out_of_bounds_raises(self):
        x = np.arange(10, dtype=np.float64)
        with pytest.raises(ValueError, match="bounds"):
            gate_slice(x, gate_id="G", python_start=8, python_end_exclusive=12)

    def test_gate_bounds_required(self):
        with pytest.raises(ValueError, match="explicit bounds"):
            gate_slice(np.arange(5.0), gate_id="G")


class TestSpectralTransform:
    def test_no_default_inference_required_fields(self):
        t = SpectralTransformDefinition(spectral_transform_id="X")
        # representation defaults to explicit MAGNITUDE, but identity is versioned
        assert t.spectral_representation == "MAGNITUDE"
        assert t.transform_id() == "X@1.0.0"

    def test_missing_sampling_rate_raises_when_required(self):
        t = SpectralTransformDefinition(
            spectral_transform_id="S",
            sampling_rate_parameter_id="ultrasound.fs_hz",
        )
        with pytest.raises(ValueError, match="MISSING_SAMPLING_RATE"):
            spectrum_from_waveform(np.ones(64), t)

    def test_magnitude_spectrum_explicit(self):
        t = SpectralTransformDefinition(spectral_transform_id="S", remove_dc=True)
        x = np.concatenate([np.zeros(16), np.ones(16)])
        f, y = spectrum_from_waveform(x, t)
        assert y.shape == f.shape == (17,)  # nfft=32 → 32//2+1 = 17 one-sided bins
        assert np.all(y >= 0)

    def test_power_spectrum_representation(self):
        t = SpectralTransformDefinition(
            spectral_transform_id="S", spectral_representation="POWER"
        )
        rng = np.random.default_rng(7)
        x = rng.standard_normal(64)
        _, y_power = spectrum_from_waveform(x, t)
        t2 = t.model_copy(update={"spectral_representation": "MAGNITUDE"})
        _, y_mag = spectrum_from_waveform(x, t2)
        assert np.allclose(y_power, y_mag**2)

    def test_other_explicit_refuses_to_guess(self):
        t = SpectralTransformDefinition(
            spectral_transform_id="S", spectral_representation="OTHER_EXPLICIT"
        )
        with pytest.raises(ValueError, match="refusing to guess"):
            spectrum_from_waveform(np.ones(16), t)

    def test_frequency_axis_with_fs(self):
        t = SpectralTransformDefinition(
            spectral_transform_id="S", fft_length=64
        )
        f, _ = spectrum_from_waveform(np.ones(64), t, sampling_rate_hz=50e6)
        assert f[1] == pytest.approx(50e6 / 64)
        assert f[-1] == pytest.approx(25e6)  # Nyquist


class TestFullVsGated:
    """§69 — same waveform full vs gate distinct; outside changes don't affect gate."""

    WAVE = np.array([0.0, 1.0, 0.0, 0.0, 3.0, 3.0, 3.0, 0.0, 0.0, -1.0])

    def test_full_and_gated_td_differ(self):
        full = {b.code: b.value for b in extract_td_block(self.WAVE)}
        gated = {b.code: b.value for b in extract_td_block(
            self.WAVE, scope="USER_SELECTED_EXPLICIT_GATE",
            gate_id="G1", python_start=4, python_end_exclusive=7,
        )}
        assert full["TDMax"] == pytest.approx(3.0)
        assert gated["TDMax"] == pytest.approx(3.0)
        assert full["TDMin"] == pytest.approx(-1.0)
        assert gated["TDMin"] == pytest.approx(3.0)  # gate [4,7) is constant 3s
        assert full["TDM"] != pytest.approx(gated["TDM"])

    def test_gate_outside_changes_do_not_affect_gated_output(self):
        a = np.array([9.0, 9.0, 1.0, 2.0, 3.0])
        b = np.array([1.0, 1.0, 1.0, 2.0, 3.0])
        ra = {bl.code: bl.value for bl in extract_td_block(
            a, gate_id="G", python_start=2, python_end_exclusive=5)}
        rb = {bl.code: bl.value for bl in extract_td_block(
            b, gate_id="G", python_start=2, python_end_exclusive=5)}
        assert ra["TDM"] == pytest.approx(rb["TDM"])
        assert ra["TDSTD"] == pytest.approx(rb["TDSTD"])

    def test_same_feature_different_gates_distinct_locator(self):
        b1 = extract_td_block(self.WAVE, gate_id="G1", python_start=0, python_end_exclusive=5)
        b2 = extract_td_block(self.WAVE, gate_id="G2", python_start=5, python_end_exclusive=10)
        assert b1[0].gate_id == "G1"
        assert b2[0].gate_id == "G2"
        v1 = {b.code: b.value for b in b1}
        v2 = {b.code: b.value for b in b2}
        assert v1["TDM"] != v2["TDM"]

    def test_full_waveform_scope_label(self):
        blocks = extract_td_block(self.WAVE)
        assert all(b.scope == FULL_WAVEFORM and b.gate_id is None for b in blocks)


class TestTDBlocks:
    def test_19_codes_emitted(self):
        blocks = extract_td_block(np.array([1.0, 2.0, 3.0]))
        assert len(blocks) == 19
        assert blocks[0].code == "TDM"

    def test_constant_waveform_status(self):
        blocks = extract_td_block(np.array([2.0, 2.0, 2.0]))
        by_code = {b.code: b for b in blocks}
        assert "INVALID_ZERO_STD" in by_code["TDS"].statuses
        assert math.isnan(by_code["TDS"].value)
        # no silent zero substitution
        assert by_code["TDS"].value is not None and by_code["TDS"].value != 0.0


class TestFDBlocks:
    def test_14_codes_emitted(self):
        t = SpectralTransformDefinition(spectral_transform_id="S")
        blocks = extract_fd_block(np.array([1.0, 2.0, 3.0, 4.0]), t)
        assert len(blocks) == 14
        assert all(b.spectral_transform_id == "S@1.0.0" for b in blocks)

    def test_missing_transform_is_explicit_not_guessed(self):
        # FD identity carries the transform id; two transforms → two identities
        t1 = SpectralTransformDefinition(spectral_transform_id="S1")
        t2 = SpectralTransformDefinition(
            spectral_transform_id="S2", spectral_representation="POWER"
        )
        x = np.array([1.0, 2.0, 3.0, 4.0])
        v1 = {b.code: b.value for b in extract_fd_block(x, t1)}
        v2 = {b.code: b.value for b in extract_fd_block(x, t2)}
        assert v1["FDAF"] != pytest.approx(v2["FDAF"])

    def test_gated_fd(self):
        t = SpectralTransformDefinition(spectral_transform_id="S")
        x = np.zeros(16)
        x[4:8] = 1.0
        blocks = extract_fd_block(
            x, t, scope="USER_SELECTED_EXPLICIT_GATE",
            gate_id="G", python_start=4, python_end_exclusive=8,
        )
        assert all(b.gate_id == "G" for b in blocks)

    def test_fd_math_matches_direct_formula_call(self):
        t = SpectralTransformDefinition(spectral_transform_id="S", remove_dc=False)
        x = np.array([1.0, 2.0, 3.0, 4.0, 2.0, 1.0, 0.5, 0.25])
        f, y = spectrum_from_waveform(x, t)
        direct = compute_frequency_domain(f, y)
        blocks = extract_fd_block(x, t)
        by_code = {b.code: b.value for b in blocks}
        assert by_code["FDM"] == pytest.approx(direct["FDM"])
        assert by_code["FDAF"] == pytest.approx(direct["FDAF"])
        assert by_code["FDEQ"] == pytest.approx(direct["FDEQ"])

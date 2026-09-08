"""BRW-013X V2 golden tests — independent hand-computed expected values (§47/§48).

These fixtures are computed BY HAND from the MATLAB source formulas on simple
vectors, NOT from the production Python implementation.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from battery_workbench.features.matlab_features import (
    EPS64,
    compute_frequency_domain,
    compute_time_domain,
)

TOL = 1e-12


class TestTDx123:
    """x = [1, 2, 3], hand-computed."""

    def test_tdm(self):
        assert compute_time_domain([1, 2, 3])["TDM"] == pytest.approx(2.0)

    def test_tdstd_population(self):
        # sum(xc²)/N = (1+0+1)/3 — population style, NOT ddof=1
        got = compute_time_domain([1, 2, 3])["TDSTD"]
        assert got == pytest.approx(math.sqrt(2.0 / 3.0), rel=TOL)
        # explicitly not np.std(ddof=1) = 1.0
        assert got != pytest.approx(1.0, abs=1e-6)

    def test_tdrms2_not_rms(self):
        # TDRMS² = mean(x²) = 14/3, NOT sqrt
        got = compute_time_domain([1, 2, 3])["TDRMS2"]
        assert got == pytest.approx(14.0 / 3.0, rel=TOL)
        # explicitly NOT RMS = sqrt(14/3) ≈ 2.16
        assert got != pytest.approx(math.sqrt(14.0 / 3.0), abs=0.01)

    def test_tdmav(self):
        # mean(|x|) = (1+2+3)/3 = 2 — NOT mean(xc)
        assert compute_time_domain([1, 2, 3])["TDMAV"] == pytest.approx(2.0, rel=TOL)

    def test_tds_no_eps(self):
        # TDS = third_moment/TDSTD³ — source has NO eps here
        got = compute_time_domain([1, 2, 3])["TDS"]
        assert got == 0.0  # sum(xc³) = (-1)³+0³+1³ = 0

    def test_tdk_pearson_candidate(self):
        got = compute_time_domain([1, 2, 3])["TDK"]
        assert got == pytest.approx(1.5, rel=TOL)  # (2/3)/(4/9) = 1.5

    def test_tdv_ddof1(self):
        got = compute_time_domain([1, 2, 3])["TDV"]
        assert got == pytest.approx(1.0, rel=TOL)  # var(ddof=1) = 2/2 = 1

    def test_tdmax_tdmin_tdpp(self):
        r = compute_time_domain([1, 2, 3])
        assert r["TDMax"] == 3.0
        assert r["TDMin"] == 1.0
        assert r["TDPP"] == 2.0

    def test_tdei_trapz_not_sum(self):
        # TDEI = trapz(x², dx=1) = 9, NOT sum(x²) = 14
        got = compute_time_domain([1, 2, 3])["TDEI"]
        assert got == pytest.approx(9.0, rel=TOL)
        assert got != pytest.approx(14.0, abs=0.1)  # not sum of squares

    def test_tdwc(self):
        got = compute_time_domain([1, 2, 3])["TDWC"]
        expected = 5.0 / (4.0 + EPS64)
        assert got == pytest.approx(expected, rel=1e-9)

    def test_tdsavr_eps(self):
        got = compute_time_domain([1, 2, 3])["TDSAVR"]
        expected = (2.0 / 3.0) ** 0.5 / (2.0 + EPS64)
        assert got == pytest.approx(expected, rel=1e-9)

    def test_tdmsr_tdmar_tdmrr_eps(self):
        r = compute_time_domain([1, 2, 3])
        assert r["TDMSR"] == pytest.approx(3.0 / ((2.0 / 3.0) ** 0.5 + EPS64), rel=1e-9)
        assert r["TDMAR"] == pytest.approx(3.0 / (2.0 + EPS64), rel=1e-9)
        assert r["TDMRR"] == pytest.approx(3.0 / ((14.0 / 3.0) ** 0.5 + EPS64), rel=1e-9)

    def test_tdhsk_tdksr_tdher(self):
        r = compute_time_domain([1, 2, 3])
        assert r["TDHSK"] == 0.0
        assert r["TDKSR"] == pytest.approx(1.5 / ((2.0 / 3.0) ** 0.5 + EPS64), rel=1e-9)
        assert r["TDHMER"] == pytest.approx((2.0 / 3.0) / (14.0 + EPS64), rel=1e-9)

    def test_all_19_present_in_order(self):
        from battery_workbench.features.matlab_features import TD_CODES
        r = compute_time_domain([1, 2, 3])
        assert list(r.keys()) == list(TD_CODES)
        assert len(r) == 19


class TestTDAlternating:
    """x = [1, -1, 1, -1]"""

    def test_tdstd_exact_1(self):
        assert compute_time_domain([1, -1, 1, -1])["TDSTD"] == pytest.approx(1.0)

    def test_tdk_pearson_1(self):
        assert compute_time_domain([1, -1, 1, -1])["TDK"] == pytest.approx(1.0, rel=TOL)

    def test_tdv(self):
        assert compute_time_domain([1, -1, 1, -1])["TDV"] == pytest.approx(4.0 / 3.0, rel=TOL)

    def test_tdei(self):
        assert compute_time_domain([1, -1, 1, -1])["TDEI"] == pytest.approx(3.0, rel=TOL)

    def test_tdwc_divergent_denominator(self):
        # trapz(x, t) = 0 → denominator = EPS64 → very large magnitude (finite)
        got = compute_time_domain([1, -1, 1, -1])["TDWC"]
        assert math.isfinite(got)
        assert abs(got) > 1e12  # -0.5 / eps


class TestTDConstant:
    """x = [2, 2, 2] — degenerate: TDSTD=0"""

    def test_tdstd_zero(self):
        assert compute_time_domain([2, 2, 2])["TDSTD"] == 0.0

    def test_tdv_zero(self):
        assert compute_time_domain([2, 2, 2])["TDV"] == 0.0

    def test_tdei(self):
        assert compute_time_domain([2, 2, 2])["TDEI"] == pytest.approx(8.0, rel=TOL)

    def test_tdwc(self):
        assert compute_time_domain([2, 2, 2])["TDWC"] == pytest.approx(1.0, rel=TOL)

    def test_tds_nan_guard(self):
        # TDS = 0/0 without eps → NaN preserved (not zero)
        assert math.isnan(compute_time_domain([2, 2, 2])["TDS"])


class TestFD:
    """f = [0,1,2,3], y = [1,2,3,4]"""

    def test_fdm(self):
        assert compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDM"] == pytest.approx(2.5)

    def test_fdv_population(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDV"]
        assert got == pytest.approx(1.25, rel=TOL)

    def test_fds_zero(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDS"]
        assert got == pytest.approx(0.0, abs=1e-12)

    def test_fdk(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDK"]
        expected = 10.25 / (4 * (1.25 ** 2 + EPS64))
        assert got == pytest.approx(expected, rel=1e-9)

    def test_fdaf_weighted_by_y(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDAF"]
        assert got == pytest.approx(2.0, rel=TOL)

    def test_fdsd(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDSD"]
        # (f-FDAF)^2 = [4,1,0,1], weighted: 4*1+1*2+0*3+1*4 = 10, /sumy=10 → 1.0
        assert got == pytest.approx(1.0, rel=1e-9)

    def test_fdrms(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDRMS"]
        assert got == pytest.approx(math.sqrt(5.0), rel=1e-9)

    def test_fdsr_is_sqrt_fdaf(self):
        r = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])
        assert r["FDSR"] == pytest.approx(math.sqrt(r["FDAF"]), rel=1e-12)

    def test_fdcf(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDCF"]
        assert got == pytest.approx(1.6, rel=TOL)

    def test_fdfsdr(self):
        r = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])
        assert r["FDFSDR"] == pytest.approx(r["FDSD"] / (r["FDAF"] + EPS64), rel=1e-9)

    def test_fdfs(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDFS"]
        expected = -6.0 / ((1.0 ** 3 + EPS64) * 10.0)
        assert got == pytest.approx(expected, rel=1e-9)

    def test_fdfk(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDFK"]
        expected = (16 + 2 + 0 + 4) / ((1.0 ** 4 + EPS64) * 10.0)
        assert got == pytest.approx(expected, rel=1e-9)

    def test_fdeq_not_normalized(self):
        # FDEQ uses prob = y²/(sum(y²)+eps) with log2 — NOT normalized to [0,1]
        f, y = [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0]
        got = compute_frequency_domain(f, y)["FDEQ"]
        y2 = np.array(y) ** 2
        prob = y2 / (y2.sum() + EPS64)
        expected = float(-np.sum(prob * np.log2(prob + EPS64)))
        assert got == pytest.approx(expected, rel=1e-12)
        # explicit check: it's NOT the uniform-distribution entropy log2(4)=2
        assert got != pytest.approx(2.0, abs=0.01)

    def test_fdeq_matches_golden(self):
        assert compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDEQ"] == pytest.approx(
            1.5559130951758235, rel=1e-9
        )

    def test_fdfwm_trapz(self):
        got = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])["FDFWM"]
        assert got == pytest.approx(14.0 / 7.5, rel=1e-9)

    def test_all_14_present_in_order(self):
        from battery_workbench.features.matlab_features import FD_CODES
        r = compute_frequency_domain([0, 1, 2, 3], [1, 2, 3, 4])
        assert list(r.keys()) == list(FD_CODES)
        assert len(r) == 14


class TestSemanticTraps:
    """§66/§68 — no hidden semantic changes."""

    def test_no_extra_eps_in_tds(self):
        # TDS: source has no eps → constant vector → NaN, not 0-with-eps
        assert math.isnan(compute_time_domain([2, 2, 2])["TDS"])

    def test_eps_value_is_float64_eps(self):
        from battery_workbench.features.matlab_features import EPS64 as exported
        assert exported == np.finfo(np.float64).eps
        assert EPS64 == exported

    def test_tdrms2_not_rms_explicit(self):
        # For [1,2,3]: TDRMS² = 4.667 ≠ RMS = 2.16
        r = compute_time_domain([1, 2, 3])
        assert abs(r["TDRMS2"] - math.sqrt(r["TDRMS2"])) > 1.0

    def test_tdei_has_no_dt_multiplication(self):
        # If someone multiplies by dt=1/fs, result would be tiny; here it's 9.0
        assert compute_time_domain([1, 2, 3])["TDEI"] == pytest.approx(9.0, rel=1e-9)

    def test_fd_no_silent_abs_y(self):
        # negative y → FDAF should reflect the sign (no abs)
        got = compute_frequency_domain([0, 1], [1, -1])
        # sumy = (1-1)+eps = eps; sum(f*y) = (0*1)+(1*(-1)) = -1 → -1/eps → huge negative
        assert math.isfinite(got["FDAF"])
        assert got["FDAF"] < 0

    def test_fd_no_entropy_normalization(self):
        # FDEQ for uniform y of length 4: prob=0.25 each → -sum(0.25*log2(0.25+eps))
        # ≈ 2.0 - (small correction from eps) but NOT exactly 2.0
        got = compute_frequency_domain([0, 1, 2, 3], [1, 1, 1, 1])
        # y² all = 1, prob = 1/(4+eps), FDEQ = -4*(1/4)*log2(1/4+eps) ≈ 2.0 - correction
        assert not math.isnan(got["FDEQ"])
        # should be extremely close to log2(4)=2 (uniform) but eps-perturbed
        assert abs(got["FDEQ"] - 2.0) < 1e-12  # uniform input → max entropy
        # but formula is raw (no re-normalization): perturbation exists at float64 eps level
        assert got["FDEQ"] != 2.0  # eps perturbation present → not the clean textbook value

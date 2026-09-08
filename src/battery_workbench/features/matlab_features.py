"""BRW-013X V2 — MATLAB-aligned TD/FD statistical features.

Direct translation of user-provided MATLAB:
  time_statistical_compute(x)  → 19 TD features
  fre_statistical_compute(f,y) → 14 FD features

Rules frozen by the task pack:
- all math in float64
- EPS64 = np.finfo(np.float64).eps only where the MATLAB source has +eps
- TDSTD uses population-style /N (NOT ddof=1)
- TDV uses np.var(x, ddof=1) candidate pending MATLAB parity
- TDK candidate = raw/Pearson kurtosis (fourth_central / TDSTD^4), pending parity
- TDEI = trapezoid(x², dx=1), no dt multiplication
- FDSR = sqrt(FDAF), FDEQ = -sum(prob*log2(prob+eps)) non-normalized
- no silent abs(y), no frequency normalization
"""

from __future__ import annotations

import numpy as np

EPS64 = float(np.finfo(np.float64).eps)

TD_CODES = (
    "TDM", "TDSTD", "TDRMS2", "TDMAV", "TDS", "TDK", "TDV",
    "TDMax", "TDMin", "TDPP", "TDEI", "TDWC", "TDSAVR",
    "TDMSR", "TDMAR", "TDMRR", "TDHSK", "TDKSR", "TDHMER",
)

FD_CODES = (
    "FDM", "FDV", "FDS", "FDK", "FDAF", "FDSD", "FDRMS",
    "FDSR", "FDCF", "FDFSDR", "FDFS", "FDFK", "FDEQ", "FDFWM",
)


def _trapz(y: np.ndarray, *, x: np.ndarray | None = None, dx: float = 1.0) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(y, x=x, dx=dx))
    return float(np.trapz(y, x=x, dx=dx))


def compute_time_domain(x) -> dict[str, float]:
    """TD 19 features, exact source order, MATLAB formula parity."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    n = x.size
    if n == 0:
        raise ValueError("x must contain at least one sample")

    t = np.arange(n, dtype=np.float64)

    tdm = float(np.mean(x))
    xc = x - tdm

    tdstd = float(np.sqrt(np.sum(xc**2) / n))
    tdrms2 = float(np.sum(x**2) / n)
    tdmav = float(np.sum(np.abs(x)) / n)

    third_moment = float(np.sum(xc**3) / n)
    with np.errstate(divide="ignore", invalid="ignore"):
        tds = third_moment / (tdstd**3) if tdstd > 0 else float("nan")

    fourth_central = float(np.sum(xc**4) / n)
    # TDK candidate: raw/Pearson kurtosis (fourth_central / TDSTD^4)
    # Source writes kurtosis(xc)+3 — pending MATLAB parity confirmation.
    with np.errstate(divide="ignore", invalid="ignore"):
        tdk = fourth_central / (tdstd**4) if tdstd > 0 else float("nan")

    # TDV candidate: MATLAB var(x) default → sample variance ddof=1
    tdv = float(np.var(x, ddof=1)) if n > 1 else float("nan")

    tdmax = float(np.max(x))
    tdmin = float(np.min(x))
    tdpp = tdmax - tdmin

    tdei = _trapz(x**2, dx=1.0)

    tdwc = _trapz(t * x, x=t) / (_trapz(x, x=t) + EPS64)

    tdsavr = tdstd / (tdmav + EPS64)
    tdmsr = tdmax / (tdstd + EPS64)
    tdmar = tdmax / (tdmav + EPS64)

    rms_val = float(np.sqrt(tdrms2))
    tdmrr = tdmax / (rms_val + EPS64)

    tdhsk = tds**2
    tdksr = tdk / (tdstd + EPS64)

    energy = float(np.sum(x**2))
    tdhmer = fourth_central / (energy + EPS64)

    vals = (
        tdm, tdstd, tdrms2, tdmav, tds, tdk, tdv,
        tdmax, tdmin, tdpp, tdei, tdwc, tdsavr,
        tdmsr, tdmar, tdmrr, tdhsk, tdksr, tdhmer,
    )
    return dict(zip(TD_CODES, map(float, vals)))


def compute_frequency_domain(f, y) -> dict[str, float]:
    """FD 14 features, exact source order, MATLAB formula parity."""
    f = np.asarray(f, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)

    if y.size == 0:
        raise ValueError("y must contain at least one spectral sample")
    if f.size != y.size:
        raise ValueError("f and y must have the same length")

    m = y.size

    fdm = float(np.mean(y))
    fdv = float(np.sum((y - fdm) ** 2) / m)

    with np.errstate(divide="ignore", invalid="ignore"):
        fds = float(np.sum((y - fdm) ** 3) / (m * (fdv**1.5 + EPS64)))
        fdk = float(np.sum((y - fdm) ** 4) / (m * (fdv**2 + EPS64)))

    sumy = float(np.sum(y) + EPS64)
    fdaf = float(np.sum(f * y) / sumy)

    fdsum_sq = float(np.sum((f - fdaf) ** 2 * y) / sumy)
    fdsd = float(np.sqrt(fdsum_sq))

    fdrms = float(np.sqrt(np.sum(f**2 * y) / sumy))
    fdsr = float(np.sqrt(fdaf))

    fdcf = float(np.max(y) / (np.mean(y) + EPS64))
    fdfsdr = float(fdsd / (fdaf + EPS64))

    fdfs = float(np.sum((f - fdaf) ** 3 * y) / ((fdsd**3 + EPS64) * sumy))
    fdfk = float(np.sum((f - fdaf) ** 4 * y) / ((fdsd**4 + EPS64) * sumy))

    y2 = y**2
    prob = y2 / (float(np.sum(y2)) + EPS64)
    fdeq = float(-np.sum(prob * np.log2(prob + EPS64)))

    fdfwm = _trapz(f * y, x=f) / (_trapz(y, x=f) + EPS64)

    vals = (fdm, fdv, fds, fdk, fdaf, fdsd, fdrms, fdsr,
            fdcf, fdfsdr, fdfs, fdfk, fdeq, fdfwm)
    return dict(zip(FD_CODES, map(float, vals)))

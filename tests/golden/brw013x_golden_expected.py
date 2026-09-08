"""Independent hand-computed golden fixtures for BRW-013X V2.

All expected values are derived from the MATLAB source formulas by hand on
simple vectors — NOT from the production Python implementation.
"""

from __future__ import annotations

# ---- TD fixture: x = [1, 2, 3] ----
# N=3, t=[0,1,2]
# mean = 2, xc = [-1,0,1]
# TDSTD = sqrt((1+0+1)/3) = sqrt(2/3)
# TDRMS2 = (1+4+9)/3 = 14/3
# TDMAV = mean(|x|) = (1+2+3)/3 = 2
# TDS = sum(xc^3)/N / TDSTD^3 = (−1+0+1)/3 / (2/3)^1.5 = 0 / ... = 0
# TDK (Pearson candidate) = sum(xc^4)/N / TDSTD^4 = (1+0+1)/3 / (2/3)^2 = (2/3)/(4/9) = 3/2
# TDV = np.var ddof=1 = (1+0+1)/2 = 1
# TDMax = 3, TDMin = 1, TDPP = 2
# TDEI = trapz([1,4,9], dx=1) = (1+9)/2 + 4 = 7  (trapz: (y0+y1)/2 + (y1+y2)/2 = 2.5+6.5=9)
#   trapz([1,4,9]) = (1+4)/2*1 + (4+9)/2*1 = 2.5 + 6.5 = 9
# TDWC: trapz(t*x, t) = trapz([0,2,6]) = (0+2)/2+(2+6)/2 = 1+4 = 5
#       trapz(x, t) = trapz([1,2,3]) = (1+2)/2+(2+3)/2 = 1.5+2.5 = 4
#       TDWC = 5/(4+eps)
# TDSAVR = TDSTD/(TDMAV+eps) = sqrt(2/3)/(2+eps)
# TDMSR = 3/(TDSTD+eps)
# TDMAR = 3/(2+eps)
# TDMRR = 3/(sqrt(14/3)+eps)
# TDHSK = TDS^2 = 0
# TDKSR = TDK/(TDSTD+eps) = 1.5/(sqrt(2/3)+eps)
# TDHMER = (sum(xc^4)/N)/(sum(x^2)+eps) = (2/3)/(14+eps)
TD_X123 = {
    "TDM": 2.0,
    "TDSTD": (2.0 / 3.0) ** 0.5,
    "TDRMS2": 14.0 / 3.0,
    "TDMAV": 2.0,
    "TDS": 0.0,
    "TDK": 1.5,
    "TDV": 1.0,
    "TDMax": 3.0,
    "TDMin": 1.0,
    "TDPP": 2.0,
    "TDEI": 9.0,
    "TDWC": 5.0 / (4.0 + 2.220446049250313e-16),
    "TDSAVR": (2.0 / 3.0) ** 0.5 / (2.0 + 2.220446049250313e-16),
    "TDMSR": 3.0 / ((2.0 / 3.0) ** 0.5 + 2.220446049250313e-16),
    "TDMAR": 3.0 / (2.0 + 2.220446049250313e-16),
    "TDMRR": 3.0 / ((14.0 / 3.0) ** 0.5 + 2.220446049250313e-16),
    "TDHSK": 0.0,
    "TDKSR": 1.5 / ((2.0 / 3.0) ** 0.5 + 2.220446049250313e-16),
    "TDHMER": (2.0 / 3.0) / (14.0 + 2.220446049250313e-16),
}

# ---- TD fixture: x = [1, -1, 1, -1] ----
# N=4, mean=0, xc=x
# TDSTD = sqrt(4/4) = 1
# TDRMS2 = 1
# TDMAV = 1
# TDS = (1-1+1-1)/4 / 1 = 0
# TDK = (1+1+1+1)/4 / 1 = 1
# TDV = np.var ddof=1 = 4/3
# TDMax = 1, TDMin = -1, TDPP = 2
# TDEI = trapz([1,1,1,1]) = 1+1+1 = 3
# TDWC: trapz(t*x) = trapz([0,-1,2,-3]) = (-1+0.5)+(-0.5-1.5) = wait, use pairs:
#   trapz([0,-1,2,-3], t=[0,1,2,3]) = (0-1)/2 + (-1+2)/2 + (2-3)/2 = -0.5+0.5-0.5 = -0.5
#   trapz(x, t) = trapz([1,-1,1,-1]) = (1-1)/2+(-1+1)/2+(1-1)/2 = 0
#   TDWC = -0.5/(0+eps) → -inf-ish (large magnitude); finite check only
TD_X1M1 = {
    "TDM": 0.0,
    "TDSTD": 1.0,
    "TDRMS2": 1.0,
    "TDMAV": 1.0,
    "TDS": 0.0,
    "TDK": 1.0,
    "TDV": 4.0 / 3.0,
    "TDMax": 1.0,
    "TDMin": -1.0,
    "TDPP": 2.0,
    "TDEI": 3.0,
    # TDWC diverges (denominator trapz(x)=0), magnitude check only
    "TDHSK": 0.0,
}

# ---- TD fixture: x = [2, 2, 2] (constant) ----
# TDSTD=0, TDS=0 (0/0 → source has no eps → NaN guard needed),
# TDK: fourth_central=0, TDSTD^4=0 → 0/0; Pearson candidate = nan → source kurtosis(xc)=NaN
# Actually xc=[0,0,0], sum(xc^4)/N=0, TDSTD^4=0 → division undefined.
# MATLAB kurtosis(xc) on constant vector = NaN (0/0).
# TDV = np.var ddof=1 = 0
# TDEI = trapz([4,4,4]) = 4+4 = 8
# TDWC = trapz([0,2,4])/trapz([2,2,2]) = (1+3)/(2+2) = 4/4 = 1
TD_X222_PARTIAL = {
    "TDM": 2.0,
    "TDSTD": 0.0,
    "TDRMS2": 4.0,
    "TDMAV": 2.0,
    "TDV": 0.0,
    "TDMax": 2.0,
    "TDMin": 2.0,
    "TDPP": 0.0,
    "TDEI": 8.0,
    "TDWC": 1.0,
}

# ---- FD fixture: f = [0,1,2,3], y = [1,2,3,4] ----
# M=4, mean(y) = 2.5
# FDV = sum((y-2.5)^2)/4 = (2.25+0.25+0.25+2.25)/4 = 5/4 = 1.25
# FDS = sum((y-2.5)^3) / (4*(1.25^1.5+eps)) = (-3.375-0.125+0.125+3.375)/(4*(1.39754+eps)) = 0/(...) = 0
# (y-2.5)^4 = [5.0625, 0.0625, 0.0625, 5.0625] sum = 10.25
# FDK = 10.25 / (4*(1.5625+eps)) = 1.64
# FDAF = sum(f*y)/(sum(y)+eps) = (0*1+1*2+2*3+3*4)/(10+eps) = 20/10 = 2
# (f-2)^2 = [4,1,0,1]; sum((f-2)^2*y) = 4+2+0+4 = 10; FDSD = sqrt(10/10) = 1
# FDRMS = sqrt(sum(f^2*y)/10) = sqrt((0+2+12+36)/10) = sqrt(5)
# FDSR = sqrt(FDAF) = sqrt(2)
# FDCF = max(y)/(mean(y)+eps) = 4/2.5 = 1.6
# FDFSDR = FDSD/(FDAF+eps) = sqrt(0.6)/2
# (f-2)^3 = [-8,-1,0,1]; sum((f-2)^3*y) = -8-2+0+4 = -6
# FDFS = -6/((1^3+eps)*10) = -0.6
# (f-2)^4 = [16,1,0,1]; sum((f-2)^4*y) = 16+2+0+4 = 22
# FDFK = 22/((1^4+eps)*10) = 2.2
# FDEQ: y2=[1,4,9,16], sum=30, prob=y2/30
#   FDEQ = -sum(prob*log2(prob+eps))
# FDFWM = trapz(f*y, f) = trapz([0,2,6,12], f=[0,1,2,3]) = (0+2)/2+(2+6)/2+(6+12)/2
#        = 1+4+9 = 14
#   trapz(y, f) = trapz([1,2,3,4], [0,1,2,3]) = 1.5+2.5+3.5 = 7.5
#   FDFWM = 14/7.5 = 1.8667
import numpy as np

_EPS = np.finfo(np.float64).eps
_f = np.array([0.0, 1.0, 2.0, 3.0])
_y = np.array([1.0, 2.0, 3.0, 4.0])
_y2 = _y ** 2
_prob = _y2 / (np.sum(_y2) + _EPS)
_fdaf = np.sum(_f * _y) / (np.sum(_y) + _EPS)
_fdsd = float(np.sqrt(np.sum((_f - _fdaf) ** 2 * _y) / (np.sum(_y) + _EPS)))

FD_F0123 = {
    "FDM": 2.5,
    "FDV": 1.25,
    "FDS": 0.0,
    "FDK": 10.25 / (4 * (1.25 ** 2 + _EPS)),
    "FDAF": 2.0,
    "FDSD": _fdsd,
    "FDRMS": 5.0 ** 0.5,
    "FDSR": 2.0 ** 0.5,
    "FDCF": 1.6,
    "FDFSDR": _fdsd / (2.0 + _EPS),  # FDSD=1
    "FDFS": -0.6,
    "FDFK": (16 * 1 + 1 * 2 + 0 * 3 + 1 * 4) / ((_fdsd ** 4 + _EPS) * 10),
    "FDEQ": float(-np.sum(_prob * np.log2(_prob + _EPS))),
    "FDFWM": 14.0 / 7.5,
}

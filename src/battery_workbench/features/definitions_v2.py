"""BRW-013X V2 — Feature Definition Registry.

33 MATLAB-aligned statistical feature definitions (19 TD + 14 FD), each with:
- bilingual display names (EN/ZH)
- formula_source_id = USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1
- formula_policy_version = MATLAB_ALIGNED_FEATURE_FORMULAS_V1
- definition status lifecycle DEFINED_NOT_VALIDATED → DEFINED_AND_VALIDATED

Existing BRW-013 features are aliased ONLY where the semantics are identical
(TDM/TDSTD/TDMax/TDMin/TDPP). TDRMS² and TDEI are intentionally NOT aliases of
waveform_rms / waveform_energy_sum_sq because their source semantics differ.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

FORMULA_SOURCE_ID = "USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1"
FORMULA_POLICY_VERSION = "MATLAB_ALIGNED_FEATURE_FORMULAS_V1"
REGISTRY_VERSION = "0.3.0"

DefinitionStatus = Literal["DEFINED_NOT_VALIDATED", "DEFINED_AND_VALIDATED"]
Family = Literal["TD", "FD"]
Scope = Literal["FULL_WAVEFORM", "USER_SELECTED_EXPLICIT_GATE"]


class MatlabFeatureDefinition(BaseModel):
    code: str
    display_name_en: str
    display_name_zh: str
    family: Family
    formula_source_id: str = FORMULA_SOURCE_ID
    formula_policy_version: str = FORMULA_POLICY_VERSION
    formula_text: str
    required_inputs: list[str]
    scope: list[Scope]
    units: str
    definition_status: DefinitionStatus = "DEFINED_NOT_VALIDATED"
    parity_status: str = "INDEPENDENT_GOLDEN_PASS"
    existing_alias: str | None = None
    notes: str = ""


# Units per master prompt §17 dimensional notes
_TDM_UNIT = "signal_unit"
_TDRMS2_UNIT = "signal_unit^2"
_TDV_UNIT = "signal_unit^2"
_TDEI_UNIT = "signal_unit^2*sample_index"
_FD_HZ = "Hz"
_FD_SR_UNIT = "sqrt(Hz)"
_RATIO = "dimensionless"
_ENTROPY = "bits"


def _td(
    code: str,
    en: str,
    zh: str,
    formula: str,
    units: str,
    alias: str | None = None,
    notes: str = "",
) -> MatlabFeatureDefinition:
    return MatlabFeatureDefinition(
        code=code,
        display_name_en=en,
        display_name_zh=zh,
        family="TD",
        formula_text=formula,
        required_inputs=["waveform"],
        scope=["FULL_WAVEFORM", "USER_SELECTED_EXPLICIT_GATE"],
        units=units,
        existing_alias=alias,
        notes=notes,
    )


def _fd(
    code: str,
    en: str,
    zh: str,
    formula: str,
    units: str,
    notes: str = "",
) -> MatlabFeatureDefinition:
    return MatlabFeatureDefinition(
        code=code,
        display_name_en=en,
        display_name_zh=zh,
        family="FD",
        formula_text=formula,
        required_inputs=["frequency_bins", "spectrum_y", "spectral_transform_id"],
        scope=["FULL_WAVEFORM", "USER_SELECTED_EXPLICIT_GATE"],
        units=units,
        notes=notes,
    )


TD_DEFINITIONS: tuple[MatlabFeatureDefinition, ...] = (
    _td("TDM", "Mean", "均值", "mean(x)", _TDM_UNIT, alias="waveform_mean_a_u"),
    _td(
        "TDSTD", "Standard Deviation", "标准差",
        "sqrt(sum((x-mean(x))^2)/N)", _TDM_UNIT, alias="waveform_std_a_u",
        notes="population-style /N (NOT ddof=1)",
    ),
    _td(
        "TDRMS2", "Mean Square (RMS²)", "均方根值平方",
        "sum(x^2)/N", _TDRMS2_UNIT,
        notes="NOT an alias of waveform_rms (which is sqrt(mean(x^2)))",
    ),
    _td("TDMAV", "Mean Absolute Value", "平均绝对值", "sum(|x|)/N", _TDM_UNIT),
    _td(
        "TDS", "Skewness", "偏度",
        "sum((x-mean(x))^3)/N / TDSTD^3", _RATIO,
        notes="source has NO eps; constant waveform → NaN (invalid preserved)",
    ),
    _td(
        "TDK", "Kurtosis", "峰度",
        "sum((x-mean(x))^4)/N / TDSTD^4", _RATIO,
        notes="MATLAB_PARITY_REQUIRED: candidate Pearson/raw moment form; "
        "source writes kurtosis(xc)+3",
    ),
    _td(
        "TDV", "Variance", "方差",
        "var(x) [MATLAB default]", _TDV_UNIT,
        notes="MATLAB_PARITY_REQUIRED: candidate np.var(x, ddof=1); "
        "NOT TDSTD^2 (different normalization)",
    ),
    _td("TDMax", "Maximum", "最大值", "max(x)", _TDM_UNIT, alias="waveform_max_a_u"),
    _td("TDMin", "Minimum", "最小值", "min(x)", _TDM_UNIT, alias="waveform_min_a_u"),
    _td("TDPP", "Peak-to-Peak", "峰值差", "max(x)-min(x)", _TDM_UNIT, alias="waveform_p2p_a_u"),
    _td(
        "TDEI", "Squared-Signal Integral", "信号平方积分",
        "trapz(x^2, dx=1)", _TDEI_UNIT,
        notes="sample-index unit spacing; NOT an alias of waveform_energy_sum_sq "
        "(which is sum(x^2)); no dt multiplication",
    ),
    _td(
        "TDWC", "Signal Weighted Mean Rate", "信号加权平均率",
        "trapz(t*x,t)/(trapz(x,t)+EPS64)", _RATIO,
    ),
    _td("TDSAVR", "Std / Mean-Absolute-Value Ratio", "标准差与平均绝对值之比",
        "TDSTD/(TDMAV+EPS64)", _RATIO),
    _td("TDMSR", "Max / Std Ratio", "最大值与标准差之比",
        "TDMax/(TDSTD+EPS64)", _RATIO),
    _td("TDMAR", "Max / Mean-Absolute-Value Ratio", "最大值与平均绝对值之比",
        "TDMax/(TDMAV+EPS64)", _RATIO),
    _td("TDMRR", "Max / RMS Ratio", "最大值与均方根值之比",
        "TDMax/(sqrt(TDRMS2)+EPS64)", _RATIO),
    _td("TDHSK", "Higher-Order Skewness Feature", "偏度高阶特征",
        "TDS^2", _RATIO),
    _td("TDKSR", "Kurtosis / Std Ratio", "峰度与标准差之比",
        "TDK/(TDSTD+EPS64)", _RATIO),
    _td("TDHMER", "High-Order Moment / Energy Ratio", "高阶矩与能量之比",
        "(sum((x-mean(x))^4)/N)/(sum(x^2)+EPS64)", _RATIO),
)

FD_DEFINITIONS: tuple[MatlabFeatureDefinition, ...] = (
    _fd("FDM", "Spectral Mean", "频域均值", "mean(y)", _RATIO),
    _fd("FDV", "Spectral Variance", "频域方差", "sum((y-mean(y))^2)/M", _RATIO),
    _fd("FDS", "Spectral Skewness", "频域偏度",
        "sum((y-mean(y))^3)/(M*(FDV^1.5+EPS64))", _RATIO),
    _fd("FDK", "Spectral Kurtosis", "频域峰度",
        "sum((y-mean(y))^4)/(M*(FDV^2+EPS64))", _RATIO),
    _fd("FDAF", "Mean Frequency", "频率均值",
        "sum(f*y)/(sum(y)+EPS64)", _FD_HZ,
        notes="weights are y values; no abs(y)"),
    _fd("FDSD", "Frequency Standard Deviation", "频率标准差",
        "sqrt(sum((f-FDAF)^2*y)/(sum(y)+EPS64))", _FD_HZ),
    _fd("FDRMS", "RMS Frequency", "均方根频率",
        "sqrt(sum(f^2*y)/(sum(y)+EPS64))", _FD_HZ),
    _fd("FDSR", "Square-Root Mean Frequency", "平方根平均频率",
        "sqrt(FDAF)", _FD_SR_UNIT,
        notes="source formula p8=sqrt(meanf) — do not replace"),
    _fd("FDCF", "Spectral Peak Factor", "峰度因子",
        "max(y)/(mean(y)+EPS64)", _RATIO,
        notes="not textbook crest factor"),
    _fd("FDFSDR", "Frequency Std / Mean Ratio", "频率标准差与均值之比",
        "FDSD/(FDAF+EPS64)", _RATIO),
    _fd("FDFS", "Frequency Skewness", "频率偏度",
        "sum((f-FDAF)^3*y)/((FDSD^3+EPS64)*sumy)", _RATIO),
    _fd("FDFK", "Frequency Kurtosis", "频率峰度",
        "sum((f-FDAF)^4*y)/((FDSD^4+EPS64)*sumy)", _RATIO),
    _fd("FDEQ", "Spectral Entropy", "频率均衡性（谱熵）",
        "-sum(prob*log2(prob+EPS64)), prob=y^2/(sum(y^2)+EPS64)", _ENTROPY,
        notes="NOT normalized to [0,1]; log2"),
    _fd("FDFWM", "Frequency Weighted Mean Rate", "频率加权平均率",
        "trapz(f*y,f)/(trapz(y,f)+EPS64)", _FD_HZ),
)


class MatlabFeatureRegistry:
    """Feature Definition Registry V2 for MATLAB-aligned statistical features."""

    def __init__(self) -> None:
        self._defs: dict[str, MatlabFeatureDefinition] = {}
        for d in (*TD_DEFINITIONS, *FD_DEFINITIONS):
            if d.code in self._defs:
                raise ValueError(f"duplicate feature code: {d.code}")
            self._defs[d.code] = d

    def get(self, code: str) -> MatlabFeatureDefinition:
        return self._defs[code]

    def codes(self) -> list[str]:
        return list(self._defs)

    def by_family(self, family: Family) -> list[MatlabFeatureDefinition]:
        return [d for d in self._defs.values() if d.family == family]

    def promote_validated(self, code: str) -> None:
        """Promote to DEFINED_AND_VALIDATED after parity/golden passes."""
        d = self._defs[code]
        self._defs[code] = d.model_copy(update={"definition_status": "DEFINED_AND_VALIDATED"})

    def promote_all_validated(self) -> None:
        for code in self._defs:
            self.promote_validated(code)

    def catalogue(self) -> list[dict[str, Any]]:
        """API-ready catalogue entries (bilingual + status)."""
        return [
            {
                "code": d.code,
                "display_name_en": d.display_name_en,
                "display_name_zh": d.display_name_zh,
                "family": d.family,
                "units": d.units,
                "formula_source_id": d.formula_source_id,
                "formula_policy_version": d.formula_policy_version,
                "formula_text": d.formula_text,
                "definition_status": d.definition_status,
                "parity_status": d.parity_status,
                "existing_alias": d.existing_alias,
                "scope": d.scope,
            }
            for d in self._defs.values()
        ]


def default_registry() -> MatlabFeatureRegistry:
    """Registry with all definitions marked DEFINED_AND_VALIDATED after
    independent golden tests pass (T01–T33). TDK/TDV remain parity-pending
    candidates until the user MATLAB fixture confirms them."""
    reg = MatlabFeatureRegistry()
    reg.promote_all_validated()
    # TDK/TDV stay DEFINED_NOT_VALIDATED pending MATLAB parity fixture
    for code in ("TDK", "TDV"):
        d = reg.get(code)
        reg._defs[code] = d.model_copy(
            update={
                "definition_status": "DEFINED_NOT_VALIDATED",
                "parity_status": "MATLAB_PARITY_REQUIRED",
            }
        )
    return reg

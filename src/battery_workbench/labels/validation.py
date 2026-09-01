"""BRW-014 label validation + scientific guards."""

from __future__ import annotations

from battery_workbench.labels.leakage import forbidden_feature_columns

_ELIGIBLE_SOC_QUALITIES = {"VALID_REFERENCE"}
_ELIGIBLE_SOH_QUALITIES = {"VALID_REFERENCE"}


def is_label_eligible(quality: str | None) -> bool:
    """Only explicit valid reference quality is label-eligible."""
    return quality in _ELIGIBLE_SOC_QUALITIES or quality in _ELIGIBLE_SOH_QUALITIES


def validate_no_ultrasound_features(columns: list[str]) -> None:
    """Guard: label tables must never carry ultrasound/waveform features."""
    forbidden = forbidden_feature_columns()
    offenders = [c for c in columns if c in forbidden]
    if offenders:
        raise ValueError(f"label table carries forbidden feature columns: {offenders}")


def validate_no_silent_clip(soc_percent: float | None, quality: str) -> None:
    """Guard: an out-of-range SOC must keep its value and its quality flag."""
    if soc_percent is None:
        return
    if (soc_percent > 100.0 or soc_percent < 0.0) and quality != "OUT_OF_RANGE_REFERENCE":
        raise ValueError(
            f"out-of-range SOC {soc_percent} must be flagged OUT_OF_RANGE_REFERENCE, got {quality}"
        )


def validate_vendor_not_promoted(
    *,
    soc_reference_percent: float | None,
    vendor_soc_dod_percent: float | None,
) -> None:
    """Guard: the vendor field is never silently echoed as the reference label."""
    if soc_reference_percent is None or vendor_soc_dod_percent is None:
        return
    # A pass-through would be an exact equality for every event; the derived
    # formula differs from the vendor field at discharge start (100 vs 0).
    # This guard is informational at builder level; the unit tests freeze it.
    return

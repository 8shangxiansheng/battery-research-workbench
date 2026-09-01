"""BRW-017 V2 Feature Registry — canonical catalog of available features.

Two tiers:
  CORE: user-visible primary features (tof_us, amplitude_a_u)
  AUXILIARY: existing BRW-013 sample-domain features (13 predictors)

TOF/PHYSICAL entries are registered but gated on parameters.
The legacy 13 BRW-016 predictors are preserved as the AUXILIARY tier.
"""

from __future__ import annotations

from battery_workbench.feature_registry.schemas import (
    AvailabilityStatus,
    FeatureGroup,
    FeatureRegistryEntry,
)

# --- Core features (user-visible primary) ---

CORE_FEATURES: list[FeatureRegistryEntry] = [
    FeatureRegistryEntry(
        feature_name="tof_us",
        feature_group=FeatureGroup.TOF,
        description=(
            "ABSOLUTE ARRIVAL-BASED FLIGHT TIME ESTIMATE: "
            "(arrival_sample_index - trigger_sample_index) / fs * 1e6. "
            "Never populated from xcorr_shift_samples (relative shift, not flight time)."
        ),
        unit="us",
        dtype="float64",
        source_engine="BRW-017",
        source_columns=[
            "arrival_sample_index",
            "ultrasound.trigger_sample_index",
            "ultrasound.sampling_rate_hz",
        ],
        requires_parameters=[
            "ultrasound.sampling_rate_hz",
            "ultrasound.trigger_sample_index",
        ],
        requires_capabilities=["arrival_detector"],
        availability_status=AvailabilityStatus.UNAVAILABLE_ALGORITHM_NOT_VALIDATED,
        availability_reason=("requires fs AND trigger/time-zero AND validated arrival detector"),
        scientific_role="predictor",
        default_predictor_eligible=True,
        is_core=True,
    ),
    FeatureRegistryEntry(
        feature_name="amplitude_a_u",
        feature_group=FeatureGroup.AMPLITUDE,
        description="Peak absolute amplitude (alias for waveform_abs_peak_a_u)",
        unit="a.u.",
        dtype="float64",
        source_engine="BRW-013",
        source_columns=["waveform_abs_peak_a_u"],
        scientific_role="predictor",
        default_predictor_eligible=True,
        is_core=True,
    ),
]

# --- Auxiliary features (existing BRW-013 sample-domain, non-core by default) ---

_AUX_NAMES = [
    "waveform_min_a_u",
    "waveform_max_a_u",
    "waveform_mean_a_u",
    "waveform_std_a_u",
    "waveform_rms_a_u",
    "waveform_p2p_a_u",
    "waveform_abs_peak_a_u",
    "waveform_energy_sum_sq_a_u2",
    "envelope_peak_a_u",
    "envelope_peak_sample_index",
    "xcorr_shift_samples",
    "xcorr_peak_coefficient",
]
_AUX_UNITS = {
    "waveform_min_a_u": "a.u.",
    "waveform_max_a_u": "a.u.",
    "waveform_mean_a_u": "a.u.",
    "waveform_std_a_u": "a.u.",
    "waveform_rms_a_u": "a.u.",
    "waveform_p2p_a_u": "a.u.",
    "waveform_abs_peak_a_u": "a.u.",
    "waveform_energy_sum_sq_a_u2": "a.u.^2*sample",
    "envelope_peak_a_u": "a.u.",
    "envelope_peak_sample_index": "sample",
    "xcorr_shift_samples": "samples",
    "xcorr_peak_coefficient": "dimensionless",
}
_AUX_DTYPES = {
    "waveform_abs_peak_sample_index": "int64",
    "envelope_peak_sample_index": "int64",
    "xcorr_shift_samples": "int64",
}

AUXILIARY_FEATURES: list[FeatureRegistryEntry] = [
    FeatureRegistryEntry(
        feature_name=name,
        feature_group=FeatureGroup.SAMPLE_TEMPORAL
        if ("index" in name or "xcorr" in name)
        else FeatureGroup.AMPLITUDE,
        description="Auxiliary BRW-013 sample-domain feature",
        unit=_AUX_UNITS.get(name, "a.u."),
        dtype=_AUX_DTYPES.get(name, "float64"),
        source_engine="BRW-013",
        source_columns=[name],
        scientific_role="predictor",
        default_predictor_eligible=False,  # auxiliary: not in default dataset
        is_core=False,
    )
    for name in _AUX_NAMES
]

# --- PHYSICAL placeholder (optional derived feature, capability-gated) ---

PHYSICAL_PLACEHOLDER_FEATURES: list[FeatureRegistryEntry] = [
    FeatureRegistryEntry(
        feature_name="wave_speed_m_s",
        feature_group=FeatureGroup.PHYSICAL,
        description="Ultrasonic wave speed",
        unit="m/s",
        requires_parameters=["experiment.ultrasound_path_length_m"],
        requires_capabilities=["wave_speed"],
        availability_status=AvailabilityStatus.UNAVAILABLE_MISSING_PARAMETER,
        availability_reason="path length is UNKNOWN",
        default_predictor_eligible=False,
    ),
]

ALL_REGISTRY_ENTRIES = CORE_FEATURES + AUXILIARY_FEATURES + PHYSICAL_PLACEHOLDER_FEATURES

_REGISTRY = {e.feature_name: e for e in ALL_REGISTRY_ENTRIES}


def get_registry_entry(feature_name: str) -> FeatureRegistryEntry:
    if feature_name not in _REGISTRY:
        raise KeyError(f"unknown feature: {feature_name}")
    return _REGISTRY[feature_name]


def get_available_features() -> list[FeatureRegistryEntry]:
    return [
        e for e in ALL_REGISTRY_ENTRIES if e.availability_status == AvailabilityStatus.AVAILABLE
    ]


def get_missing_parameters_for(
    feature_names: list[str],
    *,
    available: set[str] | None = None,
) -> list[str]:
    """Return the parameters to prompt for, in progressive order.

    Per unavailable feature, only the FIRST still-missing parameter (in the
    feature's declared ``requires_parameters`` order) is returned — the user
    supplies fs first, then trigger. ``available`` carries parameters already
    provided so later prompts surface stepwise. Algorithm capabilities
    (arrival detector) are never user prompts and never appear here.
    """
    have = available or set()
    missing: list[str] = []
    for name in feature_names:
        entry = _REGISTRY.get(name)
        if entry is None:
            continue
        if entry.availability_status == AvailabilityStatus.AVAILABLE:
            continue
        for param in entry.requires_parameters:
            if param not in have:
                if param not in missing:
                    missing.append(param)
                break  # progressive: one parameter per feature per round
    return missing

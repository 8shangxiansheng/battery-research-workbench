"""Canonical parameter catalog for BRW-015.

Each parameter carries a frozen ``resolution_policy`` encoding the user
principle: only parameters that directly change scientific results AND cannot
be reliably obtained from data accept user configuration; data-factual values
are AUTO_ONLY; derivations require verified premises; everything else stays
UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass

from battery_workbench.parameters.schemas import ResolutionPolicy


@dataclass(frozen=True)
class ParameterSpec:
    canonical_name: str
    unit: str
    dimension: str
    critical: bool = False
    resolution_policy: ResolutionPolicy = ResolutionPolicy.USER_ONLY
    auto_source: str | None = None  # where auto-read collects the value from
    description: str = ""


CANONICAL_PARAMETERS: list[ParameterSpec] = [
    # --- Ultrasound (sampling/acquisition) ---
    ParameterSpec(
        "ultrasound.sampling_rate_hz",
        "Hz",
        "frequency",
        critical=True,
        resolution_policy=ResolutionPolicy.AUTO_READ_THEN_USER,
        auto_source="parser_manifest_assets",
        description="Waveform sampling rate; 1250 samples / 10 s cadence can never provide it",
    ),
    ParameterSpec(
        "ultrasound.trigger_sample_index",
        "sample",
        "sample_index",
        critical=True,
        resolution_policy=ResolutionPolicy.USER_ONLY,
        description="Trigger / time-zero sample index",
    ),
    ParameterSpec(
        "ultrasound.acquisition_window_samples",
        "sample",
        "sample_index",
        critical=False,
        resolution_policy=ResolutionPolicy.AUTO_ONLY,
        auto_source="zarr_waveform_shape",
        description="Waveform record length (data-factual)",
    ),
    ParameterSpec(
        "ultrasound.acquisition_window_s",
        "s",
        "time",
        critical=False,
        resolution_policy=ResolutionPolicy.DERIVED_ONLY,
        description="Record duration = samples / fs; requires VERIFIED fs",
    ),
    ParameterSpec(
        "ultrasound.pretrigger_samples",
        "sample",
        "sample_index",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.pulse_center_frequency_hz",
        "Hz",
        "frequency",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.transducer_center_frequency_hz",
        "Hz",
        "frequency",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.transducer_model",
        "text",
        "text",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.waveform_gain_db",
        "dB",
        "gain",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    # --- Delay / calibration ---
    ParameterSpec(
        "ultrasound.system_delay_s",
        "s",
        "time",
        critical=True,
        resolution_policy=ResolutionPolicy.USER_ONLY,
        description="System delay calibration (total or component-derived per policy)",
    ),
    ParameterSpec(
        "ultrasound.cable_delay_s",
        "s",
        "time",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.transducer_delay_s",
        "s",
        "time",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "ultrasound.time_zero_offset_s",
        "s",
        "time",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    # --- Geometry ---
    ParameterSpec(
        "experiment.ultrasound_path_length_m",
        "m",
        "length",
        critical=True,
        resolution_policy=ResolutionPolicy.USER_ONLY,
        description="Acoustic path length; cell thickness is never a substitute",
    ),
    ParameterSpec(
        "experiment.cell_thickness_m",
        "m",
        "length",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "experiment.transducer_spacing_m",
        "m",
        "length",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    # --- Battery / labels ---
    ParameterSpec(
        "battery.nominal_capacity_ah",
        "Ah",
        "capacity",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
        description="Vendor nominal capacity; never guessed",
    ),
    ParameterSpec(
        "battery.rated_capacity_ah",
        "Ah",
        "capacity",
        critical=False,
        resolution_policy=ResolutionPolicy.USER_ONLY,
    ),
    ParameterSpec(
        "battery.reference_capacity_ah",
        "Ah",
        "capacity",
        critical=True,
        resolution_policy=ResolutionPolicy.AUTO_ONLY,
        auto_source="label_manifest",
        description="SOH reference capacity as already derived by BRW-014 (BASELINE_CYCLE)",
    ),
    ParameterSpec(
        "labels.rpt_capacity_ah",
        "Ah",
        "capacity",
        critical=True,
        resolution_policy=ResolutionPolicy.USER_ONLY,
        description="RPT capacity from an independent reference test",
    ),
    ParameterSpec(
        "labels.reference_cycle_index",
        "sample",
        "sample_index",
        critical=False,
        resolution_policy=ResolutionPolicy.AUTO_ONLY,
        auto_source="label_manifest",
        description="Baseline reference cycle chosen by BRW-014",
    ),
    ParameterSpec(
        "labels.reference_capacity_policy",
        "text",
        "text",
        critical=False,
        resolution_policy=ResolutionPolicy.AUTO_ONLY,
        auto_source="label_manifest",
        description="Explicit reference policy; parameter existence never changes it",
    ),
]

_CATALOG = {p.canonical_name: p for p in CANONICAL_PARAMETERS}


def get_spec(canonical_name: str) -> ParameterSpec:
    if canonical_name not in _CATALOG:
        raise KeyError(f"unknown canonical parameter: {canonical_name}")
    return _CATALOG[canonical_name]


def is_critical(canonical_name: str) -> bool:
    return _CATALOG[canonical_name].critical


def parameters_with_policy(policy: ResolutionPolicy) -> list[ParameterSpec]:
    return [p for p in CANONICAL_PARAMETERS if p.resolution_policy == policy]

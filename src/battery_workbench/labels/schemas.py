"""Typed models for BRW-014 Reference Label Engine (SOC/SOH) + TOF readiness.

V1 produces *derived reference labels* from electrical protocol/capacity
measurements only. These are NOT ground-truth claims: no ``true_soc`` /
``true_soh`` semantics exist here. Labels never carry ultrasound features.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

SocQuality = Literal[
    "VALID_REFERENCE",
    "ANCHOR_UNAVAILABLE",
    "REFERENCE_CAPACITY_UNAVAILABLE",
    "INCOMPLETE_CYCLE",
    "OUT_OF_RANGE_REFERENCE",
    "AMBIGUOUS_PROTOCOL",
    "VENDOR_FIELD_ONLY",
]
SocTemporality = Literal[
    "RETROSPECTIVE_FULL_CYCLE_REFERENCE",
    "ONLINE_CAUSAL_REFERENCE",
]
SocDirection = Literal["DISCHARGE", "CHARGE", "REST"]
ReferenceScope = Literal[
    "WITHIN_EXPERIMENT_BASELINE",
    "EXTERNAL_METADATA",
    "RPT",
    "TRAIN_ONLY_ESTIMATE",
]
TofStatus = Literal[
    "BLOCKED_MISSING_SAMPLING_RATE",
    "BLOCKED_MISSING_TIME_ZERO",
    "BLOCKED_MISSING_CALIBRATION",
    "READY_FOR_RELATIVE_SAMPLE_SHIFT_ONLY",
    "READY_FOR_ABSOLUTE_TOF_DEVELOPMENT",
]
SliceStatus = Literal["READY", "PASS_WITH_WARNINGS", "PARTIAL", "FAILED", "EMPTY"]


class SocConfig(BaseModel):
    method: str = "COULOMB_COUNTING_PROTOCOL_ANCHORED"
    formula_version: str = "0.1.0"
    promote_vendor_soc_dod: bool = False


class SohConfig(BaseModel):
    method: str = "CAPACITY_BASELINE_RATIO"
    formula_version: str = "0.1.0"
    reference_capacity_source: str = "BASELINE_CYCLE"
    rpt_capacity_ah: float | None = None


class LeakageConfig(BaseModel):
    frame_random_split_prohibited: bool = True


class TofConfig(BaseModel):
    reserved_algorithm_version: str = "0.1.0-reserved"


class LabelConfig(BaseModel):
    version: str = "0.1.0"
    label_definition_version: str = "0.1.0"
    soc: SocConfig = Field(default_factory=SocConfig)
    soh: SohConfig = Field(default_factory=SohConfig)
    leakage: LeakageConfig = Field(default_factory=LeakageConfig)
    tof: TofConfig = Field(default_factory=TofConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> LabelConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "reference_labels" in payload:
            payload = payload["reference_labels"]
        return cls.model_validate(payload)


class EventLabel(BaseModel):
    """One label row per MeasurementEvent (no ultrasound features)."""

    measurement_event_id: str
    battery_id: str
    experiment_id: str
    cycle_index_raw: float | None = None
    step_index_raw: float | None = None
    event_order_index: int | None = None

    # SOC.
    soc_reference_percent: float | None = None
    soc_reference_method: str | None = None
    soc_reference_capacity_ah: float | None = None
    soc_anchor_type: str | None = None
    soc_anchor_event_id: str | None = None
    soc_direction: SocDirection | None = None
    soc_label_temporality: SocTemporality | None = None
    soc_reference_quality: SocQuality | None = None
    soc_label_eligible: bool = False
    soc_formula_version: str | None = None

    # SOH (propagated from cycle labels by exact key join).
    soh_capacity_reference_percent: float | None = None
    soh_reference_capacity_ah: float | None = None
    soh_reference_cycle_index: int | None = None
    soh_reference_method: str | None = None
    soh_reference_quality: str | None = None
    soh_label_eligible: bool = False
    soh_formula_version: str | None = None

    # Leakage isolation groups.
    battery_group_id: str | None = None
    experiment_group_id: str | None = None
    cycle_group_id: str | None = None
    label_group_id: str | None = None


class CycleLabel(BaseModel):
    battery_id: str
    experiment_id: str
    cycle_index_raw: float
    cycle_complete: bool

    charge_capacity_measured_ah: float | None = None
    discharge_capacity_measured_ah: float | None = None

    reference_capacity_ah: float | None = None
    reference_capacity_source: str | None = None
    reference_capacity_source_scope: str | None = None

    soh_capacity_reference_percent: float | None = None
    soh_reference_method: str | None = None
    soh_reference_quality: str | None = None
    soh_formula_version: str | None = None
    soh_label_eligible: bool = False


class TofReadiness(BaseModel):
    absolute_tof_status: TofStatus
    sampling_rate_hz: float | None = None
    sampling_rate_source: str | None = None
    trigger_zero_available: bool = False
    trigger_zero_source: str | None = None
    system_delay_calibration_available: bool = False
    transducer_delay_metadata_available: bool = False
    cable_delay_metadata_available: bool = False
    waveform_sample_count: int | None = None
    arrival_detector_status: str = "NOT_SELECTED"
    tof_algorithm_reserved_version: str = "0.1.0-reserved"
    blocking_reasons: list[str] = Field(default_factory=list)
    frame_acquisition_interval_s: float | None = None
    frame_acquisition_interval_is_waveform_period: bool = False
    xcorr_shift_is_absolute_tof: bool = False
    physical_time_features_available: bool = False


class LabelManifest(BaseModel):
    label_engine_name: str = "reference_label_engine"
    label_engine_version: str = "0.1.0"
    label_set_id: str
    battery_id: str
    experiment_id: str
    input_paths: dict[str, str] = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)
    soc_method: str | None = None
    soc_formula_version: str | None = None
    soc_temporality: str | None = None
    soc_anchor: str | None = None
    soc_q_ref: float | None = None
    soc_valid_count: int = 0
    soc_null_count: int = 0
    soc_ineligible_count: int = 0
    soh_method: str | None = None
    soh_formula_version: str | None = None
    soh_reference_source: str | None = None
    soh_reference_cycle: int | None = None
    soh_reference_capacity_ah: float | None = None
    soh_independent_state_count: int = 0
    frame_random_split_prohibited: bool = True
    group_fields: list[str] = Field(default_factory=list)
    reference_scope: str | None = None
    tof_readiness: dict[str, Any] = Field(default_factory=dict)
    output_paths: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class LabelReport(BaseModel):
    label_set_id: str
    battery_id: str
    experiment_id: str
    label_engine_version: str
    status: SliceStatus
    event_label_count: int
    cycle_label_count: int
    soc_valid_count: int = 0
    soc_ineligible_count: int = 0
    soh_independent_state_count: int = 0
    vendor_diagnostic: dict[str, Any] = Field(default_factory=dict)
    frame_random_split_prohibited: bool = True
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CycleLabel",
    "EventLabel",
    "LabelConfig",
    "LabelManifest",
    "LabelReport",
    "ReferenceScope",
    "SliceStatus",
    "SocDirection",
    "SocQuality",
    "SocTemporality",
    "TofReadiness",
    "TofStatus",
]

"""Typed models for BRW-012 Condition Slice Engine.

Condition slicing is *deterministic data selection* over MeasurementEvents — it
performs no feature extraction, waveform processing, synchronization, or
scientific conclusion. Slice identity is a deterministic digest of the input
checksum + normalized spec.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

SliceStatus = Literal["READY", "READY_WITH_WARNINGS", "EMPTY", "FAILED"]


class ConditionSliceSpec(BaseModel):
    """A declarative, typed filter over canonical MeasurementEvents."""

    # Identity.
    battery_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    ultrasound_asset_ids: list[str] = Field(default_factory=list)

    # Quality.
    analysis_eligible_only: bool = True
    event_quality_statuses: list[str] = Field(default_factory=list)
    max_sync_error_s: float | None = None
    boundary_flag: bool | None = None

    # Protocol.
    cycle_indices: list[int] = Field(default_factory=list)
    step_indices: list[int] = Field(default_factory=list)
    step_types: list[str] = Field(default_factory=list)

    # Numeric electrical ranges (inclusive).
    voltage_v_min: float | None = None
    voltage_v_max: float | None = None
    current_a_min: float | None = None
    current_a_max: float | None = None
    capacity_ah_min: float | None = None
    capacity_ah_max: float | None = None
    temperature_c_min: float | None = None
    temperature_c_max: float | None = None
    soc_dod_percent_min: float | None = None
    soc_dod_percent_max: float | None = None

    # Time.
    elapsed_time_s_min: float | None = None
    elapsed_time_s_max: float | None = None
    provisional_timestamp_start: datetime | None = None
    provisional_timestamp_end: datetime | None = None

    # Null policy.
    include_null_numeric_values: bool = False


class SliceDefaultsConfig(BaseModel):
    analysis_eligible_only: bool = True
    include_null_numeric_values: bool = False
    exclude_boundaries: bool = False


class ScientificGuardConfig(BaseModel):
    allow_resynchronization: bool = False
    allow_measurement_event_rebuild: bool = False
    allow_waveform_processing: bool = False
    allow_feature_extraction: bool = False


class AnalysisSliceConfig(BaseModel):
    version: str = "0.1.0"
    defaults: SliceDefaultsConfig = Field(default_factory=SliceDefaultsConfig)
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AnalysisSliceConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "analysis_slice" in payload:
            payload = payload["analysis_slice"]
        return cls.model_validate(payload)


class AnalysisSlice(BaseModel):
    """The canonical slice metadata carried on output rows and reports."""

    analysis_slice_id: str
    battery_id: str
    experiment_id: str
    requested_spec: dict[str, Any]
    normalized_spec: dict[str, Any]
    status: SliceStatus
    input_row_count: int = 0
    output_row_count: int = 0
    excluded_row_count: int = 0
    filter_breakdown: dict[str, int] = Field(default_factory=dict)


class AnalysisSliceManifest(BaseModel):
    slice_engine_name: str = "analysis_slice_engine"
    slice_engine_version: str = "0.1.0"
    analysis_slice_id: str
    battery_id: str
    experiment_id: str
    input_path: str
    input_checksum: str
    input_row_count: int
    requested_spec: dict[str, Any]
    normalized_spec: dict[str, Any]
    output_path: str
    output_checksum: str
    output_row_count: int
    excluded_row_count: int
    filter_breakdown: dict[str, int]
    included_quality_statuses: list[str]
    analysis_eligible_only: bool
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnalysisSliceReport(BaseModel):
    analysis_slice_id: str
    battery_id: str
    experiment_id: str
    slice_engine_version: str
    status: SliceStatus
    input_row_count: int
    output_row_count: int
    excluded_row_count: int
    filter_breakdown: dict[str, int]
    requested_spec: dict[str, Any]
    normalized_spec: dict[str, Any]
    analysis_eligible_only: bool
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AnalysisSlice",
    "AnalysisSliceConfig",
    "AnalysisSliceManifest",
    "AnalysisSliceReport",
    "ConditionSliceSpec",
    "ScientificGuardConfig",
    "SliceDefaultsConfig",
    "SliceStatus",
]

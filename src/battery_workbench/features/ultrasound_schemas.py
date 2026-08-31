"""Typed models for BRW-013 Ultrasound Feature Engine (Sample-Domain V1).

One feature row = one AnalysisSlice event = one waveform. Feature extraction is
sample-domain only: no physical time/frequency features are emitted because the
waveform sampling rate is unknown. Scientific conclusion is out of scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

FeatureStatus = Literal["READY", "NONFINITE_WAVEFORM", "CONSTANT_WAVEFORM"]
SliceStatus = Literal["READY", "READY_WITH_WARNINGS", "EMPTY", "FAILED"]


class ScientificGuardConfig(BaseModel):
    allow_resynchronization: bool = False
    allow_filtering: bool = False
    allow_alignment: bool = False
    allow_physical_tof: bool = False
    allow_frequency: bool = False
    allow_measurement_event_rebuild: bool = False


class FeatureDefinition(BaseModel):
    """A single frozen scientific feature definition."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    formula: str = ""
    unit: str = ""
    dtype: str = "float64"
    requires_sampling_rate: bool = False
    preprocessing: str = ""
    null_behavior: str = ""


class XcorrConfig(BaseModel):
    reference_policy: str = "first_valid_by_event_order"
    mean_center_only: bool = True


class UltrasoundFeatureConfig(BaseModel):
    version: str = "0.1.0"
    feature_definition_version: str = "0.1.0"
    xcorr: XcorrConfig = Field(default_factory=XcorrConfig)
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> UltrasoundFeatureConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "ultrasound_features" in payload:
            payload = payload["ultrasound_features"]
        return cls.model_validate(payload)


class FeatureSetManifest(BaseModel):
    feature_engine_name: str = "ultrasound_feature_engine"
    feature_engine_version: str = "0.1.0"
    feature_set_id: str
    analysis_slice_id: str
    analysis_slice_path: str
    analysis_slice_checksum: str
    waveform_store_path: str
    waveform_store_checksum: str
    input_row_count: int
    output_row_count: int
    feature_definition_version: str = "0.1.0"
    feature_groups: list[str] = Field(default_factory=list)
    sampling_rate_hz: float | None = None
    physical_time_features_available: bool = False
    physical_frequency_features_available: bool = False
    xcorr_reference_policy: str = "first_valid_by_event_order"
    xcorr_references_per_asset: dict[str, str] = Field(default_factory=dict)
    output_paths: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    feature_missing_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class UltrasoundFeatureReport(BaseModel):
    feature_set_id: str
    analysis_slice_id: str
    battery_id: str
    experiment_id: str
    engine_version: str
    status: SliceStatus
    input_row_count: int
    output_row_count: int
    sampling_rate_hz: float | None = None
    physical_time_features_available: bool = False
    physical_frequency_features_available: bool = False
    xcorr_references_per_asset: dict[str, str] = Field(default_factory=dict)
    feature_status_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "FeatureDefinition",
    "FeatureSetManifest",
    "FeatureStatus",
    "ScientificGuardConfig",
    "SliceStatus",
    "UltrasoundFeatureConfig",
    "UltrasoundFeatureReport",
    "XcorrConfig",
]

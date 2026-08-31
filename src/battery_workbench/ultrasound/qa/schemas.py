from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class TemporalConfig(BaseModel):
    large_gap_factor: float = 2.5
    absolute_timestamp_tolerance_s: float = 1e-6


class OutlierConfig(BaseModel):
    method: Literal["mad"] = "mad"
    mad_k: float = 8.0


class WaveformConfig(BaseModel):
    all_zero_is_critical: bool = True
    constant_frame_is_warning: bool = True


class CorrelationConfig(BaseModel):
    low_adjacent_warning: float = 0.80


class SaturationConfig(BaseModel):
    adc_min: int | None = None
    adc_max: int | None = None
    extreme_plateau_warning_fraction: float = 0.05


class FigureConfig(BaseModel):
    overlay_frames: int = 30
    heatmap_max_frames: int = 1000
    format: str = "png"
    dpi: int = 150


class ScientificGuardConfig(BaseModel):
    allow_filtering: bool = False
    allow_alignment: bool = False
    allow_feature_dataset: bool = False
    require_sampling_rate_for_absolute_tof: bool = True
    require_sampling_rate_for_frequency_hz: bool = True


class UltrasoundQAConfig(BaseModel):
    version: str = "0.1.0"
    temporal: TemporalConfig = Field(default_factory=TemporalConfig)
    outlier: OutlierConfig = Field(default_factory=OutlierConfig)
    waveform: WaveformConfig = Field(default_factory=WaveformConfig)
    correlation: CorrelationConfig = Field(default_factory=CorrelationConfig)
    saturation: SaturationConfig = Field(default_factory=SaturationConfig)
    figures: FigureConfig = Field(default_factory=FigureConfig)
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> UltrasoundQAConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["ultrasound_qa"]
        return cls.model_validate(payload)


class QAAnomaly(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    scope: str
    asset_id: str | None = None
    frame_index_raw: int | None = None
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class QAAnomalyRegion(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    asset_id: str
    start_frame_index_raw: int
    end_frame_index_raw: int
    frame_count: int


class UltrasoundQAReport(BaseModel):
    battery_id: str
    experiment_id: str
    qa_version: str
    inputs: dict[str, Any]
    summary: dict[str, Any]
    schema_report: dict[str, Any] = Field(alias="schema")
    provenance: dict[str, Any]
    temporal: dict[str, Any]
    waveform: dict[str, Any]
    cross_frame: dict[str, Any]
    assets: list[dict[str, Any]]
    anomalies: list[QAAnomaly]
    anomaly_regions: list[QAAnomalyRegion]
    warnings: list[str]
    scientific_metadata: dict[str, Any]
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    artifacts: dict[str, str]
    configuration: dict[str, Any]

"""Typed models for BRW-009 Timestamp Construction Engine.

V1 clock model is ``OFFSET_ONLY``: absolute = anchor + (elapsed - elapsed_at_anchor),
with scale=1.0, offset_s=0.0, drift_enabled=False. ``validated_sync`` is always
``False`` — these are provisional absolute timestamps, never verified cross-modal
synchronization.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

ModelType = Literal["OFFSET_ONLY", "AFFINE"]
ReportStatus = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]


class ClockModel(BaseModel):
    """Deterministic clock model applied to one asset's elapsed frames."""

    model_type: ModelType = "OFFSET_ONLY"
    anchor_id: str | None = None
    anchor_datetime: datetime | None = None
    elapsed_time_s_at_anchor: float = 0.0
    scale: float = 1.0
    offset_s: float = 0.0
    drift_enabled: bool = False


class ClockConfig(BaseModel):
    model_type: ModelType = "OFFSET_ONLY"
    scale: float = 1.0
    offset_s: float = 0.0
    drift_enabled: bool = False


class ValidationConfig(BaseModel):
    legacy_timestamp_tolerance_s: float = 1e-6


class ScientificGuardConfig(BaseModel):
    """Hard guards; BRW-009 never performs matching, drift fit, or cycle mapping."""

    allow_electrical_matching: bool = False
    allow_sync_error: bool = False
    allow_drift_fit: bool = False
    allow_cycle_mapping: bool = False
    allow_verified_sync_status: bool = False


class TimestampEngineConfig(BaseModel):
    version: str = "0.1.0"
    clock: ClockConfig = Field(default_factory=ClockConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TimestampEngineConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["timestamp_engine"]
        return cls.model_validate(payload)


class TimestampEngineAssetResult(BaseModel):
    """Per-asset timing diagnostics."""

    asset_id: str
    frame_count: int
    timestamp_available_count: int
    timestamp_missing_count: int
    elapsed_min_s: float | None = None
    elapsed_max_s: float | None = None
    timestamp_min: datetime | None = None
    timestamp_max: datetime | None = None
    is_elapsed_strictly_increasing: bool = False
    is_timestamp_strictly_increasing: bool = False
    duplicate_elapsed_count: int = 0
    duplicate_timestamp_count: int = 0
    anchor_id: str | None = None
    anchor_status: str | None = None
    legacy_timestamp_compare_count: int = 0
    legacy_timestamp_max_abs_delta_s: float | None = None


class TimestampEngineReport(BaseModel):
    """Engine report, written as JSON/HTML artifacts and the manifest source."""

    battery_id: str
    experiment_id: str
    engine_version: str
    input_frame_count: int
    output_frame_count: int
    assets: list[TimestampEngineAssetResult]
    timestamp_available_count: int
    timestamp_missing_count: int
    clock_models: list[ClockModel]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: ReportStatus
    validated_sync: bool = False
    electrical_matching_performed: bool = False
    drift_correction_applied: bool = False
    cycle_mapping_performed: bool = False
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ClockConfig",
    "ClockModel",
    "ModelType",
    "ReportStatus",
    "ScientificGuardConfig",
    "TimestampEngineAssetResult",
    "TimestampEngineConfig",
    "TimestampEngineReport",
    "ValidationConfig",
]

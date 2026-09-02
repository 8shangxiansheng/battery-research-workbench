"""Typed models for BRW-010 Electrical–Ultrasound synchronization.

V1 nearest-record synchronization with explicit ambiguity preservation.
``validated_sync`` stays ``False``: matching uses a PROVISIONAL timebase and
does not establish independent clock verification.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

MatchStatus = Literal[
    "MATCHED_UNIQUE",
    "MATCHED_AMBIGUOUS",
    "OUT_OF_TOLERANCE",
    "TIMESTAMP_UNAVAILABLE",
    "NO_ELECTRICAL_CANDIDATE",
    "TIMEZONE_MISMATCH",
]
AmbiguityType = Literal[
    "NONE",
    "DUPLICATE_ELECTRICAL_TIMESTAMP",
    "EQUIDISTANT_TIMESTAMPS",
    "DUPLICATE_AND_EQUIDISTANT",
]
ReportStatus = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]


class NearestCandidate(BaseModel):
    """A single nearest candidate electrical timestamp for one ultrasound frame."""

    electrical_timestamp: datetime
    sync_error_s: float
    candidate_timestamp_rank: int = 1
    candidate_record_rank: int = 1
    within_tolerance: bool = False
    electrical_timestamp_duplicate_count: int = 1


class MatchingConfig(BaseModel):
    method: Literal["nearest"] = "nearest"
    max_sync_error_s: float = 1.0
    tie_tolerance_s: float = 1e-9
    ambiguous_selection: Literal["none"] = "none"


class BoundaryConfig(BaseModel):
    duplicate_timestamp_is_boundary: bool = True
    detect_cycle_transition: bool = True
    detect_step_transition: bool = True
    use_explicit_start_end_marker_if_available: bool = True


class ReportingConfig(BaseModel):
    sync_error_p95: bool = True
    required_figures: int = 4


class SyncScientificGuardConfig(BaseModel):
    allow_drift_correction: bool = False
    allow_interpolation: bool = False
    allow_cycle_based_matching: bool = False
    allow_step_based_matching: bool = False
    allow_measurement_event: bool = False
    allow_verified_sync_upgrade: bool = False


# Persisted synchronization output schema version. Bumped 0.1.0 -> 0.2.0 by
# BRW-010R: aligned rows now persist the composite selected electrical identity
# (electrical_asset_id, electrical_record_locator, electrical_timestamp).
# Matching algorithm / policy version is unchanged.
SYNCHRONIZATION_SCHEMA_VERSION = "0.2.0"


class SynchronizationConfig(BaseModel):
    version: str = "0.1.0"
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    boundary: BoundaryConfig = Field(default_factory=BoundaryConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    scientific_guards: SyncScientificGuardConfig = Field(default_factory=SyncScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> SynchronizationConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "synchronization" in payload:
            payload = payload["synchronization"]
        return cls.model_validate(payload)


class SyncQualityMetrics(BaseModel):
    total_ultrasound_frames: int
    matched_unique_count: int = 0
    matched_ambiguous_count: int = 0
    out_of_tolerance_count: int = 0
    timestamp_unavailable_count: int = 0
    no_candidate_count: int = 0
    timezone_mismatch_count: int = 0
    ambiguous_fraction: float = 0.0
    within_tolerance_fraction: float = 0.0
    sync_error_min_s: float | None = None
    sync_error_median_s: float | None = None
    sync_error_p95_s: float | None = None
    sync_error_max_s: float | None = None
    boundary_match_count: int = 0
    ambiguous_boundary_count: int = 0


class SynchronizationReport(BaseModel):
    """Experiment-level synchronization report."""

    battery_id: str
    experiment_id: str
    sync_version: str
    matching_method: str = "nearest"
    max_sync_error_s: float = 1.0
    tie_tolerance_s: float = 1e-9
    ultrasound_frame_count: int
    electrical_record_count: int
    metrics: SyncQualityMetrics
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: ReportStatus
    matching_performed: bool = True
    validated_sync: bool = False
    sync_semantics: str = "MATCHED_USING_PROVISIONAL_TIMEBASE"
    configuration: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)

"""Typed models for BRW-008 Experiment Time Anchor foundation.

These models describe *anchor provenance and provisional coverage* — they do
NOT represent verified cross-modal synchronization. The ``validated_sync``
flag is always ``False`` throughout BRW-008.

All datetimes are treated as naive (no timezone). Timezone is preserved as an
explicitly ``unknown`` state rather than inferred or assumed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

CandidateStatus = Literal[
    "UNVERIFIED",
    "PROVISIONAL",
    "CONFLICTING",
    "MANUALLY_ACCEPTED",
    "REJECTED",
]
SourceType = Literal[
    "MANIFEST_FILE_START",
    "MANUAL_OVERRIDE",
    "FILENAME_HINT",
    "EXPERIMENT_START_HINT",
]
ReportStatus = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]


class PlausibilityConfig(BaseModel):
    """Diagnostic thresholds for coverage plausibility.

    These are a *diagnostic policy*, never a law that promotes an anchor to
    ``VERIFIED``. Meeting these thresholds yields only ``PLAUSIBLE``.
    """

    max_start_residual_s: float = 60.0
    max_end_residual_s: float = 60.0
    min_overlap_fraction: float = 0.95


class ScientificGuardConfig(BaseModel):
    """Hard guards that keep BRW-008 from over-claiming or guessing."""

    allow_verified_sync_status: bool = False
    allow_filename_time_inference: bool = False
    allow_timezone_inference: bool = False
    allow_cycle_based_anchor: bool = False
    allow_drift_fit: bool = False
    allow_record_matching: bool = False


class TimeAnchorConfig(BaseModel):
    version: str = "0.1.0"
    plausibility: PlausibilityConfig = Field(default_factory=PlausibilityConfig)
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TimeAnchorConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["time_anchor"]
        return cls.model_validate(payload)


class TimeAnchorOverride(BaseModel):
    """A user-provided override. Never written back to raw manifests."""

    anchor_datetime: datetime
    elapsed_time_s_at_anchor: float = 0.0
    reason: str = ""


class TimeAnchorEvidence(BaseModel):
    """A piece of evidence — distinct from the candidate it may support."""

    evidence_id: str
    asset_id: str
    source_type: SourceType
    source_ref: str
    raw_value: Any
    parsed_value: datetime | None = None
    supports_candidate: bool = True
    conflicts_with_candidate: bool = False
    message: str = ""


class TimeAnchorCandidate(BaseModel):
    """A candidate anchor for one asset's elapsed clock."""

    anchor_id: str
    asset_id: str
    anchor_datetime: datetime
    elapsed_time_s_at_anchor: float = 0.0
    source_type: SourceType
    source_ref: str
    status: CandidateStatus
    timezone_known: bool = False
    timezone_name: str | None = None
    notes: str = ""


class CoverageDiagnostics(BaseModel):
    """Mechanical candidate coverage vs. a reference window."""

    candidate_start: datetime
    candidate_end: datetime
    start_residual_s: float
    end_residual_s: float
    duration_residual_s: float
    overlap_duration_s: float
    coverage_overlap_fraction: float


class AssetAnchorAssessment(BaseModel):
    """Per-asset anchor assessment (one ultrasound asset's elapsed clock)."""

    asset_id: str
    modality: str
    elapsed_min_s: float
    elapsed_max_s: float
    candidates: list[TimeAnchorCandidate] = Field(default_factory=list)
    selected_anchor_id: str | None = None
    anchor_status: CandidateStatus | None = None
    coverage: CoverageDiagnostics | None = None
    conflicts: list[TimeAnchorEvidence] = Field(default_factory=list)
    validated_sync: bool = False


class ExperimentTimeReference(BaseModel):
    """The experiment + electrical coverage window used for plausibility."""

    battery_id: str
    experiment_id: str
    experiment_start_time: datetime | None = None
    experiment_end_time: datetime | None = None
    electrical_start_time: datetime | None = None
    electrical_end_time: datetime | None = None
    timezone_known: bool = False
    timezone_name: str | None = None
    reference_sources: list[str] = Field(default_factory=list)


class TimeAnchorReport(BaseModel):
    """Human/QA report artifact (JSON + HTML)."""

    battery_id: str
    experiment_id: str
    anchor_version: str
    status: ReportStatus
    assets: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    validated_sync: bool = False


class TimeAnchorState(BaseModel):
    """Canonical persisted state — the machine input for BRW-009.

    This is the schema of ``data/processed/synchronization/{battery}/{exp}/time_anchors.json``.
    """

    battery_id: str
    experiment_id: str
    anchor_version: str
    experiment_reference: dict[str, Any]
    assets: list[AssetAnchorAssessment]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    validated_sync: bool = False


class TimeAnchor(BaseModel):
    """Backward-compatible minimal anchor (pre-BRW-008 placeholder)."""

    asset_id: str
    file_start_time: datetime
    source: str = "manifest"


class SyncMatch(BaseModel):
    """A candidate frame<->record alignment (BRW-010 scope; schema preserved)."""

    ultrasound_asset_id: str
    ultrasound_frame_index: int
    ultrasound_timestamp: datetime
    electrical_asset_id: str
    electrical_record_index: int
    electrical_timestamp: datetime
    sync_error_s: float


class SyncQualityReport(BaseModel):
    """Aggregated match quality (BRW-010 scope; schema preserved)."""

    total_ultrasound_frames: int
    matched_frames: int
    unmatched_frames: int
    match_rate: float
    median_sync_error_s: float | None = None
    max_sync_error_s: float | None = None


__all__ = [
    "AssetAnchorAssessment",
    "CandidateStatus",
    "CoverageDiagnostics",
    "ExperimentTimeReference",
    "PlausibilityConfig",
    "ReportStatus",
    "ScientificGuardConfig",
    "SourceType",
    "SyncMatch",
    "SyncQualityReport",
    "TimeAnchor",
    "TimeAnchorCandidate",
    "TimeAnchorConfig",
    "TimeAnchorEvidence",
    "TimeAnchorOverride",
    "TimeAnchorReport",
    "TimeAnchorState",
]

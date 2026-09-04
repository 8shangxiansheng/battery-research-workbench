"""BRW-024R intake session model — state machine + typed records.

States (task pack §5):
  DRAFT → ASSETS_RECEIVED → DETECTED → VALIDATED → COMMITTED
  any pre-commit state → FAILED / CANCELLED / EXPIRED

Scientific readiness is tracked separately and never collapses into
"experiment failed" (§2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

IntakeStatus = Literal[
    "DRAFT",
    "ASSETS_RECEIVED",
    "DETECTED",
    "VALIDATED",
    "COMMITTED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
]

ExperimentLifecycle = Literal[
    "DRAFT",
    "AWAITING_DATA",
    "IMPORTING",
    "IMPORT_VALIDATION_REQUIRED",
    "READY_FOR_PIPELINE",
    "WAITING_FOR_USER",
    "RUNNING",
    "READY",
    "FAILED",
    "ARCHIVED",
]

AssetRole = Literal["ELECTRICAL", "ULTRASOUND", "EXPERIMENT_METADATA", "AUXILIARY"]

DETECTION_STATE = Literal[
    "DETECTED_UNIQUE",
    "DETECTED_AMBIGUOUS",
    "UNSUPPORTED",
    "NEEDS_USER_CONFIRMATION",
]


class IntakeAssetRecord(BaseModel):
    """One staged asset — checksum/role/provenance always present (§8/§16)."""

    intake_asset_id: str
    session_id: str
    role: AssetRole
    original_filename: str
    stored_filename: str  # safe name inside staging; never the client-controlled path
    size: int
    sha256: str
    received_at: str
    content_kind: str | None = None  # sniffed mime-ish hint, never authoritative


class AdapterDetectionRecord(BaseModel):
    intake_asset_id: str
    state: DETECTION_STATE
    modality: str | None = None
    adapter_id: str | None = None
    adapter_version: str | None = None
    asset_role: AssetRole | None = None
    detection_reason: str = ""
    matched_signatures: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ValidationCheck(BaseModel):
    dimension: Literal["FORMAT_VALIDITY", "SCIENTIFIC_METADATA_COMPLETENESS", "PIPELINE_READINESS"]
    level: Literal["STRUCTURE_ONLY", "FULL_PARSE"]
    passed: bool
    detail: str = ""


class ImportValidationRecord(BaseModel):
    session_id: str
    validation_level: Literal["STRUCTURE_ONLY", "FULL_PARSE"]
    overall_passed: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    # unknown stays unknown (§12)
    sampling_rate_hz: float | None = None
    sampling_rate_status: Literal["UNKNOWN", "RESOLVED"] = "UNKNOWN"
    timebase_status: Literal["UNKNOWN", "PROVISIONAL", "VERIFIED"] = "UNKNOWN"


class IntakeCommitRecord(BaseModel):
    session_id: str
    committed_at: str
    experiment_composite_id: str
    assets: list[dict[str, Any]] = Field(default_factory=list)
    import_manifest_checksum: str


class IntakeSession(BaseModel):
    session_id: str
    experiment_composite_id: str
    battery_id: str
    experiment_id: str
    status: IntakeStatus = "DRAFT"
    created_at: str
    updated_at: str
    assets: list[IntakeAssetRecord] = Field(default_factory=list)
    detections: list[AdapterDetectionRecord] = Field(default_factory=list)
    validation: ImportValidationRecord | None = None
    commit: IntakeCommitRecord | None = None
    failure_reason: str | None = None
    policy_version: str = "0.1.0"


class LifecycleEvent(BaseModel):
    event_type: Literal[
        "EXPERIMENT_CREATED",
        "INTAKE_STARTED",
        "ASSET_UPLOADED",
        "ADAPTER_DETECTED",
        "VALIDATION_COMPLETED",
        "INTAKE_COMMITTED",
        "EXPERIMENT_UPDATED",
        "EXPERIMENT_ARCHIVED",
        "PIPELINE_STARTED",
    ]
    occurred_at: str
    session_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ExperimentRecord(BaseModel):
    """Persistent experiment library record (§3 summary fields)."""

    battery_id: str
    experiment_id: str
    name: str
    status: ExperimentLifecycle = "AWAITING_DATA"
    is_demo: bool = False
    created_at: str
    updated_at: str
    notes: str = ""
    events: list[LifecycleEvent] = Field(default_factory=list)

    @property
    def composite_id(self) -> str:
        return f"{self.battery_id}/{self.experiment_id}"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class IntakePolicyError(ValueError):
    """Raised when an intake operation violates the commit/session policy."""

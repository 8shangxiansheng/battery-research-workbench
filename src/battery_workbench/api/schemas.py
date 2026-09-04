"""BRW-024 public API DTOs — versioned, internal dataclasses not exposed."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- stable public field names frozen in task pack §23 ----
class SystemStatus(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    version: str
    api_version: str = "v1"


class Capabilities(BaseModel):
    software_capabilities: dict[str, Any] = Field(default_factory=dict)
    experiment_readiness: dict[str, Any] = Field(default_factory=dict)


class ExperimentSummary(BaseModel):
    battery_id: str
    experiment_id: str
    experiment_composite_id: str
    dataset_id: str | None = None
    split_id: str | None = None
    label_set_id: str | None = None
    gate_set_id: str | None = None
    feature_set_id: str | None = None
    scientific_status: str = ""
    limitations: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    latest_canonical_artifacts: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    status: str
    battery_id: str
    experiment_id: str
    created_at: str | None = None
    user_actions_pending: list[dict[str, Any]] = Field(default_factory=list)


class PlanSummary(BaseModel):
    plan_id: str
    profile: str
    battery_id: str
    experiment_id: str
    nodes: list[str] = Field(default_factory=list)


class DryRunResult(BaseModel):
    plan_id: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    reuse_summary: dict[str, Any] = Field(default_factory=dict)


class EventRecord(BaseModel):
    node: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)


class EventsResponse(BaseModel):
    run_id: str
    events: list[EventRecord] = Field(default_factory=list)


class UserActionInfo(BaseModel):
    action_id: str
    action_kind: str
    run_id: str
    node_id: str | None = None
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "PENDING"


class ArtifactDescriptor(BaseModel):
    artifact_id: str
    artifact_type: str
    availability: str = "AVAILABLE"
    status: str = ""
    row_count: int | None = None
    preview: list[dict[str, Any]] = Field(default_factory=list)
    path_hint: str | None = None  # debug/admin metadata only


class FeatureInfo(BaseModel):
    feature_name: str
    role: str | None = None
    availability: str = "AVAILABLE"
    gate_id: str | None = None
    tof_definition_id: str | None = None
    missing_reason: str | None = None


class LimitationInfo(BaseModel):
    code: str
    severity: str
    description: str


class EvidenceInfo(BaseModel):
    evidence_id: str
    evidence_type: str
    evidence_ref: str
    source_artifact_id: str | None = None
    description: str = ""


class LineageInfo(BaseModel):
    battery_id: str
    experiment_id: str
    lineage_chain: list[dict[str, Any]] = Field(default_factory=list)


class PaginationMeta(BaseModel):
    limit: int
    cursor: str | None = None
    next_cursor: str | None = None
    total: int | None = None


class ResponseEnvelope(BaseModel):
    data: Any = None
    meta: PaginationMeta | dict | None = None

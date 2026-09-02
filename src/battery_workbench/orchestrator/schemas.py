"""BRW-019 orchestrator schemas: AnalysisPlan, states, user actions, manifests.

The orchestrator expresses scientific *intent* only — never algorithm
internals. All scientific values come from existing deterministic modules.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

PlanProfile = Literal[
    "INGEST_TO_MEASUREMENT_EVENTS",
    "SCIENTIFIC_ANALYSIS",
    "BUILD_DATASET",
    "FULL_PRE_MODEL",
]

ALL_STAGES = [
    "ELECTRICAL_CANONICAL",
    "ULTRASOUND_CANONICAL",
    "TIME_ANCHOR",
    "ULTRASOUND_TIMESTAMPS",
    "SYNCHRONIZATION",
    "MEASUREMENT_EVENTS",
    "ANALYSIS_SLICE",
    "ULTRASOUND_FEATURES",
    "REFERENCE_LABELS",
    "PARAMETER_SET",
    "TOF_ACTIVATION",
    "GATED_FEATURES",
    "FEATURE_LABEL_ANALYSIS",
    "DATASET",
    "SPLIT",
    "FEATURE_ANALYSIS",
]

PROFILE_STAGES: dict[str, list[str]] = {
    "INGEST_TO_MEASUREMENT_EVENTS": [
        "ELECTRICAL_CANONICAL",
        "ULTRASOUND_CANONICAL",
        "TIME_ANCHOR",
        "ULTRASOUND_TIMESTAMPS",
        "SYNCHRONIZATION",
        "MEASUREMENT_EVENTS",
    ],
    "SCIENTIFIC_ANALYSIS": [
        "MEASUREMENT_EVENTS",
        "ANALYSIS_SLICE",
        "ULTRASOUND_FEATURES",
        "REFERENCE_LABELS",
        "PARAMETER_SET",
        "TOF_ACTIVATION",
        "GATED_FEATURES",
        "FEATURE_LABEL_ANALYSIS",
        "FEATURE_ANALYSIS",
    ],
    "EVALUATION_SPLIT": ["DATASET", "SPLIT", "FEATURE_ANALYSIS"],
    "BUILD_DATASET": [
        "MEASUREMENT_EVENTS",
        "ANALYSIS_SLICE",
        "ULTRASOUND_FEATURES",
        "REFERENCE_LABELS",
        "PARAMETER_SET",
        "DATASET",
    ],
    "FULL_PRE_MODEL": ALL_STAGES,
}


class PlanProject(BaseModel):
    battery_id: str
    experiment_id: str


class PlanExecution(BaseModel):
    dry_run: bool = False
    reuse_existing: bool = True
    force_recompute: list[str] = Field(default_factory=list)


class AnalysisPlan(BaseModel):
    profile: PlanProfile
    project: PlanProject
    stages: list[str] = Field(default_factory=list)
    analysis_slice: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    split: dict[str, Any] = Field(default_factory=dict)
    feature_analysis: dict[str, Any] = Field(default_factory=dict)
    split_id: str | None = None
    fold_index: int | None = None
    target: str | None = None
    label_producer_version: str | None = None
    execution: PlanExecution = Field(default_factory=PlanExecution)
    plan_id: str = ""
    plan_version: str = "0.1.0"

    @model_validator(mode="after")
    def _resolve(self) -> AnalysisPlan:
        if not self.stages:
            self.stages = list(PROFILE_STAGES[self.profile])
        unknown = [s for s in self.stages if s not in ALL_STAGES]
        if unknown:
            raise ValueError(f"unknown stages: {unknown}")
        if not self.plan_id:
            scientific = {
                "profile": self.profile,
                "battery_id": self.project.battery_id,
                "experiment_id": self.project.experiment_id,
                "stages": self.stages,
                "analysis_slice": self.analysis_slice,
                "gates": self.gates,
                "features": self.features,
                "parameters": self.parameters,
                "split": self.split,
                "feature_analysis": self.feature_analysis,
                "target": self.target,
                "label_producer_version": self.label_producer_version,
                "plan_version": self.plan_version,
            }
            canonical = json.dumps(scientific, sort_keys=True, separators=(",", ":"))
            self.plan_id = "PLAN::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return self


class ArtifactType(str, Enum):
    ELECTRICAL_CANONICAL = "ELECTRICAL_CANONICAL"
    ULTRASOUND_CANONICAL = "ULTRASOUND_CANONICAL"
    TIME_ANCHORS = "TIME_ANCHORS"
    ULTRASOUND_TIMESTAMPS = "ULTRASOUND_TIMESTAMPS"
    SYNCHRONIZATION = "SYNCHRONIZATION"
    MEASUREMENT_EVENTS = "MEASUREMENT_EVENTS"
    ANALYSIS_SLICE = "ANALYSIS_SLICE"
    ULTRASOUND_FEATURE_SET = "ULTRASOUND_FEATURE_SET"
    LABEL_SET = "LABEL_SET"
    PARAMETER_SET = "PARAMETER_SET"
    TOF_ACTIVATION = "TOF_ACTIVATION"
    GATE_SET = "GATE_SET"
    GATED_FEATURE_SET = "GATED_FEATURE_SET"
    FEATURE_LABEL_ANALYSIS = "FEATURE_LABEL_ANALYSIS"
    DATASET = "DATASET"
    SPLIT = "SPLIT"


class ArtifactRef(BaseModel):
    artifact_type: str
    artifact_id: str
    battery_id: str
    experiment_id: str
    path: str
    manifest_path: str
    producer_node: str = ""
    producer_version: str = ""
    content_hash: str = ""
    status: str = ""
    reuse_reason: str = ""


class NodeState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    REUSED = "REUSED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunState(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PARTIAL = "PARTIAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class UserActionRequired(BaseModel):
    action_id: str
    node_id: str
    action_type: str
    message: str
    required_fields: list[dict[str, Any]] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    scientific_reason: str = ""
    blocking: bool = True


class NodeResult(BaseModel):
    node_id: str
    node_version: str = "0.1.0"
    state: NodeState = NodeState.PENDING
    engineering_success: bool = False
    outputs: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    user_action_required: UserActionRequired | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ExecutionPlan(BaseModel):
    plan_id: str
    dry_run: bool = True
    nodes: list[NodeResult] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    analysis_plan_id: str
    battery_id: str
    experiment_id: str
    status: RunState = RunState.PLANNED
    started_at: str = ""
    completed_at: str = ""
    processed_root: str = ""
    nodes: list[NodeResult] = Field(default_factory=list)
    user_actions: list[UserActionRequired] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    final_artifacts: list[ArtifactRef] = Field(default_factory=list)


def build_plan(**plan_fields: Any) -> AnalysisPlan:
    """Normalize facade kwargs (stages / execution options) into an AnalysisPlan."""
    stages = plan_fields.pop("stages", None)
    plan_fields.pop("runs_root", None)
    execution = {
        "dry_run": plan_fields.pop("dry_run", False),
        "reuse_existing": plan_fields.pop("reuse_existing", True),
        "force_recompute": plan_fields.pop("force_recompute", []),
    }
    if "project" not in plan_fields:
        plan_fields["project"] = {
            "battery_id": plan_fields.pop("battery_id"),
            "experiment_id": plan_fields.pop("experiment_id"),
        }
    plan = AnalysisPlan(execution=execution, **plan_fields)  # type: ignore[arg-type]
    if stages is not None:
        plan = plan.model_copy(update={"stages": stages})
    return plan

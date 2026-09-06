"""BRW-026 core models — tool contract v1.0.0.

ToolSpec declares the full metadata contract (§3). Every tool result is a
ToolResult envelope carrying scientific context, evidence, and next actions
(§4). Confirmations bind tool+inputs digest and expire (§7).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

TOOL_CONTRACT_VERSION = "1.0.0"


class ToolCategory(str, Enum):
    DISCOVERY = "discovery"
    INTAKE = "intake"
    PARAMETERS = "parameters"
    WAVEFORM_GATES = "waveform_gates"
    FEATURES_ANALYSIS = "features_analysis"
    DATASET_EVALUATION = "dataset_evaluation"
    REPORTING = "reporting"


class ConfirmationPolicy(str, Enum):
    NO_CONFIRMATION = "NO_CONFIRMATION"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"


class ToolSpec(BaseModel):
    """Immutable tool declaration (§3). The registry validates completeness."""

    name: str
    description: str
    category: ToolCategory
    read_only: bool
    side_effect: bool
    confirmation_required: ConfirmationPolicy
    scientific_scope: str
    idempotent: bool = False
    returns_evidence: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    allowed_when: list[str] = Field(default_factory=list)
    blocked_when: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    # parameters the agent must never guess; require USER_INPUT_REQUIRED
    no_guess_parameters: list[str] = Field(default_factory=list)


class AgentScientificContext(BaseModel):
    """Agent working context (§5). Experiment switching is explicit."""

    battery_id: str
    experiment_id: str
    run_id: str | None = None
    analysis_id: str | None = None
    dataset_id: str | None = None
    split_id: str | None = None
    gate_id: str | None = None
    current_ui_route: str | None = None

    @property
    def composite_id(self) -> str:
        return f"{self.battery_id}/{self.experiment_id}"


class ScientificContext(BaseModel):
    readiness: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    evidence_type: str
    evidence_ref: str
    artifact_id: str | None = None
    availability: str | None = None


ToolStatus = Literal[
    "SUCCEEDED", "FAILED", "BLOCKED", "WAITING_FOR_USER", "CONFIRMATION_REQUIRED", "REUSED"
]


class ToolResult(BaseModel):
    status: Literal[
        "SUCCEEDED", "FAILED", "BLOCKED", "WAITING_FOR_USER", "CONFIRMATION_REQUIRED", "REUSED"
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    scientific_context: ScientificContext = Field(default_factory=ScientificContext)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    tool_call_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    error: dict[str, Any] | None = None
    confirmation: dict[str, Any] | None = None


class PendingConfirmation(BaseModel):
    confirmation_id: str
    tool_name: str
    inputs_digest: str
    policy: ConfirmationPolicy
    created_at: str
    expires_at: str
    summary: str = ""

    @staticmethod
    def digest(tool_name: str, inputs: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"tool": tool_name, "inputs": inputs}, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class ConfirmationStore:
    """Binds confirmations to tool+inputs digest; payload change invalidates (§7)."""

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._items: dict[str, PendingConfirmation] = {}
        self._ttl = ttl_minutes

    def issue(
        self, tool_name: str, inputs: dict[str, Any], policy: ConfirmationPolicy, summary: str = ""
    ) -> PendingConfirmation:
        digest = PendingConfirmation.digest(tool_name, inputs)
        now = datetime.now(UTC)
        record = PendingConfirmation(
            confirmation_id=f"CNF::{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            inputs_digest=digest,
            policy=policy,
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + timedelta(minutes=self._ttl)).isoformat(timespec="seconds"),
            summary=summary,
        )
        self._items[record.confirmation_id] = record
        return record

    def validate(
        self, confirmation_id: str, tool_name: str, inputs: dict[str, Any]
    ) -> PendingConfirmation:
        record = self._items.get(confirmation_id)
        if record is None:
            raise PermissionError(f"unknown confirmation: {confirmation_id}")
        if record.expires_at < datetime.now(UTC).isoformat(timespec="seconds"):
            raise PermissionError(f"confirmation expired: {confirmation_id}")
        if record.tool_name != tool_name:
            raise PermissionError("confirmation tool mismatch")
        if record.inputs_digest != PendingConfirmation.digest(tool_name, inputs):
            raise PermissionError("payload changed since confirmation; re-confirm required")
        return record

    def consume(self, confirmation_id: str) -> None:
        self._items.pop(confirmation_id, None)


class ToolAuditEntry(BaseModel):
    tool_call_id: str
    tool_name: str
    timestamp: str
    inputs_digest: str
    confirmation_status: str
    result_status: str
    resource_ids: dict[str, str] = Field(default_factory=dict)
    run_id: str | None = None
    request_id: str
    evidence_refs: list[str] = Field(default_factory=list)


class ToolAuditLog:
    """Append-only audit trail; never records payloads/secrets/waveforms (§16)."""

    def __init__(self) -> None:
        self._entries: list[ToolAuditEntry] = []

    def append(self, entry: ToolAuditEntry) -> None:
        self._entries.append(entry)

    def all_entries(self) -> list[ToolAuditEntry]:
        return list(self._entries)

    def for_run(self, run_id: str) -> list[ToolAuditEntry]:
        return [e for e in self._entries if e.run_id == run_id]

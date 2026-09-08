"""BRW-027R — AgentResearchSession typed state.

Persists the research-assistant working state for one experiment:
experiment, page context, selected target, alignment status, gate
calibration status, selected features, feature-selection mode, dataset/
split/model/report ids, pending user action, limitations and evidence.

Scientific facts (readiness, alignment counts, model metrics) are always
refreshed from backend tools — the session stores references and
agent-facing context, never computed scientific values.

The planner module orchestrates BRW-026 ToolGateway calls; this module has
no scientific logic and imports no scientific calculation modules.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

SESSION_SCHEMA_VERSION = "1.0.0"

ResearchPhase = Literal[
    "UNDERSTAND_GOAL", "SELECT_TARGET", "CHECK_TARGET_READINESS",
    "CHECK_ALIGNMENT", "CHECK_GATE_READINESS", "INSPECT_FEATURES",
    "ANALYZE_RELATIONSHIPS", "CHOOSE_PATH", "EXPLORATORY_RESULT",
    "CHECK_GROUPED_SPLIT", "TRAIN_ONLY_FEATURE_SELECTION",
    "CONFIRM_SELECTION", "BUILD_DATASET", "RUN_BASELINES", "INTERPRET",
    "REPORT", "WAITING_FOR_USER",
]

SelectionMode = Literal["EXPLORATORY", "ML_SAFE"]


class SessionTurn(BaseModel):
    """One user-visible exchange (no chain-of-thought, no raw tool logs)."""

    turn_id: str
    role: Literal["user", "assistant"]
    intent: str | None = None
    message: str
    tool_name: str | None = None
    tool_status: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class NextAction(BaseModel):
    action_id: str
    label_en: str
    label_zh: str
    intent: str | None = None
    confirmation_required: bool = False


class AgentResearchSession(BaseModel):
    """Typed research-assistant session (§03)."""

    session_id: str
    schema_version: str = SESSION_SCHEMA_VERSION
    battery_id: str
    experiment_id: str
    current_page: str = "analysis"
    ui_context: dict[str, Any] = Field(default_factory=dict)

    selected_target: str | None = None
    target_readiness: str | None = None
    alignment_status: dict[str, Any] | None = None
    gate_calibration_status: str | None = None

    selected_features: list[str] = Field(default_factory=list)
    feature_selection_mode: SelectionMode = "EXPLORATORY"

    dataset_id: str | None = None
    split_id: str | None = None
    model_run_id: str | None = None
    report_id: str | None = None

    phase: ResearchPhase = "UNDERSTAND_GOAL"
    pending_user_action: dict[str, Any] | None = None
    last_confirmation_id: str | None = None

    scientific_limitations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    conversation: list[SessionTurn] = Field(default_factory=list)

    def touch(self) -> None:
        self.ui_context["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    def add_turn(self, role: Literal["user", "assistant"], message: str, *,
                 intent: str | None = None, tool_name: str | None = None,
                 tool_status: str | None = None,
                 evidence_refs: list[str] | None = None) -> SessionTurn:
        turn = SessionTurn(
            turn_id=f"T::{uuid.uuid4().hex[:10]}",
            role=role, message=message, intent=intent,
            tool_name=tool_name, tool_status=tool_status,
            evidence_refs=evidence_refs or [],
        )
        self.conversation.append(turn)
        return turn


class SessionStore:
    """File-backed session persistence under processed_root/assistant_sessions.

    One JSON file per session; deterministic id per (experiment, session
    prefix) is supported so the drawer can resume its latest session.
    """

    def __init__(self, processed_root: Path) -> None:
        self.root = Path(processed_root) / "assistant_sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, battery_id: str, experiment_id: str, session_id: str) -> Path:
        return self.root / battery_id / experiment_id / f"{session_id}.json"

    def save(self, session: AgentResearchSession) -> None:
        session.touch()
        path = self._path(session.battery_id, session.experiment_id, session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(session.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    def load(self, battery_id: str, experiment_id: str, session_id: str) -> AgentResearchSession | None:
        path = self._path(battery_id, experiment_id, session_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentResearchSession.model_validate(data)

    def latest(self, battery_id: str, experiment_id: str) -> AgentResearchSession | None:
        exp_dir = self.root / battery_id / experiment_id
        if not exp_dir.is_dir():
            return None
        newest: tuple[str, Path] | None = None
        for p in exp_dir.glob("*.json"):
            mtime = datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(timespec="seconds")
            if newest is None or mtime > newest[0]:
                newest = (mtime, p)
        if newest is None:
            return None
        return AgentResearchSession.model_validate(json.loads(newest[1].read_text(encoding="utf-8")))

    @staticmethod
    def new_session_id(battery_id: str, experiment_id: str) -> str:
        digest = hashlib.sha256(
            f"{battery_id}|{experiment_id}|{uuid.uuid4().hex}".encode()
        ).hexdigest()[:12]
        return f"RS::{digest}"

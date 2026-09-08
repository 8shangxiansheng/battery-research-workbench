"""BRW-027R — Research Assistant session endpoints.

Thin HTTP surface over the ResearchPlanner; no scientific logic here.
Message handling routes through ToolGateway → WorkbenchService →
deterministic core. Sessions persist under processed_root/assistant_sessions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from battery_workbench.agent_assistant.planner import ResearchPlanner
from battery_workbench.agent_assistant.session import (
    AgentResearchSession,
    SessionStore,
)
from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

router = APIRouter(tags=["research-assistant"])


class _FakeRequestBridge:
    """Request shim exposing workbench_service for read route functions."""

    def __init__(self, service: Any) -> None:
        self.state = type("S", (), {"workbench_service": service})()
        self.app = type("A", (), {"state": self.state})()


def _store(request: Request) -> SessionStore:
    return SessionStore(get_service(request).processed_root)


def _planner(request: Request) -> ResearchPlanner:
    return ResearchPlanner(gateway=_gateway(request), store=_store(request))


def _gateway(request: Request):
    """ToolGateway bound to the same workspace as the service."""
    from battery_workbench.agent_tools.gateway import ToolGateway

    service = get_service(request)
    if not hasattr(service, "_assistant_gateway"):
        service._assistant_gateway = ToolGateway(service=service)  # type: ignore[attr-defined]
    return service._assistant_gateway  # type: ignore[attr-defined]


@router.post("/experiments/{battery_id}/{experiment_id}/assistant/session")
def open_session(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    store = _store(request)
    existing = store.latest(battery_id, experiment_id)
    if existing is None:
        existing = AgentResearchSession(
            session_id=SessionStore.new_session_id(battery_id, experiment_id),
            battery_id=battery_id, experiment_id=experiment_id,
        )
        store.save(existing)
    return {"data": existing.model_dump(mode="json"), "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/assistant/session/{session_id}")
def get_session(request: Request, battery_id: str, experiment_id: str, session_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    session = _store(request).load(battery_id, experiment_id, session_id)
    if session is None:
        raise APIError(ErrorCode.NOT_FOUND, "assistant session not found")
    return {"data": session.model_dump(mode="json"), "meta": {}}


class AssistantMessageRequest(dict):
    pass


@router.post("/experiments/{battery_id}/{experiment_id}/assistant/session/{session_id}/message")
def send_message(
    request: Request, battery_id: str, experiment_id: str, session_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    message = str(body.get("message", "")).strip()
    if not message:
        raise APIError(ErrorCode.VALIDATION_ERROR, "message required")
    if len(message) > 2000:
        raise APIError(ErrorCode.VALIDATION_ERROR, "message too long")
    session = _store(request).load(battery_id, experiment_id, session_id)
    if session is None:
        raise APIError(ErrorCode.NOT_FOUND, "assistant session not found")
    session.current_page = str(body.get("current_page", session.current_page))
    response = _planner(request).handle_message(session, message)
    return {
        "data": {
            "message": response.message,
            "intent": response.intent,
            "phase": response.phase,
            "status": response.status,
            "pending_user_action": response.pending_user_action,
            "confirmation_id": response.confirmation_id,
            "evidence_refs": response.evidence_refs,
            "limitations": response.limitations,
            "next_actions": [n.model_dump() for n in response.next_actions],
            "session": session.model_dump(mode="json"),
        },
        "meta": {"planner": "RESEARCH_PLANNER_V1", "note": "no chain-of-thought retained"},
    }

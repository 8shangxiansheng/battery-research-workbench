"""BRW-027R — Research Assistant session endpoints.

Thin HTTP surface over the ResearchPlanner; no scientific logic here.
Message handling routes through ToolGateway → WorkbenchService →
deterministic core. Sessions persist under processed_root/assistant_sessions.
"""

from __future__ import annotations

import hashlib
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


def _source_state(request: Request, battery_id: str, experiment_id: str) -> tuple[list[str], dict[str, str | None]]:
    from battery_workbench.reporting.collector import invalid_parser_manifest_modalities

    service = get_service(request)
    invalid = invalid_parser_manifest_modalities(
        service.processed_root, battery_id, experiment_id
    )
    fingerprints: dict[str, str | None] = {}
    for modality in ("electrical", "ultrasound"):
        path = (
            service.processed_root
            / modality
            / battery_id
            / experiment_id
            / "parser_manifest.json"
        )
        try:
            fingerprints[modality] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            )
        except OSError:
            fingerprints[modality] = "UNREADABLE"
    return invalid, fingerprints


def _session_matches_source_state(
    session: AgentResearchSession,
    invalid_modalities: list[str],
    fingerprints: dict[str, str | None],
) -> bool:
    stored = session.ui_context.get("source_parser_manifest_fingerprints")
    if stored != fingerprints:
        return False
    if invalid_modalities:
        return (
            session.ui_context.get("source_integrity_status") == "INTEGRITY_BLOCKED"
            and session.ui_context.get("invalid_modalities") == invalid_modalities
            and stored == fingerprints
        )
    return True


def _stale_session_error() -> APIError:
    return APIError(
        ErrorCode.INTEGRITY_ERROR,
        "assistant session is bound to a different source-parser state",
        {
            "source_integrity_status": "INTEGRITY_BLOCKED",
            "recovery_action": "OPEN_A_NEW_ASSISTANT_SESSION_AFTER_SOURCE_REVIEW",
        },
    )


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
    invalid_modalities, fingerprints = _source_state(request, battery_id, experiment_id)
    if existing is not None and not _session_matches_source_state(
        existing, invalid_modalities, fingerprints
    ):
        existing = None
    if existing is None:
        existing = AgentResearchSession(
            session_id=SessionStore.new_session_id(battery_id, experiment_id),
            battery_id=battery_id, experiment_id=experiment_id,
        )
        existing.ui_context["source_parser_manifest_fingerprints"] = fingerprints
        if invalid_modalities:
            existing.ui_context["source_integrity_status"] = "INTEGRITY_BLOCKED"
            existing.ui_context["invalid_modalities"] = invalid_modalities
            existing.scientific_limitations = [
                {
                    "code": "SOURCE_PROVENANCE_INVALID",
                    "description": "来源 parser manifest 无效；重新解析并复核 lineage 前不解释历史结果。",
                }
            ]
        store.save(existing)
    meta = {"read_only": False}
    if invalid_modalities:
        meta.update(
            {
                "source_integrity_status": "INTEGRITY_BLOCKED",
                "invalid_modalities": invalid_modalities,
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            }
        )
    return {"data": existing.model_dump(mode="json"), "meta": meta}


@router.get("/experiments/{battery_id}/{experiment_id}/assistant/session/{session_id}")
def get_session(request: Request, battery_id: str, experiment_id: str, session_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    session = _store(request).load(battery_id, experiment_id, session_id)
    if session is None:
        raise APIError(ErrorCode.NOT_FOUND, "assistant session not found")
    invalid_modalities, fingerprints = _source_state(request, battery_id, experiment_id)
    if not _session_matches_source_state(session, invalid_modalities, fingerprints):
        raise _stale_session_error()
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
    invalid_modalities, fingerprints = _source_state(request, battery_id, experiment_id)
    if not _session_matches_source_state(session, invalid_modalities, fingerprints):
        raise _stale_session_error()
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

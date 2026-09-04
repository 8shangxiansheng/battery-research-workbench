"""Run endpoints — delegate to BRW-019 orchestrator; idempotency contract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode

router = APIRouter(tags=["runs"])

_PROFILES = ("INGEST_TO_MEASUREMENT_EVENTS", "SCIENTIFIC_ANALYSIS", "FULL_PRE_MODEL")


def _profile_payload(body: dict[str, Any]) -> dict[str, Any]:
    profile = body.get("profile")
    if profile not in _PROFILES:
        raise APIError(ErrorCode.VALIDATION_ERROR, "unknown profile", {"profile": profile})
    return {
        "profile": profile,
        "battery_id": body.get("battery_id", "CELL_001"),
        "experiment_id": body.get("experiment_id", "EXP_001"),
    }


@router.post("/runs/plan")
def plan_run(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    data = get_service(request).plan_run(_profile_payload(body))
    return {"data": data, "meta": {}}


@router.post("/runs/dry-run")
def dry_run(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    data = get_service(request).dry_run(_profile_payload(body))
    return {"data": data, "meta": {}}


@router.post("/runs")
def start_run(
    request: Request,
    body: dict[str, Any],
    idempotency_key: str | None = Header(default=None),
) -> dict[str, Any]:
    data = get_service(request).start_run(_profile_payload(body), idempotency_key=idempotency_key)
    return {"data": data, "meta": {}}


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    return {"data": get_service(request).get_run(run_id), "meta": {}}


@router.get("/runs/{run_id}/events")
def get_run_events(request: Request, run_id: str) -> dict[str, Any]:
    events = get_service(request).get_run_events(run_id)
    return {"data": {"run_id": run_id, "events": events}, "meta": {}}


@router.post("/runs/{run_id}/resume")
def resume_run(request: Request, run_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": get_service(request).resume_run(run_id), "meta": {}}


@router.post("/runs/{run_id}/retry")
def retry_node(request: Request, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    node_id = body.get("node_id")
    if not node_id or not isinstance(node_id, str):
        raise APIError(ErrorCode.VALIDATION_ERROR, "node_id required")
    return {"data": get_service(request).retry_node(run_id, node_id), "meta": {}}


@router.get("/runs/{run_id}/user-actions")
def list_user_actions(request: Request, run_id: str) -> dict[str, Any]:
    actions = get_service(request).list_user_actions(run_id)
    return {"data": {"run_id": run_id, "user_actions": actions}, "meta": {}}


@router.post("/runs/{run_id}/user-actions/{action_id}")
def submit_user_action(
    request: Request, run_id: str, action_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    raw_values = body.get("values")
    values: dict[str, Any] = dict(raw_values) if isinstance(raw_values, dict) else {}
    data = get_service(request).submit_user_action(run_id, action_id, values)
    return {"data": data, "meta": {}}

"""Experiment endpoints — read-only; no scientific recomputation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

router = APIRouter(tags=["experiments"])

_CURSORS: set[str] = {"", "not-a-cursor"}


@router.get("/experiments")
def list_experiments(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    if cursor is not None and not cursor.strip():
        raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cursor")
    # opaque cursor: must look like a composite id (letters + '/' + letters)
    if cursor is not None and (
        "/" not in cursor or any(ch in cursor for ch in (" ", "\\", "%", ".."))
    ):
        raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cursor")
    items = get_service(request).list_experiments()
    items.sort(key=lambda x: x["experiment_composite_id"])
    if cursor:
        items = [x for x in items if x["experiment_composite_id"] > cursor]
    page = items[:limit]
    next_cursor = page[-1]["experiment_composite_id"] if len(items) > limit else None
    return {
        "data": page,
        "meta": {"limit": limit, "cursor": cursor, "next_cursor": next_cursor},
    }


@router.get("/experiments/{battery_id}/{experiment_id}")
def get_experiment(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {"data": get_service(request).get_experiment(battery_id, experiment_id), "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/status")
def get_status(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {"data": get_service(request).get_status(battery_id, experiment_id), "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/workspace-summary")
def workspace_summary(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {
        "data": get_service(request).get_workspace_summary(battery_id, experiment_id),
        "meta": {},
    }


@router.get("/experiments/{battery_id}/{experiment_id}/lineage")
def lineage(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {"data": get_service(request).get_lineage(battery_id, experiment_id), "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/results")
def results(
    request: Request,
    battery_id: str,
    experiment_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
    result_type: str | None = Query(default=None),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if cursor is not None and (
        not cursor.strip() or any(ch in cursor for ch in (" ", "\\", "%", "..", "/"))
    ):
        raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cursor")
    items = get_service(request).get_results(battery_id, experiment_id, limit=limit, cursor=cursor)
    if result_type:
        items = [i for i in items if i["result_type"] == result_type]
    return {"data": items, "meta": {"limit": limit, "cursor": cursor}}


@router.get("/experiments/{battery_id}/{experiment_id}/limitations")
def limitations(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {
        "data": {"limitations": get_service(request).get_limitations(battery_id, experiment_id)},
        "meta": {},
    }


@router.get("/experiments/{battery_id}/{experiment_id}/evidence")
def evidence(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {
        "data": {"evidence": get_service(request).get_evidence(battery_id, experiment_id)},
        "meta": {},
    }

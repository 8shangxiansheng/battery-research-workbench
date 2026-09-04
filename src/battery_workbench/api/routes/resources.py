"""Scientific resource endpoints — delegate to WorkbenchService.

Deterministic creates (gates/parameters/datasets/splits/analyses/reports/
baseline models) are idempotent: same semantic spec → same semantic ID.
Large payloads are never returned; only metadata/preview.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

router = APIRouter(tags=["scientific-resources", "artifacts"])


# ---------- parameters (BRW-015) ----------
@router.get("/experiments/{battery_id}/{experiment_id}/parameters")
def list_parameters(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {"data": get_service(request).list_parameters(battery_id, experiment_id), "meta": {}}


@router.post("/experiments/{battery_id}/{experiment_id}/parameters")
def create_parameters(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    data = get_service(request).create_parameter_set(battery_id, experiment_id, body)
    return {"data": data, "meta": {}}


# ---------- gates (BRW-018) ----------
@router.post("/gates")
def create_gate(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).create_gate(body), "meta": {}}


@router.get("/gates/{gate_id}")
def get_gate(request: Request, gate_id: str) -> dict[str, Any]:
    return {"data": get_service(request).get_gate(gate_id), "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/gates")
def list_gates(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {
        "data": {"gates": get_service(request).list_gates(battery_id, experiment_id)},
        "meta": {},
    }


# ---------- features ----------
@router.get("/experiments/{battery_id}/{experiment_id}/features")
def list_features(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    return {
        "data": {"features": get_service(request).list_features(battery_id, experiment_id)},
        "meta": {},
    }


# ---------- feature analysis (BRW-021) ----------
@router.post("/feature-analyses")
def create_feature_analysis(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).create_feature_analysis(body), "meta": {}}


@router.get("/feature-analyses/{analysis_id}")
def get_feature_analysis(request: Request, analysis_id: str) -> dict[str, Any]:
    return {"data": get_service(request).get_feature_analysis(analysis_id), "meta": {}}


# ---------- datasets ----------
@router.post("/datasets")
def create_dataset(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).create_dataset(body), "meta": {}}


@router.get("/datasets/{dataset_id}")
def get_dataset(request: Request, dataset_id: str) -> dict[str, Any]:
    validate_id(dataset_id, "dataset_id")
    return {"data": get_service(request).get_artifact(dataset_id), "meta": {}}


# ---------- splits ----------
@router.post("/splits")
def create_split(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).create_split(body), "meta": {}}


@router.get("/splits/{split_id}")
def get_split(request: Request, split_id: str) -> dict[str, Any]:
    validate_id(split_id, "split_id")
    return {"data": get_service(request).get_artifact(split_id), "meta": {}}


# ---------- models (fixed baseline only; no tuning endpoint) ----------
@router.post("/models/baseline-runs")
def create_baseline_model(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).create_baseline_model(body), "meta": {}}


# ---------- reports (BRW-023) ----------
@router.post("/reports")
def create_report(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    return {"data": get_service(request).generate_report(body), "meta": {}}


@router.get("/reports")
def list_reports(
    request: Request,
    battery_id: str = Query(default="CELL_001"),
    experiment_id: str = Query(default="EXP_001"),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    page = get_service(request).list_reports(
        battery_id, experiment_id, limit=limit + 1, cursor=cursor
    )
    has_more = len(page) > limit
    data = page[:limit]
    # opaque cursor = last returned report_id; next page strictly excludes it
    next_cursor = data[-1].get("report_id") if has_more and data else None
    return {"data": data, "meta": {"limit": limit, "cursor": cursor, "next_cursor": next_cursor}}


@router.get("/reports/{report_id}")
def get_report(request: Request, report_id: str) -> dict[str, Any]:
    return {"data": get_service(request).get_report(report_id), "meta": {}}


# ---------- artifacts (metadata only; preview bounded) ----------
@router.get("/artifacts/{artifact_id}")
def get_artifact(request: Request, artifact_id: str) -> dict[str, Any]:
    return {"data": get_service(request).get_artifact(artifact_id), "meta": {}}


@router.get("/artifacts/{artifact_id}/preview")
def preview_artifact(
    request: Request,
    artifact_id: str,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    validate_id(artifact_id, "artifact_id")
    if limit > 200:
        raise APIError(ErrorCode.VALIDATION_ERROR, "preview limit capped at 200")
    return {
        "data": {"artifact_id": artifact_id, "preview": [], "limit": limit},
        "meta": {},
    }

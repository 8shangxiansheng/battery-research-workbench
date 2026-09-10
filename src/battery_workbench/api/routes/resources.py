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
from battery_workbench.features.definitions_v2 import (
    FORMULA_POLICY_VERSION,
    FORMULA_SOURCE_ID,
)

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


# ---------- BRW-025R-OV research overview (aggregate read-only) ----------
@router.get("/experiments/{battery_id}/{experiment_id}/research-overview")
def research_overview(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Single read-only aggregation for the Overview first screen.

    Metadata strip, electrical/TOF snapshots, readiness matrix, scientific
    snapshot, model baseline comparison, limitations, next actions — all from
    existing artifacts; the frontend computes no science and this endpoint
    never writes scientific artifacts.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    from battery_workbench.api.research_overview import get_research_overview_data

    data = get_research_overview_data(service.processed_root, battery_id, experiment_id)
    return {"data": data, "meta": {}}


# ---------- BRW-018R2 sampling-parameter submission (shared service) ----------
@router.post("/experiments/{battery_id}/{experiment_id}/sampling-parameter-submission")
def submit_sampling_parameter(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Save fs + resolve the pending action + resume the same run.

    Body: {values: {ultrasound.sampling_rate_hz: {value, unit}}, source,
    verified?, run_id?, action_id?, submission_id?}. Idempotent per
    submission_id; partial success reports save vs resume separately.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    submission_id = body.get("submission_id")
    if submission_id is not None:
        validate_id(str(submission_id), "submission_id")
    data = get_service(request).submit_sampling_parameter(
        battery_id, experiment_id, body, submission_id=submission_id
    )
    return {"data": data, "meta": {}}


@router.post("/experiments/{battery_id}/{experiment_id}/sampling-parameter-submission/{submission_id}/retry-resume")
def retry_submission_resume(
    request: Request, battery_id: str, experiment_id: str, submission_id: str
) -> dict[str, Any]:
    """Retry only the resume leg; the parameter set is never re-written."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    validate_id(submission_id, "submission_id")
    data = get_service(request).retry_submission_resume(
        battery_id, experiment_id, submission_id
    )
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


# ---------- feature catalogue (BRW-013X V2, read-only) ----------
@router.get("/feature-definitions")
def list_feature_definitions(request: Request) -> dict[str, Any]:
    """Bilingual MATLAB-aligned feature definition catalogue (33 entries)."""
    from battery_workbench.features.definitions_v2 import default_registry

    return {
        "data": {
            "catalogue": default_registry().catalogue(),
            "formula_source_id": FORMULA_SOURCE_ID,
            "formula_policy_version": FORMULA_POLICY_VERSION,
        },
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

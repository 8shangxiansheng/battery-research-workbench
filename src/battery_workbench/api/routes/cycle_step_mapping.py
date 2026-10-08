"""Read-only API preflight for operator-reviewed Cycle/Step mappings."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id
from battery_workbench.provenance.cycle_step_mapping import (
    CycleStepMappingError,
    CycleStepMappingEvidenceTooLarge,
    build_cycle_step_mapping_draft_csv,
    build_cycle_step_mapping_source_inventory,
    hash_cycle_step_mapping_evidence,
    validate_cycle_step_mapping,
)
from battery_workbench.provenance.cycle_step_mapping_store import (
    CycleStepMappingConflict,
    CycleStepMappingStoreError,
    get_cycle_step_mapping_status,
    list_cycle_step_mapping_revisions,
    read_cycle_step_mapping_revision,
    save_cycle_step_mapping,
)

router = APIRouter(tags=["scientific-resources"])


class CycleStepMappingPreflightRequest(BaseModel):
    """CSV bytes supplied by the operator; this endpoint never saves them."""

    mapping_csv: str = Field(min_length=1, max_length=4_000_000)


class CycleStepMappingSaveRequest(CycleStepMappingPreflightRequest):
    """Explicit human confirmation plus optimistic concurrency token."""

    confirm_reviewed: bool
    expected_active_sha256: str | None


class CycleStepMappingEvidenceCheckRequest(BaseModel):
    """操作者选择的 immutable raw-root 下的证据路径。"""

    evidence_relative_path: str = Field(min_length=1, max_length=1024)


@router.get("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/source-inventory")
def get_cycle_step_mapping_source_inventory(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """返回已校验的 source pair 清单，不提出 canonical 对应关系。"""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        rows = build_cycle_step_mapping_source_inventory(
            raw_root=service.raw_root,
            processed_root=service.processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except CycleStepMappingError as exc:
        raise APIError(
            ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
            "Current parser source inventory is unavailable",
            {"reason": str(exc)},
        ) from exc
    return {
        "data": {"source_steps": rows},
        "meta": {"read_only": True, "scientific_assignments_inferred": False},
    }


@router.post("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/evidence-check")
def check_cycle_step_mapping_evidence(
    request: Request,
    battery_id: str,
    experiment_id: str,
    body: CycleStepMappingEvidenceCheckRequest,
) -> dict[str, Any]:
    """校验用户选择的 raw 证据文件并返回其 checksum。"""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        result = hash_cycle_step_mapping_evidence(
            body.evidence_relative_path,
            raw_root=service.raw_root,
        )
    except CycleStepMappingEvidenceTooLarge as exc:
        raise APIError(ErrorCode.UPLOAD_TOO_LARGE, str(exc)) from exc
    except CycleStepMappingError as exc:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "Cycle/Step mapping evidence path is invalid",
            {"reason": str(exc)},
        ) from exc
    return {"data": result, "meta": {"read_only": True}}


@router.get(
    "/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/draft",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def download_cycle_step_mapping_draft(
    request: Request, battery_id: str, experiment_id: str
) -> Response:
    """下载未审核来源清单，所有科学映射决策保持空白。"""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        content = build_cycle_step_mapping_draft_csv(
            raw_root=service.raw_root,
            processed_root=service.processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except CycleStepMappingError as exc:
        raise APIError(
            ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
            "Current parser source inventory is unavailable",
            {"reason": str(exc)},
        ) from exc
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="cycle-step-mapping-draft-{battery_id}-{experiment_id}.csv"',
            "X-Mapping-Draft": "unreviewed",
        },
    )


@router.get("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping")
def get_reviewed_cycle_step_mapping_status(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Return current sidecar checksum/status for safe replacement flows."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        result = get_cycle_step_mapping_status(
            raw_root=service.raw_root,
            processed_root=service.processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except CycleStepMappingStoreError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    return {"data": result, "meta": {"read_only": True}}


@router.get("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/revisions")
def list_reviewed_cycle_step_mapping_revisions(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """List content-addressed snapshots without interpreting their science."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        revisions = list_cycle_step_mapping_revisions(
            raw_root=service.raw_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except CycleStepMappingStoreError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    return {"data": {"revisions": revisions}, "meta": {"read_only": True}}


@router.get(
    "/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/revisions/{revision_sha256}",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def download_reviewed_cycle_step_mapping_revision(
    request: Request, battery_id: str, experiment_id: str, revision_sha256: str
) -> Response:
    """Download a verified immutable CSV snapshot by its SHA-256 identity."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    try:
        content = read_cycle_step_mapping_revision(
            revision_sha256,
            raw_root=service.raw_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except FileNotFoundError as exc:
        raise APIError(ErrorCode.NOT_FOUND, str(exc)) from exc
    except CycleStepMappingStoreError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    except CycleStepMappingError as exc:
        raise APIError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="cycle-step-mapping-{revision_sha256}.csv"',
            "X-Content-SHA256": revision_sha256,
        },
    )


@router.post("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping/preflight")
def preflight_cycle_step_mapping(
    request: Request,
    battery_id: str,
    experiment_id: str,
    body: CycleStepMappingPreflightRequest,
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if len(body.mapping_csv.encode("utf-8")) > 4_000_000:
        raise APIError(ErrorCode.UPLOAD_TOO_LARGE, "mapping CSV exceeds 4 MB")

    service = get_service(request)
    try:
        with tempfile.TemporaryDirectory(prefix="brw-cycle-step-preflight-") as temp_dir:
            candidate = Path(temp_dir) / "cycle-step-mapping.csv"
            candidate.write_text(body.mapping_csv, encoding="utf-8")
            result = validate_cycle_step_mapping(
                candidate,
                raw_root=service.raw_root,
                processed_root=service.processed_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
    except CycleStepMappingError as exc:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "Cycle/Step mapping preflight failed",
            {"status": "INVALID_MAPPING", "reason": str(exc)},
        ) from exc
    return {"data": result, "meta": {"read_only": True}}


@router.put("/experiments/{battery_id}/{experiment_id}/cycle-step-mapping")
def save_reviewed_cycle_step_mapping(
    request: Request,
    battery_id: str,
    experiment_id: str,
    body: CycleStepMappingSaveRequest,
) -> dict[str, Any]:
    """Persist an explicitly confirmed mapping outside immutable raw data."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if len(body.mapping_csv.encode("utf-8")) > 4_000_000:
        raise APIError(ErrorCode.UPLOAD_TOO_LARGE, "mapping CSV exceeds 4 MB")
    service = get_service(request)
    try:
        result = save_cycle_step_mapping(
            body.mapping_csv,
            confirm_reviewed=body.confirm_reviewed,
            expected_active_sha256=body.expected_active_sha256,
            raw_root=service.raw_root,
            processed_root=service.processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except CycleStepMappingConflict as exc:
        raise APIError(ErrorCode.CONFLICT, str(exc)) from exc
    except CycleStepMappingStoreError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    except CycleStepMappingError as exc:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "Cycle/Step mapping save failed",
            {"status": "INVALID_MAPPING", "reason": str(exc)},
        ) from exc
    return {"data": result, "meta": {"read_only": False}}

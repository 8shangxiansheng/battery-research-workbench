"""Read-only API preflight for operator-reviewed Cycle/Step mappings."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id
from battery_workbench.provenance.cycle_step_mapping import (
    CycleStepMappingError,
    validate_cycle_step_mapping,
)
from battery_workbench.provenance.cycle_step_mapping_store import (
    CycleStepMappingConflict,
    CycleStepMappingStoreError,
    get_cycle_step_mapping_status,
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

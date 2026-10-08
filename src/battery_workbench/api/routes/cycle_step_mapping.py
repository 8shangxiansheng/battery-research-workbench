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

router = APIRouter(tags=["scientific-resources"])


class CycleStepMappingPreflightRequest(BaseModel):
    """CSV bytes supplied by the operator; this endpoint never saves them."""

    mapping_csv: str = Field(min_length=1, max_length=4_000_000)


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

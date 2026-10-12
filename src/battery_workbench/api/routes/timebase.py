"""Evidence-submission and operator-review endpoints for timebase validation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.future_contracts import (
    TimebaseEvidencePreflightData,
    TimebaseEvidencePreflightEnvelope,
    TimebaseEvidencePreflightRequest,
    TimebaseReviewRequest,
    TimebaseValidationRequest,
)
from battery_workbench.api.service import validate_id
from battery_workbench.io.experiment.manifest_loader import data_asset_matches, load_data_assets
from battery_workbench.synchronization.timebase_evidence import (
    TimebaseEvidenceError,
    verify_timebase_evidence_files,
)
from battery_workbench.synchronization.timebase_registry import (
    TimebaseRegistryError,
    TimebaseRegistryIntegrityError,
    get_timebase_validation_record,
    list_timebase_validations,
    review_timebase_validation,
    submit_timebase_validation,
)

router = APIRouter(tags=["timebase-validation"])


@router.post(
    "/experiments/{battery_id}/{experiment_id}/timebase-evidence-preflight",
    response_model=TimebaseEvidencePreflightEnvelope,
)
def preflight_timebase_evidence(
    request: Request,
    battery_id: str,
    experiment_id: str,
    body: TimebaseEvidencePreflightRequest,
) -> TimebaseEvidencePreflightEnvelope:
    """Read-only file integrity check used to populate source hashes in the UI."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if body.battery_id != battery_id or body.experiment_id != experiment_id:
        raise APIError(ErrorCode.VALIDATION_ERROR, "path and body identity must match")
    try:
        verified_evidence = verify_timebase_evidence_files(
            get_service(request).raw_root,
            body.evidence_refs,
        )
    except TimebaseEvidenceError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    data = TimebaseEvidencePreflightData.model_validate(
        {
            "status": "SOURCE_FILES_VERIFIED",
            "source_integrity": "VERIFIED",
            "verified_evidence": verified_evidence,
        }
    )
    return TimebaseEvidencePreflightEnvelope(
        data=data,
        meta={"read_only": True, "scientific_validity": "NOT_ASSESSED"},
    )


@router.post("/experiments/{battery_id}/{experiment_id}/timebase-validations")
def create_timebase_validation(
    request: Request,
    battery_id: str,
    experiment_id: str,
    body: TimebaseValidationRequest,
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if body.battery_id != battery_id or body.experiment_id != experiment_id:
        raise APIError(ErrorCode.VALIDATION_ERROR, "path and body identity must match")
    service = get_service(request)
    manifest_path = service.raw_root / "manifests" / "data_assets.csv"
    if not manifest_path.is_file():
        raise APIError(ErrorCode.SCIENTIFIC_READINESS_BLOCKED, "DataAsset manifest is unavailable")
    assets = load_data_assets(manifest_path)
    known_asset_ids = {
        asset.asset_id for asset in assets if data_asset_matches(asset, battery_id, experiment_id)
    }
    unknown_assets = sorted({anchor.asset_id for anchor in body.anchors} - known_asset_ids)
    if unknown_assets:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "anchors must reference DataAsset IDs registered to this experiment",
            {"unknown_asset_ids": unknown_assets},
        )
    expected_anchor_hashes = {
        anchor.source_reference: anchor.source_sha256 for anchor in body.anchors
    }
    try:
        verified_evidence = verify_timebase_evidence_files(
            service.raw_root,
            body.evidence_refs,
            expected_sha256=expected_anchor_hashes,
        )
        if any(
            verified_evidence[anchor.source_reference]["sha256"].lower()
            != anchor.source_sha256.lower()
            for anchor in body.anchors
        ):
            raise TimebaseEvidenceError(
                "anchor source checksum does not match the raw evidence file"
            )
    except TimebaseEvidenceError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    data = submit_timebase_validation(
        body,
        processed_root=service.processed_root,
        verified_evidence=verified_evidence,
    )
    return {"data": data, "meta": {"read_only": False}}


@router.get("/experiments/{battery_id}/{experiment_id}/timebase-validations")
def list_timebase_validation_records(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    try:
        records = list_timebase_validations(
            processed_root=get_service(request).processed_root,
            raw_root=get_service(request).raw_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
    except TimebaseRegistryIntegrityError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    return {"data": {"validations": records}, "meta": {"read_only": True}}


@router.get("/experiments/{battery_id}/{experiment_id}/timebase-validations/{validation_id}")
def get_timebase_validation(
    request: Request, battery_id: str, experiment_id: str, validation_id: str
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if not validation_id.startswith("TBV::") or "/" in validation_id or ".." in validation_id:
        raise APIError(ErrorCode.VALIDATION_ERROR, "invalid validation_id")
    service = get_service(request)
    try:
        record = get_timebase_validation_record(
            processed_root=service.processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
            validation_id=validation_id,
            raw_root=service.raw_root,
        )
    except TimebaseRegistryIntegrityError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    except TimebaseRegistryError as exc:
        raise APIError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if record is None:
        raise APIError(ErrorCode.NOT_FOUND, "timebase validation not found")
    return {
        "data": {
            **record,
        },
        "meta": {"identity_trust": "OPERATOR_ASSERTED_UNAUTHENTICATED"},
    }


@router.post(
    "/experiments/{battery_id}/{experiment_id}/timebase-validations/{validation_id}/review"
)
def review_timebase(
    request: Request,
    battery_id: str,
    experiment_id: str,
    validation_id: str,
    body: TimebaseReviewRequest,
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    verified_evidence = None
    if body.evidence_refs:
        try:
            verified_evidence = verify_timebase_evidence_files(
                service.raw_root,
                body.evidence_refs,
            )
        except TimebaseEvidenceError as exc:
            raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    try:
        data = review_timebase_validation(
            battery_id,
            experiment_id,
            validation_id,
            body,
            processed_root=service.processed_root,
            verified_evidence=verified_evidence,
            raw_root=service.raw_root,
        )
    except TimebaseRegistryIntegrityError as exc:
        raise APIError(ErrorCode.INTEGRITY_ERROR, str(exc)) from exc
    except TimebaseRegistryError as exc:
        code = (
            ErrorCode.NOT_FOUND
            if "not found" in str(exc)
            else ErrorCode.SCIENTIFIC_READINESS_BLOCKED
        )
        raise APIError(code, str(exc)) from exc
    if verified_evidence is not None:
        data["evidence_integrity"] = "VERIFIED"
        data["verified_evidence"] = verified_evidence
    return {"data": data, "meta": {"read_only": False}}

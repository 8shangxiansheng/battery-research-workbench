"""BRW-024R Experiment Intake & Lifecycle API routes.

All intake operations go through the IntakeEngine (scientific core); routes
only validate, invoke, serialize, and map errors. Client never passes a
filesystem path — assets are uploaded via multipart body into managed staging.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id
from battery_workbench.intake.engine import IntakeEngine
from battery_workbench.intake.models import (
    AssetRole,
    ExperimentRecord,
    IntakePolicyError,
    IntakeSession,
)

router = APIRouter(tags=["intake", "experiments"])


def _engine(request: Request) -> IntakeEngine:
    service = get_service(request)
    engine = getattr(service, "intake", None)
    if engine is None:
        raise APIError(ErrorCode.UNSUPPORTED_OPERATION, "intake engine unavailable")
    return engine  # type: ignore[no-any-return]


def _session_or_404(engine: IntakeEngine, session_id: str) -> IntakeSession:
    try:
        return engine.load_session(session_id)
    except KeyError as e:
        raise APIError(ErrorCode.NOT_FOUND, "intake session not found") from e


def _policy_error(exc: IntakePolicyError) -> APIError:
    message = str(exc)
    if "too large" in message.lower():
        return APIError(ErrorCode.UPLOAD_TOO_LARGE, message)
    if "unsupported" in message.lower():
        return APIError(ErrorCode.UNSUPPORTED_FILE_FORMAT, message)
    if "ambiguous" in message.lower():
        return APIError(ErrorCode.AMBIGUOUS_ADAPTER, message)
    if "not validated" in message.lower() or "before validate" in message.lower():
        return APIError(ErrorCode.INTAKE_NOT_VALIDATED, message)
    if "already exists" in message.lower():
        return APIError(ErrorCode.CONFLICT, message)
    if "immutable" in message.lower() or "checksum conflict" in message.lower():
        return APIError(ErrorCode.INTEGRITY_ERROR, message)
    if (
        "limit reached" in message.lower()
        or "empty asset" in message.lower()
        or "unsafe filename" in message.lower()
    ):
        return APIError(ErrorCode.VALIDATION_ERROR, message)
    if "cannot be modified" in message.lower():
        code = ErrorCode.INTAKE_ALREADY_COMMITTED if "COMMITTED" in message else ErrorCode.CONFLICT
        return APIError(code, message)
    return APIError(ErrorCode.VALIDATION_ERROR, message)


def _experiment_summary(engine: IntakeEngine, record: ExperimentRecord) -> dict[str, Any]:
    return {
        "battery_id": record.battery_id,
        "experiment_id": record.experiment_id,
        "experiment_composite_id": record.composite_id,
        "name": record.name,
        "status": record.status,
        "is_demo": record.is_demo,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "notes": record.notes,
        "asset_summary": _asset_summary(engine, record),
        "latest_run": None,
        "readiness": None,  # scientific readiness stays separate (§2)
        "pending_actions": [],
    }


def _asset_summary(engine: IntakeEngine, record: ExperimentRecord) -> dict[str, Any]:
    assets_csv = engine.manifests_dir / "data_assets.csv"
    count = 0
    if assets_csv.is_file():
        import csv

        with assets_csv.open("r", encoding="utf-8") as handle:
            count = sum(
                1 for r in csv.DictReader(handle) if r.get("experiment_id") == record.experiment_id
            )
    return {"committed_assets": count, "intake_sessions": _session_count(engine, record)}


def _session_count(engine: IntakeEngine, record: ExperimentRecord) -> int:
    sessions_dir = engine.registry_root / "sessions"
    if not sessions_dir.is_dir():
        return 0
    return sum(
        1
        for p in sessions_dir.glob("*.json")
        if f'"{record.battery_id}/{record.experiment_id}"' in p.read_text(encoding="utf-8")
    )


# ---------- capabilities (§20) ----------
@router.get("/intake/capabilities")
def intake_capabilities(request: Request) -> dict[str, Any]:
    _engine(request)  # availability guard
    from battery_workbench.io.adapters.registry import build_default_adapter_registry

    registry = build_default_adapter_registry()
    adapters = []
    for modality in sorted(registry.modalities()):
        adapter = registry.get(modality)
        adapters.append(
            {
                "modality": modality,
                "adapter_id": adapter.adapter_name,
                "adapter_version": adapter.adapter_version,
            }
        )
    return {
        "data": {
            "adapters": adapters,
            "supported_roles": ["ELECTRICAL", "ULTRASOUND", "EXPERIMENT_METADATA", "AUXILIARY"],
            "file_limits": {"max_file_size_bytes": 100 * 1024 * 1024, "max_assets_per_session": 20},
            "format_hints": {
                "electrical": ".xlsx (BRW-003 custom_excel adapter)",
                "ultrasound": ".txt (BRW-005 custom_txt adapter)",
            },
            "extension_note": "extension/MIME is a hint only; detection reuses BRW-007 registry",
            "intake_policy_version": "0.1.0",
        },
        "meta": {},
    }


# ---------- experiment library (§3/§4/§27) ----------
@router.post("/experiments")
def create_experiment(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    engine = _engine(request)
    battery_id = body.get("battery_id", "")
    name = body.get("name", "")
    if not battery_id or not validate_id(battery_id, "battery_id"):
        raise APIError(ErrorCode.VALIDATION_ERROR, "battery_id required")
    if not name:
        raise APIError(ErrorCode.VALIDATION_ERROR, "name required")
    experiment_id = body.get("experiment_id")
    if experiment_id is not None:
        validate_id(experiment_id, "experiment_id")
    try:
        record = engine.create_experiment(
            battery_id=battery_id,
            experiment_id=experiment_id,
            name=name,
            is_demo=bool(body.get("is_demo", False)),
            notes=str(body.get("notes", "")),
        )
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    return {"data": _experiment_summary(engine, record), "meta": {}}


@router.get("/experiments")
def list_experiments_v2(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    battery_id: str | None = Query(default=None),
    is_demo: bool | None = Query(default=None),
) -> dict[str, Any]:
    engine = _engine(request)
    if not engine.raw_root.is_dir():
        raise APIError(ErrorCode.INTEGRITY_ERROR, "raw data environment unavailable")
    library = engine.load_library()
    items = [ExperimentRecord.model_validate(v) for v in library.values()]
    # legacy demo experiments (not in intake library) stay visible
    try:
        legacy = get_service(request).list_experiments()
    except APIError:
        legacy = []
        if status is None and battery_id is None and is_demo is None and cursor is None:
            pass
    known = {e.composite_id for e in items}
    for legacy_item in legacy if isinstance(legacy, list) else []:
        composite = legacy_item.get("experiment_composite_id")
        if composite and composite not in known:
            items.append(
                ExperimentRecord(
                    battery_id=legacy_item["battery_id"],
                    experiment_id=legacy_item["experiment_id"],
                    name=legacy_item.get("experiment_composite_id", composite),
                    status="READY",
                    is_demo=True,
                    created_at="",
                    updated_at="",
                )
            )
    if status:
        items = [e for e in items if e.status == status]
    if battery_id:
        items = [e for e in items if e.battery_id == battery_id]
    if is_demo is not None:
        items = [e for e in items if e.is_demo == is_demo]
    if cursor is not None and (
        "/" not in cursor or any(ch in cursor for ch in (" ", "\\", "%", ".."))
    ):
        raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cursor")
    items.sort(key=lambda e: e.composite_id)
    if cursor:
        items = [e for e in items if e.composite_id > cursor]
    page = items[:limit]
    next_cursor = page[-1].composite_id if len(items) > limit else None
    return {
        "data": {"experiments": [_experiment_summary(engine, e) for e in page]},
        "meta": {"limit": limit, "cursor": cursor, "next_cursor": next_cursor},
    }


@router.get("/experiments/{battery_id}/{experiment_id}")
def get_experiment_record(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Library record when present; otherwise legacy demo summary stays authoritative."""
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    try:
        record = engine.load_experiment(battery_id, experiment_id)
        return {"data": _experiment_summary(engine, record), "meta": {}}
    except KeyError:
        pass  # not in library → fall through to legacy demo summary
    return {"data": get_service(request).get_experiment(battery_id, experiment_id), "meta": {}}


@router.patch("/experiments/{battery_id}/{experiment_id}")
def patch_experiment(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    try:
        record = engine.load_experiment(battery_id, experiment_id)
    except KeyError as e:
        raise APIError(ErrorCode.NOT_FOUND, "experiment not found in library") from e
    if "name" in body:
        record.name = str(body["name"])
    if "notes" in body:
        record.notes = str(body["notes"])
    allowed_status = {"DRAFT", "AWAITING_DATA", "READY_FOR_PIPELINE", "ARCHIVED"}
    if "status" in body:
        if body["status"] not in allowed_status:
            raise APIError(ErrorCode.VALIDATION_ERROR, "status transition not allowed via PATCH")
        record.status = body["status"]
    record.updated_at = record.updated_at
    engine.save_experiment(record)
    engine.append_event("EXPERIMENT_UPDATED", detail={"composite_id": record.composite_id})
    return {"data": _experiment_summary(engine, record), "meta": {}}


@router.post("/experiments/{battery_id}/{experiment_id}/archive")
def archive_experiment(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    try:
        record = engine.archive_experiment(battery_id, experiment_id)
    except KeyError as e:
        raise APIError(ErrorCode.NOT_FOUND, "experiment not found in library") from e
    return {"data": _experiment_summary(engine, record), "meta": {}}


# ---------- intake sessions (§5) ----------
@router.post("/experiments/{battery_id}/{experiment_id}/intake-sessions")
def create_intake_session(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    try:
        session = engine.create_session(battery_id, experiment_id)
    except KeyError as e:
        raise APIError(ErrorCode.NOT_FOUND, "experiment not found in library") from e
    return {"data": _session_payload(engine, session), "meta": {}}


def _session_payload(engine: IntakeEngine, session: IntakeSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "experiment_composite_id": session.experiment_composite_id,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "assets": [a.model_dump(mode="json") for a in session.assets],
        "detections": [d.model_dump(mode="json") for d in session.detections],
        "validation": session.validation.model_dump(mode="json") if session.validation else None,
        "commit": session.commit.model_dump(mode="json") if session.commit else None,
        "failure_reason": session.failure_reason,
        "recommended_next_action": _recommended_action(session),
    }


def _recommended_action(session: IntakeSession) -> str | None:
    return {
        "DRAFT": "UPLOAD_ASSETS",
        "ASSETS_RECEIVED": "RUN_DETECT",
        "DETECTED": "RUN_VALIDATE",
        "VALIDATED": "RUN_COMMIT",
        "COMMITTED": "RUN_INGEST_TO_MEASUREMENT_EVENTS",
        "FAILED": "RESOLVE_FAILURE",
        "CANCELLED": None,
        "EXPIRED": None,
    }.get(session.status)


@router.get("/intake-sessions/{session_id}")
def get_intake_session(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    return {"data": _session_payload(engine, session), "meta": {}}


# ---------- assets (§7/§8) ----------
@router.post("/intake-sessions/{session_id}/assets")
async def upload_asset(
    request: Request,
    session_id: str,
    role: AssetRole = Form(...),  # noqa: B008 — FastAPI DI pattern
    file: UploadFile = File(...),  # noqa: B008 — FastAPI DI pattern
) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    if file.filename is None:
        raise APIError(ErrorCode.VALIDATION_ERROR, "filename required")
    content = await file.read()
    try:
        record = engine.store_asset(
            session, role=role, original_filename=file.filename, content=content
        )
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    return {"data": record.model_dump(mode="json"), "meta": {}}


@router.get("/intake-sessions/{session_id}/assets")
def list_session_assets(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    return {
        "data": {"assets": [a.model_dump(mode="json") for a in engine.list_assets(session)]},
        "meta": {},
    }


@router.get("/intake-sessions/{session_id}/assets/{intake_asset_id}/preview")
def preview_asset(request: Request, session_id: str, intake_asset_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    validate_id(intake_asset_id, "intake_asset_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    asset = next((a for a in session.assets if a.intake_asset_id == intake_asset_id), None)
    if asset is None:
        raise APIError(ErrorCode.NOT_FOUND, "staged asset not found")
    detection = next((d for d in session.detections if d.intake_asset_id == intake_asset_id), None)
    path = engine.staged_path(session, asset)
    if not path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "staged file missing")
    payload: dict[str, Any] = {
        "intake_asset_id": intake_asset_id,
        "role": asset.role,
        "sha256": asset.sha256,
        "size": asset.size,
        "detection": detection.model_dump(mode="json") if detection else None,
    }
    try:
        if detection and detection.modality == "electrical":
            from battery_workbench.io.electrical.custom_excel import read_electrical_workbook

            workbook = read_electrical_workbook(path)
            payload["preview"] = {
                "kind": "ELECTRICAL",
                "sheets": sorted(workbook.sheets.keys()),
                "row_counts": {name: len(sheet.rows) for name, sheet in workbook.sheets.items()},
            }
        elif detection and detection.modality == "ultrasound":
            from battery_workbench.io.ultrasound.custom_txt import inspect_ultrasound_txt

            inspection = inspect_ultrasound_txt(path)
            payload["preview"] = {
                "kind": "ULTRASOUND",
                "frame_count": inspection.frame_count,
                "samples_per_frame": sorted(inspection.waveform_lengths),
                "first_frame_id": inspection.first_frame_id,
                "last_frame_id": inspection.last_frame_id,
                "sampling_rate_hz": None,
                "sampling_rate_status": "UNKNOWN",
                "note": "10s frame cadence is not a waveform fs (§12)",
            }
        else:
            # undetected: bounded raw head, no full file dump (§10)
            head = path.read_text(encoding="utf-8", errors="replace")[:2000]
            payload["preview"] = {"kind": "RAW_HEAD", "head": head}
    except Exception as exc:
        raise APIError(
            ErrorCode.ARTIFACT_NOT_AVAILABLE, f"preview failed: {type(exc).__name__}"
        ) from exc
    return {"data": payload, "meta": {}}


# ---------- detect / validate / commit / cancel (§13) ----------
@router.post("/intake-sessions/{session_id}/detect")
def detect_session(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    try:
        detections = engine.detect(session)
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    ambiguous = any(d.state == "DETECTED_AMBIGUOUS" for d in detections)
    unsupported = any(d.state == "UNSUPPORTED" for d in detections)
    if unsupported:
        raise APIError(
            ErrorCode.UNSUPPORTED_FILE_FORMAT,
            "one or more assets have no registered adapter; intake stopped",
            {"detections": [d.model_dump(mode="json") for d in detections]},
        )
    if ambiguous:
        raise APIError(
            ErrorCode.AMBIGUOUS_ADAPTER,
            "multiple adapters matched; user confirmation required",
            {"detections": [d.model_dump(mode="json") for d in detections]},
        )
    return {"data": {"detections": [d.model_dump(mode="json") for d in detections]}, "meta": {}}


@router.post("/intake-sessions/{session_id}/validate")
def validate_session(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    try:
        validation = engine.validate(session)
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    if not validation.overall_passed:
        return {
            "data": {
                **validation.model_dump(mode="json"),
                "next_action": "RESOLVE_VALIDATION_FAILURES",
            },
            "meta": {},
        }
    return {"data": validation.model_dump(mode="json"), "meta": {}}


@router.post("/intake-sessions/{session_id}/commit")
def commit_session(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    try:
        result = engine.commit(session)
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    return {"data": result, "meta": {}}


@router.post("/intake-sessions/{session_id}/cancel")
def cancel_session(request: Request, session_id: str) -> dict[str, Any]:
    validate_id(session_id, "session_id")
    engine = _engine(request)
    session = _session_or_404(engine, session_id)
    try:
        session = engine.cancel(session)
    except IntakePolicyError as exc:
        raise _policy_error(exc) from exc
    return {"data": _session_payload(engine, session), "meta": {}}


# ---------- experiment-scoped reads (§15/§23) ----------
@router.get("/experiments/{battery_id}/{experiment_id}/assets")
def experiment_assets(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    assets_csv = engine.manifests_dir / "data_assets.csv"
    items: list[dict[str, Any]] = []
    if assets_csv.is_file():
        import csv

        with assets_csv.open("r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("experiment_id") == experiment_id:
                    items.append(row)
    return {"data": {"assets": items}, "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/intake-history")
def intake_history(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    composite = f"{battery_id}/{experiment_id}"
    sessions_dir = engine.registry_root / "sessions"
    items: list[dict[str, Any]] = []
    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.glob("*.json")):
            session = IntakeSession.model_validate_json(path.read_text(encoding="utf-8"))
            if session.experiment_composite_id == composite:
                items.append(
                    {
                        "session_id": session.session_id,
                        "status": session.status,
                        "asset_count": len(session.assets),
                        "validated": session.validation is not None
                        and session.validation.overall_passed,
                        "committed_at": session.commit.committed_at if session.commit else None,
                        "failure_reason": session.failure_reason,
                    }
                )
    items.sort(key=lambda x: str(x.get("committed_at") or ""))
    return {"data": {"history": items}, "meta": {}}


# ---------- lifecycle events (§28) ----------
@router.get("/experiments/{battery_id}/{experiment_id}/lifecycle-events")
def lifecycle_events(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    engine = _engine(request)
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    composite = f"{battery_id}/{experiment_id}"
    items: list[dict[str, Any]] = []
    events_path = engine.events_path()
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            detail = data.get("detail") or {}
            if detail.get("composite_id") == composite or (
                data.get("session_id")
                and str(data.get("session_id")).startswith("INTAKE::")
                and composite in json.dumps(detail)
            ):
                items.append(data)
    return {"data": {"events": items}, "meta": {}}

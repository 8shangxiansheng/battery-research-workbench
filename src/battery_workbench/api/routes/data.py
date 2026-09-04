"""BRW-025R API additive endpoints (read-only / lifecycle-only).

- GET  /experiments/{b}/{e}/data-quality — aggregated parquet metadata, no recompute
- GET  /experiments/{b}/{e}/synchronization — sync state summary
- GET  /experiments/{b}/{e}/measurement-events — paginated event preview
- POST /experiments/{b}/{e}/load-demo — register the shipped demo in the intake
  library (lifecycle-only; is_demo=true; no raw data is copied)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Query, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.routes.intake import _experiment_summary
from battery_workbench.api.service import validate_id

router = APIRouter(tags=["experiments", "data"])


def _processed(request: Request) -> Path:
    return get_service(request).processed_root


@router.get("/experiments/{battery_id}/{experiment_id}/data-quality")
def data_quality(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    processed = _processed(request)
    out: dict[str, Any] = {
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "electrical": None,
        "ultrasound": None,
    }
    records_path = processed / "electrical" / battery_id / experiment_id / "records.parquet"
    if records_path.is_file():
        records = pd.read_parquet(records_path)
        duplicate_ts = (
            int(records["timestamp"].duplicated().sum()) if "timestamp" in records.columns else None
        )
        out["electrical"] = {
            "records": len(records),
            "cycles": int(records["cycle_index_raw"].nunique())
            if "cycle_index_raw" in records.columns
            else None,
            "steps": int(records["step_index_raw"].nunique())
            if "step_index_raw" in records.columns
            else None,
            "duplicate_timestamps": duplicate_ts,
        }
    frames_path = processed / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    if frames_path.is_file():
        frames = pd.read_parquet(frames_path)
        cadence = frames["elapsed_time_s"].diff().median() if "elapsed_time_s" in frames.columns else None
        out["ultrasound"] = {
            "frames": len(frames),
            "frame_cadence_s": round(float(cadence), 4) if pd.notna(cadence) else None,
            "sampling_rate_hz": None,
            "sampling_rate_status": "UNKNOWN",
            "note": "frame cadence is not a waveform sampling rate",
        }
    return {"data": out, "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/synchronization")
def synchronization(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    processed = _processed(request)
    sync_dir = processed / "synchronization" / battery_id / experiment_id
    manifest_path = sync_dir / "synchronization_manifest.json"
    if not manifest_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "synchronization manifest not available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    anchor_path = sync_dir / "time_anchors.json"
    anchors = json.loads(anchor_path.read_text(encoding="utf-8")) if anchor_path.is_file() else None
    ambiguous_frames = manifest.get("ambiguous_frames") or manifest.get("ambiguous") or []
    return {
        "data": {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "matches_frames": manifest.get("matches_frames"),
            "match_state": "MATCHED_UNIQUE" if manifest.get("matches_frames") else "AMBIGUOUS",
            "ambiguous_frames": ambiguous_frames,
            "sync_tolerance_s": manifest.get("sync_tolerance_s"),
            "validated_sync": bool(anchors.get("validated_sync", False)) if anchors else False,
            "timebase_status": manifest.get("timebase_status", "PROVISIONAL"),
            "note": "PROVISIONAL timebase is not a software error",
        },
        "meta": {},
    }


@router.get("/experiments/{battery_id}/{experiment_id}/measurement-events")
def measurement_events(
    request: Request,
    battery_id: str,
    experiment_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: int | None = Query(default=None),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    processed = _processed(request)
    events_path = processed / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    if not events_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    events = pd.read_parquet(events_path)
    if cursor is not None:
        events = events[events.index >= cursor]
    page = events.head(limit)
    columns = [
        col
        for col in (
            "measurement_event_id",
            "frame_index_raw",
            "timestamp",
            "cycle_index_raw",
            "step_index_raw",
            "voltage_v",
            "current_a",
            "soc_reference_percent",
        )
        if col in page.columns
    ]
    rows = page[columns].astype(object).where(page[columns].notna(), None).to_dict("records")
    next_cursor = int(page.index[-1]) + 1 if len(events) > limit and len(page) else None
    return {
        "data": {
            "total": len(events),
            "events": rows,
        },
        "meta": {"limit": limit, "cursor": cursor, "next_cursor": next_cursor},
    }


@router.post("/experiments/{battery_id}/{experiment_id}/load-demo")
def load_demo(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Register a shipped demo experiment in the intake library (lifecycle-only).

    No raw/processed data is copied; the library entry points at the existing
    demo artifacts and is flagged is_demo=true.
    """
    engine = get_service(request).intake
    engine._ensure_dirs()
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    experiments_csv = engine.manifests_dir / "experiments.csv"
    if not experiments_csv.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "demo manifests not available")
    import csv

    with experiments_csv.open("r", encoding="utf-8") as handle:
        demo_rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("battery_id") == battery_id and row.get("experiment_id") == experiment_id
        ]
    if not demo_rows:
        raise APIError(ErrorCode.NOT_FOUND, "experiment not found in demo manifests")
    library = engine.load_library()
    composite = f"{battery_id}/{experiment_id}"
    if composite in library:
        existing = library[composite]
        if existing.get("is_demo"):
            return {"data": existing, "meta": {}}  # idempotent
        raise APIError(ErrorCode.CONFLICT, "experiment already exists in library")
    from battery_workbench.intake.models import ExperimentRecord, utc_now_iso

    now = utc_now_iso()
    record = ExperimentRecord(
        battery_id=battery_id,
        experiment_id=experiment_id,
        name=f"Demo {composite}",
        status="READY",
        is_demo=True,
        created_at=now,
        updated_at=now,
        notes="shipped regression/demo experiment",
    )
    library[composite] = record.model_dump(mode="json")
    engine.experiments_library_path().write_text(
        json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    engine.append_event("EXPERIMENT_CREATED", detail={"composite_id": composite, "is_demo": True})
    return {"data": _experiment_summary(engine, record), "meta": {}}

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
    metrics = manifest.get("quality_metrics") or {}
    anchor_assets = (anchors or {}).get("assets") or []
    asset_summaries = []
    for asset in anchor_assets:
        candidates = asset.get("candidates") or []
        selected_id = asset.get("selected_anchor_id")
        selected = next(
            (candidate for candidate in candidates if candidate.get("anchor_id") == selected_id),
            None,
        )
        asset_summaries.append(
            {
                "asset_id": asset.get("asset_id"),
                "modality": asset.get("modality"),
                "elapsed_min_s": asset.get("elapsed_min_s"),
                "elapsed_max_s": asset.get("elapsed_max_s"),
                "anchor_status": asset.get("anchor_status") or "UNVERIFIED",
                "selected_anchor_id": selected_id,
                "anchor_datetime": selected.get("anchor_datetime") if selected else None,
                "source_type": selected.get("source_type") if selected else None,
                "source_ref": selected.get("source_ref") if selected else None,
                "timezone_known": bool(selected.get("timezone_known", False)) if selected else False,
                "timezone_name": selected.get("timezone_name") if selected else None,
                "candidates": [
                    {
                        "anchor_id": item.get("anchor_id"),
                        "anchor_datetime": item.get("anchor_datetime"),
                        "source_type": item.get("source_type"),
                        "source_ref": item.get("source_ref"),
                        "status": item.get("status"),
                        "timezone_known": bool(item.get("timezone_known", False)),
                        "timezone_name": item.get("timezone_name"),
                    }
                    for item in candidates
                ],
                "evidence": [
                    {
                        "source_type": item.get("source_type"),
                        "source_ref": item.get("source_ref"),
                        "source_sha256": item.get("source_sha256"),
                        "raw_value": item.get("raw_value"),
                        "parsed_value": item.get("parsed_value"),
                        "supports_candidate": item.get("supports_candidate"),
                        "conflicts_with_candidate": item.get("conflicts_with_candidate"),
                        "message": item.get("message"),
                    }
                    for item in asset.get("evidence") or []
                ],
                "conflicts": [
                    {
                        "source_type": item.get("source_type"),
                        "source_ref": item.get("source_ref"),
                        "source_sha256": item.get("source_sha256"),
                        "raw_value": item.get("raw_value"),
                        "parsed_value": item.get("parsed_value"),
                        "supports_candidate": item.get("supports_candidate"),
                        "message": item.get("message"),
                    }
                    for item in asset.get("conflicts") or []
                ],
            }
        )
    electrical_assets: list[dict[str, Any]] = []
    mixed_clock_assets: list[str] = []
    coverage_overlaps: list[dict[str, Any]] = []
    incompatible_clock_pairs: list[list[str]] = []
    records_path = processed / "electrical" / battery_id / experiment_id / "records.parquet"
    if records_path.is_file():
        records = pd.read_parquet(records_path)
        if {"electrical_asset_id", "timestamp"}.issubset(records.columns):
            ranges: list[dict[str, Any]] = []
            for asset_id, group in records.groupby("electrical_asset_id", dropna=False, sort=True):
                timestamps = group["timestamp"].dropna()
                if timestamps.empty:
                    continue
                try:
                    timezone = timestamps.dt.tz
                except (AttributeError, TypeError):
                    timezone = None
                timestamp_values = [pd.Timestamp(value) for value in timestamps]
                awareness = {value.tzinfo is not None for value in timestamp_values}
                try:
                    timestamp_min = pd.Timestamp(timestamps.min())
                    timestamp_max = pd.Timestamp(timestamps.max())
                except (TypeError, ValueError):
                    timestamp_min = timestamp_max = None
                mixed = len(awareness) != 1 or timestamp_min is None or timestamp_max is None
                aware = next(iter(awareness)) if len(awareness) == 1 and not mixed else None
                item = {
                    "electrical_asset_id": str(asset_id),
                    "record_count": len(group),
                    "timestamp_min": timestamp_min.isoformat() if timestamp_min is not None else None,
                    "timestamp_max": timestamp_max.isoformat() if timestamp_max is not None else None,
                    "timestamp_representation": "MIXED"
                    if mixed
                    else ("OFFSET_AWARE" if aware else "NAIVE"),
                    "timezone_known": bool(aware),
                    "timezone_name": (
                        str(timezone)
                        if aware and timezone is not None
                        else (
                            ", ".join(sorted({str(value.tzinfo) for value in timestamp_values}))
                            if aware
                            else None
                        )
                    ),
                    "source_files": sorted(
                        str(value)
                        for value in group["source_file"].dropna().astype(str).unique()
                    )
                    if "source_file" in group
                    else [],
                    "source_row_min": int(group["source_row_index"].min())
                    if "source_row_index" in group and group["source_row_index"].notna().any()
                    else None,
                    "source_row_max": int(group["source_row_index"].max())
                    if "source_row_index" in group and group["source_row_index"].notna().any()
                    else None,
                }
                electrical_assets.append(item)
                if item["timestamp_representation"] == "MIXED":
                    mixed_clock_assets.append(str(asset_id))
                ranges.append(
                    {
                        "asset_id": str(asset_id),
                        "start": timestamp_min,
                        "end": timestamp_max,
                        "aware": aware,
                    }
                )
            for index, left in enumerate(ranges):
                for right in ranges[index + 1 :]:
                    if left["aware"] is None or right["aware"] is None or left["aware"] != right["aware"]:
                        incompatible_clock_pairs.append([left["asset_id"], right["asset_id"]])
                        continue
                    try:
                        overlap_s = (
                            min(left["end"], right["end"]) - max(left["start"], right["start"])
                        ).total_seconds()
                    except TypeError:
                        incompatible_clock_pairs.append([left["asset_id"], right["asset_id"]])
                        continue
                    if overlap_s > 0:
                        coverage_overlaps.append(
                            {
                                "asset_ids": [left["asset_id"], right["asset_id"]],
                                "overlap_seconds": overlap_s,
                                "basis": "UTC_INSTANT" if left["aware"] else "NAIVE_WALL_CLOCK",
                            }
                        )
    quality_available = "matched_unique_count" in metrics and "matched_ambiguous_count" in metrics
    ambiguous_count = int(metrics.get("matched_ambiguous_count", 0) or 0)
    unique_count = int(metrics.get("matched_unique_count", 0) or 0)
    blocked_count = int(
        (metrics.get("timestamp_unavailable_count", 0) or 0)
        + (metrics.get("no_candidate_count", 0) or 0)
        + (metrics.get("out_of_tolerance_count", 0) or 0)
        + (metrics.get("timezone_mismatch_count", 0) or 0)
    )
    has_anchor_blocker = not anchor_assets or any(
        asset.get("anchor_status") in {"CONFLICTING", "UNVERIFIED", "REJECTED"}
        or not asset.get("selected_anchor_id")
        for asset in anchor_assets
    )
    if has_anchor_blocker:
        match_state = "BLOCKED_TIMEBASE"
    elif not quality_available:
        match_state = "UNKNOWN"
    elif unique_count == 0 and ambiguous_count == 0:
        match_state = "NO_MATCH"
    elif ambiguous_count or blocked_count:
        match_state = "PARTIAL"
    else:
        match_state = "MATCHED_UNIQUE"
    ambiguous_frames = manifest.get("ambiguous_frames") or manifest.get("ambiguous") or []
    total_frames = metrics.get("total_ultrasound_frames", manifest.get("ultrasound_row_count"))
    aligned_rows = manifest.get("matches_frames")
    return {
        "data": {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            # Keep the historical field for compatibility; it counts rows in
            # the aligned artifact, not necessarily successful unique matches.
            "matches_frames": aligned_rows,
            "aligned_rows": aligned_rows,
            "total_frames": total_frames,
            "candidate_matched_frames": unique_count + ambiguous_count if quality_available else None,
            "match_state": match_state,
            "match_counts": {
                "matched_unique": unique_count if quality_available else None,
                "matched_ambiguous": ambiguous_count,
                "out_of_tolerance": int(metrics.get("out_of_tolerance_count", 0) or 0),
                "timestamp_unavailable": int(metrics.get("timestamp_unavailable_count", 0) or 0),
                "no_candidate": int(metrics.get("no_candidate_count", 0) or 0),
                "timezone_mismatch": int(metrics.get("timezone_mismatch_count", 0) or 0),
            },
            "ambiguous_frames": ambiguous_frames,
            "time_anchors": asset_summaries,
            "electrical_assets": electrical_assets,
            "electrical_mixed_clock_assets": mixed_clock_assets,
            "electrical_coverage_overlaps": coverage_overlaps,
            "electrical_incompatible_clock_pairs": incompatible_clock_pairs,
            "time_anchor_warnings": (anchors or {}).get("warnings") or [],
            "time_anchor_limitations": (anchors or {}).get("limitations") or [],
            "experiment_time_reference": (anchors or {}).get("experiment_reference"),
            "timebase_conflicts": [
                asset["asset_id"]
                for asset in asset_summaries
                if asset["conflicts"] or asset["anchor_status"] == "CONFLICTING"
            ],
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
    asset_id: str | None = Query(default=None),
    frame_index: int | None = Query(default=None),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    processed = _processed(request)
    events_path = processed / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    if not events_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    events = pd.read_parquet(events_path)
    # asset/frame scoping keeps the electrical context tied to the exact
    # ultrasound asset + frame being viewed (cross-asset context, not a
    # shared first-N preview)
    if asset_id is not None and "ultrasound_asset_id" in events.columns:
        events = events[events["ultrasound_asset_id"].astype(str) == asset_id]
    if frame_index is not None and "frame_index_raw" in events.columns:
        events = events[events["frame_index_raw"].astype("Int64") == frame_index]
    if cursor is not None:
        events = events[events.index >= cursor]
    page = events.head(limit)
    columns = [
        col
        for col in (
            "measurement_event_id",
            "frame_index_raw",
            "timestamp",
            "provisional_absolute_timestamp",
            "cycle_index_raw",
            "step_index_raw",
            "voltage_v",
            "current_a",
            "soc_reference_percent",
            "step_type",
            "temperature_c",
            "sync_error_s",
            "match_status",
            "sync_ambiguous",
            "anchor_status",
            "source_file",
            "ultrasound_asset_id",
            "electrical_asset_id",
            "electrical_timestamp",
        )
        if col in page.columns
    ]
    rows = page[columns].astype(object).where(page[columns].notna(), None).to_dict("records")
    # Reference SOC is a LABEL artifact (event_labels.parquet), not an event
    # column — join by measurement_event_id so the header never confuses it
    # with the raw electrical soc_dod. Ambiguous/unlabeled events stay null.
    label_source = "UNAVAILABLE"
    labels_path = processed / "labels" / battery_id / experiment_id / "event_labels.parquet"
    if labels_path.is_file():
        lab = pd.read_parquet(
            labels_path, columns=["measurement_event_id", "soc_reference_percent"]
        )
        soc_map = dict(
            zip(lab["measurement_event_id"], lab["soc_reference_percent"], strict=False)
        )
        for r in rows:
            value = soc_map.get(r.get("measurement_event_id"))
            r["soc_reference_percent"] = None if pd.isna(value) else float(value)
        label_source = f"labels/{battery_id}/{experiment_id}/event_labels.parquet"
    next_cursor = int(page.index[-1]) + 1 if len(events) > limit and len(page) else None
    return {
        "data": {
            "total": len(events),
            "events": rows,
        },
        "meta": {
            "limit": limit,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "soc_reference_label_source": label_source,
        },
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

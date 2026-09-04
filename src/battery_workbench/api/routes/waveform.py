"""Waveform preview + runs list routes (BRW-025 UI support).

Read-only. Frames come from the canonical waveform store; responses are
downsampled and bounded. Without a verified sampling rate the x-axis stays
SAMPLE_INDEX — the UI never receives a fabricated time axis.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

router = APIRouter(tags=["experiments", "runs"])

MAX_PREVIEW_POINTS = 1000


@router.get("/experiments/{battery_id}/{experiment_id}/waveform-frames")
def list_waveform_frames(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    frames_path = (
        service.processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    )
    if not frames_path.is_file():
        raise APIError(
            ErrorCode.ARTIFACT_NOT_AVAILABLE,
            "waveform frame store not available",
        )
    import pandas as pd

    frames = pd.read_parquet(
        frames_path,
        columns=[
            "frame_index_raw",
            "waveform_group",
            "waveform_row_index",
            "waveform_sample_count",
        ],
    ).reset_index(drop=True)
    items = [
        {
            "frame_index": int(str(r.frame_index_raw)),
            "waveform_group": str(r.waveform_group),
            "waveform_row_index": int(str(r.waveform_row_index)),
            "sample_count": int(str(r.waveform_sample_count)),
        }
        for r in frames.itertuples()
    ]
    # frame metadata only; no waveforms here
    return {
        "data": {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "frame_count": len(items),
            "waveform_length": int(str(items[0]["sample_count"])) if items else 0,
            "x_axis": "SAMPLE_INDEX",
            "time_axis_available": False,
            "frames": items,
        },
        "meta": {},
    }


@router.get("/experiments/{battery_id}/{experiment_id}/waveform-frames/{frame_index}")
def get_waveform_frame(
    request: Request,
    battery_id: str,
    experiment_id: str,
    frame_index: int,
    max_points: int = Query(default=500, ge=1, le=MAX_PREVIEW_POINTS),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    if max_points > MAX_PREVIEW_POINTS:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            f"preview capped at {MAX_PREVIEW_POINTS} points",
        )
    service = get_service(request)
    base = service.processed_root / "ultrasound" / battery_id / experiment_id
    frames_path = base / "frames.parquet"
    store_path = base / "waveforms.zarr"
    if not frames_path.is_file() or not store_path.is_dir():
        raise APIError(
            ErrorCode.ARTIFACT_NOT_AVAILABLE,
            "waveform store not available",
        )
    import numpy as np
    import pandas as pd
    import zarr

    frames = pd.read_parquet(
        frames_path, columns=["frame_index_raw", "waveform_group", "waveform_row_index"]
    ).reset_index(drop=True)
    row = frames[frames["frame_index_raw"] == frame_index]
    if row.empty:
        raise APIError(ErrorCode.NOT_FOUND, "frame not found")
    r = row.iloc[0]
    zg = zarr.open_group(str(store_path), mode="r")
    wave = np.asarray(
        zg[str(r.waveform_group)][int(str(r.waveform_row_index))]  # type: ignore[index]
    )
    length = int(wave.shape[0])
    step = -(-length // max_points)  # ceil division: points <= max_points
    downsampled = [
        {"sample_index": int(i), "amplitude_a_u": float(wave[i])} for i in range(0, length, step)
    ]
    return {
        "data": {
            "frame_index": int(frame_index),
            "waveform_group": str(r.waveform_group),
            "waveform_row_index": int(r.waveform_row_index),
            "waveform_length": length,
            "x_axis": "SAMPLE_INDEX",
            "time_axis_us": None,
            "sampling_rate_status": "NOT_VERIFIED",
            "max_points": max_points,
            "samples": downsampled,
        },
        "meta": {},
    }


@router.get("/runs")
def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    service = get_service(request)
    runs: list[dict[str, Any]] = []
    if service.runs_root.is_dir():
        for manifest in sorted(service.runs_root.rglob("run_manifest.json"), reverse=True):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and data.get("run_id"):
                runs.append(
                    {
                        "run_id": data["run_id"],
                        "status": data.get("status", ""),
                        "profile": data.get("profile", data.get("plan_profile", "")),
                    }
                )
            if len(runs) >= limit + (1 if cursor else 0):
                break
    if cursor:
        runs = [r for r in runs if r["run_id"] > cursor]
    page = runs[:limit]
    next_cursor = page[-1]["run_id"] if len(runs) > limit else None
    return {
        "data": {"runs": page},
        "meta": {"limit": limit, "cursor": cursor, "next_cursor": next_cursor},
    }

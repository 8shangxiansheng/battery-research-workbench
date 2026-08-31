from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class TimeAnchor(BaseModel):
    asset_id: str
    file_start_time: datetime
    source: str = "manifest"


class SyncMatch(BaseModel):
    ultrasound_asset_id: str
    ultrasound_frame_index: int
    ultrasound_timestamp: datetime
    electrical_asset_id: str
    electrical_record_index: int
    electrical_timestamp: datetime
    sync_error_s: float


class SyncQualityReport(BaseModel):
    total_ultrasound_frames: int
    matched_frames: int
    unmatched_frames: int
    match_rate: float
    median_sync_error_s: float | None = None
    max_sync_error_s: float | None = None

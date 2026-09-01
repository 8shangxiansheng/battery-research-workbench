from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MeasurementEvent(BaseModel):
    event_id: str
    battery_id: str
    experiment_id: str

    ultrasound_asset_id: str
    ultrasound_frame_index: int
    ultrasound_timestamp: datetime

    electrical_asset_id: str | None = None
    electrical_record_index: int | None = None
    electrical_timestamp: datetime | None = None

    sync_error_s: float | None = None
    sync_quality: str | None = None
    boundary_flag: bool = False

    cycle: int | None = None
    step: int | None = None
    step_type: str | None = None

    voltage_v: float | None = None
    current_a: float | None = None
    capacity_ah: float | None = None
    soc_percent: float | None = None
    soh_percent: float | None = None
    temperature_c: float | None = None

    metadata: dict[str, object] = Field(default_factory=dict)

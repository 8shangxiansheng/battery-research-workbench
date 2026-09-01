from __future__ import annotations

from pydantic import BaseModel, Field


class BatteryCell(BaseModel):
    battery_id: str
    chemistry: str | None = None
    nominal_capacity_ah: float | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

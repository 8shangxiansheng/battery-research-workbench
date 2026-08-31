from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class Experiment(BaseModel):
    experiment_id: str
    battery_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    protocol: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

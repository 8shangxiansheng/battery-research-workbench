from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field


Modality = Literal["electrical", "ultrasound"]


class DataAsset(BaseModel):
    asset_id: str
    experiment_id: str
    modality: Modality
    relative_path: Path
    file_start_time: datetime | None = None
    file_end_time: datetime | None = None
    sha256: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

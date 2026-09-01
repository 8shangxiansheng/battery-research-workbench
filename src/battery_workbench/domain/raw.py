from __future__ import annotations

from pydantic import BaseModel

from battery_workbench.domain.asset import DataAsset


class ElectricalExperiment(BaseModel):
    """Standardized representation placeholder for one electrical experiment.

    The detailed record/cycle/step tables are implemented in BRW-003.
    """

    source: DataAsset | None = None
    sheets: dict[str, tuple[int, int]] = {}


class UltrasoundFrame(BaseModel):
    """One raw ultrasound frame from the current TXT contract."""

    frame_index: int
    unknown_field_1: str
    elapsed_time_s: float
    unknown_meta_pair: tuple[str, str]
    waveform: list[int]
    unknown_tail: list[str]

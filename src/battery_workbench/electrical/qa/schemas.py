from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class NumericBounds(BaseModel):
    min: float
    max: float


class TemporalConfig(BaseModel):
    duplicate_timestamps_are_fatal: bool = False
    large_gap_warning_s: float = 5.0


class CrossTableConfig(BaseModel):
    timestamp_tolerance_s: float = 1.0
    numeric_relative_tolerance: float = 0.01


class FigureConfig(BaseModel):
    dpi: int = 150
    format: str = "png"


class ElectricalQAConfig(BaseModel):
    version: str = "0.1.0"
    required_columns: list[str] = Field(
        default_factory=lambda: [
            "battery_id",
            "experiment_id",
            "electrical_asset_id",
            "source_file",
            "source_sheet",
            "source_row_index",
            "timestamp",
            "cycle_index_raw",
            "step_index_raw",
            "current_a",
            "voltage_v",
            "capacity_ah",
        ]
    )
    temporal: TemporalConfig = Field(default_factory=TemporalConfig)
    physical_bounds: dict[str, NumericBounds] = Field(
        default_factory=lambda: {
            "voltage_v": NumericBounds(min=0.0, max=5.0),
            "current_a": NumericBounds(min=-30.0, max=30.0),
            "capacity_ah": NumericBounds(min=0.0, max=1000.0),
            "temperature_c": NumericBounds(min=-20.0, max=80.0),
            "soc_dod_percent": NumericBounds(min=0.0, max=100.0),
        }
    )
    cross_table: CrossTableConfig = Field(default_factory=CrossTableConfig)
    figures: FigureConfig = Field(default_factory=FigureConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ElectricalQAConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["electrical_qa"]
        schema = payload.pop("schema", {})
        if "required_columns" in schema:
            payload["required_columns"] = schema["required_columns"]
        return cls.model_validate(payload)


class QAAnomaly(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    scope: str
    message: str
    count: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class ElectricalQAReport(BaseModel):
    battery_id: str
    experiment_id: str
    qa_version: str
    inputs: dict[str, Any]
    summary: dict[str, Any]
    schema_report: dict[str, Any] = Field(alias="schema")
    completeness: dict[str, Any]
    temporal: dict[str, Any]
    cycles: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    physical_ranges: dict[str, Any]
    cross_table: dict[str, Any]
    anomalies: list[QAAnomaly]
    warnings: list[str]
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    artifacts: dict[str, str]
    configuration: dict[str, Any]

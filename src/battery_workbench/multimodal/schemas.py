"""Typed models for BRW-011 MeasurementEvent canonical multimodal layer.

One ``CanonicalMeasurementEvent`` corresponds to exactly one aligned ultrasound
frame. ``validated_sync`` is always ``False``; ``matching_recomputed`` is always
``False`` — this layer propagates BRW-010 state, it never re-matches.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

EventQualityStatus = Literal[
    "READY",
    "AMBIGUOUS_SYNC",
    "OUT_OF_TOLERANCE",
    "TIMESTAMP_UNAVAILABLE",
    "INTEGRITY_ERROR",
]
MatchStatus = Literal[
    "MATCHED_UNIQUE",
    "MATCHED_AMBIGUOUS",
    "OUT_OF_TOLERANCE",
    "TIMESTAMP_UNAVAILABLE",
    "NO_ELECTRICAL_CANDIDATE",
    "TIMEZONE_MISMATCH",
]
ReportStatus = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]

# Bounded electrical enrichment whitelist (logical canonical names).
_ELECTRICAL_ENRICHMENT_FIELDS = [
    "cycle_index_raw",
    "step_index_raw",
    "step_type",
    "voltage_v",
    "current_a",
    "capacity_ah",
    "charge_capacity_ah",
    "discharge_capacity_ah",
    "energy_wh",
    "power_w",
    "temperature_c",
    "soc_dod_percent",
    "contact_resistance_mohm",
    "dq_dv_raw",
]


class QualityConfig(BaseModel):
    analysis_eligible_statuses: list[str] = ["READY"]


class ElectricalEnrichmentConfig(BaseModel):
    fields: list[str] = Field(default_factory=lambda: list(_ELECTRICAL_ENRICHMENT_FIELDS))


class ScientificGuardConfig(BaseModel):
    allow_timestamp_rematching: bool = False
    allow_ambiguous_candidate_selection: bool = False
    allow_interpolation: bool = False
    allow_drift_correction: bool = False
    allow_feature_extraction: bool = False
    allow_validated_sync_upgrade: bool = False


class MeasurementEventConfig(BaseModel):
    version: str = "0.1.0"
    quality: QualityConfig = Field(default_factory=QualityConfig)
    electrical_enrichment: ElectricalEnrichmentConfig = Field(
        default_factory=ElectricalEnrichmentConfig
    )
    scientific_guards: ScientificGuardConfig = Field(default_factory=ScientificGuardConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> MeasurementEventConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "measurement_event" in payload:
            payload = payload["measurement_event"]
        return cls.model_validate(payload)


class CanonicalMeasurementEvent(BaseModel):
    """One canonical multimodal event per aligned ultrasound frame."""

    measurement_event_id: str
    battery_id: str
    experiment_id: str

    # Ultrasound identity.
    ultrasound_asset_id: str
    frame_index_raw: int
    event_order_index: int
    source_file: str | None = None
    source_line_index: int | None = None
    waveform_group: str | None = None
    waveform_row_index: int | None = None

    # Time.
    provisional_absolute_timestamp: datetime | None = None
    elapsed_time_s: float | None = None
    timezone_known: bool = False
    timezone_name: str | None = None

    # Synchronization (propagated, never recomputed).
    match_status: MatchStatus
    sync_error_s: float | None = None
    within_tolerance: bool = False
    candidate_timestamp_count: int = 0
    candidate_record_count: int = 0
    sync_ambiguous: bool = False
    ambiguity_type: str | None = None
    boundary_flag: bool = False
    boundary_reason: str | None = None
    matching_performed: bool = True
    validated_sync: bool = False
    sync_semantics: str = "MATCHED_USING_PROVISIONAL_TIMEBASE"
    anchor_id: str | None = None
    anchor_status: str | None = None

    # Selected electrical identity (null for ambiguous/OOT/unavailable).
    electrical_asset_id: str | None = None
    electrical_record_locator: str | None = None
    electrical_row_index: int | None = None
    electrical_timestamp: datetime | None = None

    # Electrical state (exact-joined only for READY).
    cycle_index_raw: int | None = None
    step_index_raw: int | None = None
    step_type: str | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    capacity_ah: float | None = None
    charge_capacity_ah: float | None = None
    discharge_capacity_ah: float | None = None
    energy_wh: float | None = None
    power_w: float | None = None
    temperature_c: float | None = None
    soc_dod_percent: float | None = None
    contact_resistance_mohm: float | None = None
    dq_dv_raw: float | None = None

    # Quality.
    event_quality_status: EventQualityStatus
    analysis_eligible: bool = False
    event_quality_reason: str = ""


class MeasurementEventCandidate(BaseModel):
    """One nearest candidate record (relation to a canonical event)."""

    measurement_event_id: str
    battery_id: str
    experiment_id: str
    ultrasound_asset_id: str
    frame_index_raw: int
    ultrasound_timestamp: datetime | None = None
    electrical_timestamp: datetime | None = None
    electrical_record_locator: str | None = None
    electrical_row_index: int | None = None
    electrical_asset_id: str | None = None
    sync_error_s: float | None = None
    within_tolerance: bool = False
    candidate_timestamp_rank: int = 1
    candidate_record_rank: int = 1
    electrical_timestamp_duplicate_count: int = 1
    boundary_flag: bool = False
    boundary_reason: str | None = None


class MeasurementEventManifest(BaseModel):
    builder_name: str = "measurement_event_builder"
    builder_version: str = "0.1.0"
    battery_id: str
    experiment_id: str
    input_paths: dict[str, str] = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)
    aligned_row_count: int = 0
    sync_candidate_row_count: int = 0
    electrical_row_count: int = 0
    aux_temperature_row_count: int = 0
    event_row_count: int = 0
    event_candidate_row_count: int = 0
    quality_counts: dict[str, int] = Field(default_factory=dict)
    analysis_eligible_count: int = 0
    analysis_eligible_fraction: float = 0.0
    electrical_enrichment_fields: list[str] = Field(default_factory=list)
    aux_temperature_coverage: dict[str, int] = Field(default_factory=dict)
    matching_recomputed: bool = False
    validated_sync: bool = False
    output_paths: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MeasurementEventReport(BaseModel):
    battery_id: str
    experiment_id: str
    builder_version: str
    event_count: int
    quality_counts: dict[str, int]
    analysis_eligible_count: int
    analysis_eligible_fraction: float
    electrical_enrichment_fields: list[str]
    synced_source: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "CanonicalMeasurementEvent",
    "ElectricalEnrichmentConfig",
    "EventQualityStatus",
    "MatchStatus",
    "MeasurementEventCandidate",
    "MeasurementEventConfig",
    "MeasurementEventManifest",
    "MeasurementEventReport",
    "QualityConfig",
    "ReportStatus",
    "ScientificGuardConfig",
]

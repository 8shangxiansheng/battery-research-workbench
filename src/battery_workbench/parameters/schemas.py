"""Typed models for BRW-015 Experiment Parameter Registry.

Design principle (user-mandated): the user configures ONLY parameters that
directly change scientific results and cannot be reliably obtained from data.
Everything else is auto-read from artifacts, scientifically derived (only when
the derivation premise is verified), or stays UNKNOWN.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    FILE_REPORTED = "FILE_REPORTED"
    MANIFEST_REPORTED = "MANIFEST_REPORTED"
    EXPERIMENT_LOG = "EXPERIMENT_LOG"
    INSTRUMENT_SETTING = "INSTRUMENT_SETTING"
    CALIBRATION_RECORD = "CALIBRATION_RECORD"
    USER_SUPPLIED = "USER_SUPPLIED"
    DERIVED_FROM_VERIFIED_PARAMETERS = "DERIVED_FROM_VERIFIED_PARAMETERS"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class ScopeType(str, Enum):
    GLOBAL = "GLOBAL"
    BATTERY = "BATTERY"
    EXPERIMENT = "EXPERIMENT"
    DATA_ASSET = "DATA_ASSET"
    CYCLE = "CYCLE"
    STEP = "STEP"


class ResolutionPolicy(str, Enum):
    """How a parameter may acquire a value (user principle, frozen in code)."""

    AUTO_READ_THEN_USER = "AUTO_READ_THEN_USER"  # critical: data first, else user
    AUTO_ONLY = "AUTO_ONLY"  # data-factual; user cannot override
    DERIVED_ONLY = "DERIVED_ONLY"  # only from verified premises
    USER_ONLY = "USER_ONLY"  # no reliable data source; user or UNKNOWN


class ParameterRecord(BaseModel):
    """One source record for one canonical parameter.

    ``parameter_record_id`` is assigned when the record is registered with the
    registry (see resolution); raw constructions may leave it empty.
    """

    parameter_record_id: str = ""
    canonical_name: str
    value: float | str | None = None
    unit: str | None = None
    source_type: SourceType | str
    source_reference: str = ""
    evidence_note: str = ""
    verification_status: VerificationStatus | str = "UNVERIFIED"
    scope_type: ScopeType | str
    scope_key: str = ""
    battery_id: str | None = None
    experiment_id: str | None = None
    asset_id: str | None = None
    cycle_index_raw: float | None = None
    step_index_raw: float | None = None
    effective_from: Any = None
    effective_to: Any = None


class EffectiveParameter(BaseModel):
    """The resolved value plus full selection provenance."""

    canonical_name: str
    value: float | str | None = None
    unit: str | None = None
    status: Literal["RESOLVED", "CONFLICT", "UNKNOWN"] = "UNKNOWN"
    critical: bool = False
    selected_parameter_record_id: str | None = None
    source_type: str | None = None
    verification_status: str = "UNKNOWN"
    resolution_reason: str = ""
    shadowed_records: list[str] = Field(default_factory=list)


class ParameterConfig(BaseModel):
    version: str = "0.1.0"
    resolution_policy_version: str = "0.1.0"
    unit_policy_version: str = "0.1.0"
    delay_policy: Literal["NONE", "SYSTEM_DELAY_TOTAL", "COMPONENT_SUM"] = "SYSTEM_DELAY_TOTAL"

    @classmethod
    def from_yaml(cls, path: str | Path) -> ParameterConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "experiment_parameters" in payload:
            payload = payload["experiment_parameters"]
        return cls.model_validate(payload)


class ParameterSetManifest(BaseModel):
    registry_name: str = "experiment_parameter_registry"
    registry_version: str = "0.1.0"
    parameter_set_id: str
    battery_id: str
    experiment_id: str
    input_paths: dict[str, str] = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)
    resolution_policy_version: str = "0.1.0"
    unit_policy_version: str = "0.1.0"
    record_count: int = 0
    known_count: int = 0
    unknown_count: int = 0
    verified_count: int = 0
    unverified_count: int = 0
    conflict_count: int = 0
    sampling_rate_hz: float | None = None
    sampling_rate_status: str = "UNKNOWN"
    tof_level: int = 0
    output_paths: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ParameterReport(BaseModel):
    parameter_set_id: str
    battery_id: str
    experiment_id: str
    registry_version: str
    status: Literal["READY", "PASS_WITH_WARNINGS", "EMPTY", "FAILED"]
    record_count: int
    known_count: int
    unknown_count: int
    verified_count: int
    unverified_count: int
    conflict_count: int
    sampling_rate_hz: float | None = None
    tof_level: int = 0
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "EffectiveParameter",
    "ParameterConfig",
    "ParameterRecord",
    "ParameterReport",
    "ParameterSetManifest",
    "ResolutionPolicy",
    "ScopeType",
    "SourceType",
    "VerificationStatus",
]

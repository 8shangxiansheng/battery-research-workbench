"""BRW-017 V2 Feature Registry schemas."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FeatureGroup(str, Enum):
    AMPLITUDE = "AMPLITUDE"
    SAMPLE_TEMPORAL = "SAMPLE_TEMPORAL"
    TOF = "TOF"
    PHYSICAL = "PHYSICAL"
    MORPHOLOGY = "MORPHOLOGY"
    FREQUENCY = "FREQUENCY"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE_MISSING_PARAMETER = "UNAVAILABLE_MISSING_PARAMETER"
    UNAVAILABLE_CAPABILITY_BLOCKED = "UNAVAILABLE_CAPABILITY_BLOCKED"
    UNAVAILABLE_ALGORITHM_NOT_VALIDATED = "UNAVAILABLE_ALGORITHM_NOT_VALIDATED"


class FeatureRegistryEntry(BaseModel):
    feature_name: str
    feature_group: FeatureGroup
    description: str = ""
    unit: str = ""
    dtype: str = "float64"
    definition_version: str = "0.2.0"
    source_engine: str = "BRW-013"
    source_columns: list[str] = Field(default_factory=list)
    requires_parameters: list[str] = Field(default_factory=list)
    requires_capabilities: list[str] = Field(default_factory=list)
    availability_status: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    availability_reason: str = ""
    scientific_role: str = "predictor"
    default_predictor_eligible: bool = True
    is_core: bool = False

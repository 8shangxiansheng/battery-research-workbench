"""Typed models for BRW-016 Leakage-Safe Feature–Label Dataset Builder.

A dataset is a deterministic, role-annotated join of BRW-013 features and
BRW-014 labels for ONE target (SOC or SOH_CAPACITY). No preprocessing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ColumnRole(str, Enum):
    IDENTITY = "IDENTITY"
    PREDICTOR = "PREDICTOR"
    TARGET = "TARGET"
    CONTEXT = "CONTEXT"
    GROUP = "GROUP"
    QUALITY = "QUALITY"
    PROVENANCE = "PROVENANCE"
    FORBIDDEN_PREDICTOR = "FORBIDDEN_PREDICTOR"


DatasetStatus = Literal[
    "READY_FOR_SPLIT",
    "READY_WITH_LIMITATIONS",
    "NOT_READY_FOR_MODEL_EVALUATION",
    "EMPTY",
    "FAILED",
]


class DatasetConfig(BaseModel):
    version: str = "0.1.0"
    role_schema_version: str = "0.1.0"
    leakage_policy_version: str = "0.1.0"
    predictor_policy: str = "ULTRASOUND_ONLY"
    parameter_dependency: str = "INFORMATIONAL"
    min_soh_independent_states: int = 20

    @classmethod
    def from_yaml(cls, path: str | Path) -> DatasetConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "dataset_builder" in payload:
            payload = payload["dataset_builder"]
        return cls.model_validate(payload)


class DatasetReport(BaseModel):
    dataset_id: str
    dataset_family: str
    target_name: str
    dataset_status: DatasetStatus
    battery_id: str
    experiment_id: str

    analysis_slice_id: str = ""
    feature_set_id: str = ""
    label_set_id: str = ""
    parameter_set_id: str = ""
    parameter_dependency: str = "INFORMATIONAL"

    input_feature_rows: int = 0
    input_label_rows: int = 0
    joined_rows: int = 0
    eligible_rows: int = 0
    excluded_rows: int = 0
    exclusion_breakdown: dict[str, int] = Field(default_factory=dict)

    predictor_columns: list[str] = Field(default_factory=list)
    forbidden_predictor_columns: list[str] = Field(default_factory=list)
    # BRW-017 V2: explicit feature selection provenance (None = legacy all-features).
    selected_features: list[str] | None = None
    target_column: str = ""
    context_columns: list[str] = Field(default_factory=list)
    group_columns: list[str] = Field(default_factory=list)
    quality_columns: list[str] = Field(default_factory=list)
    identity_columns: list[str] = Field(default_factory=list)

    battery_group_count: int = 0
    experiment_group_count: int = 0
    cycle_group_count: int = 0
    distinct_soh_values: int = 0
    target_range: list[float] = Field(default_factory=list)

    soc_label_temporality: str | None = None
    soc_formula_version: str | None = None
    frame_random_split_prohibited: bool = True
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    dataset_builder_name: str = "leakage_safe_dataset_builder"
    dataset_builder_version: str = "0.1.0"
    dataset_id: str
    dataset_family: str
    target_name: str
    dataset_status: DatasetStatus
    battery_id: str
    experiment_id: str

    analysis_slice_id: str = ""
    feature_set_id: str = ""
    feature_set_path: str = ""
    feature_set_checksum: str = ""
    label_set_id: str = ""
    label_set_path: str = ""
    label_set_checksum: str = ""
    parameter_set_id: str = ""
    parameter_dependency: str = "INFORMATIONAL"

    predictor_policy: str = "ULTRASOUND_ONLY"
    predictor_columns: list[str] = Field(default_factory=list)
    forbidden_predictor_columns: list[str] = Field(default_factory=list)
    # BRW-017 V2: explicit feature selection provenance (None = legacy all-features).
    selected_features: list[str] | None = None
    context_columns: list[str] = Field(default_factory=list)
    group_columns: list[str] = Field(default_factory=list)
    quality_columns: list[str] = Field(default_factory=list)
    identity_columns: list[str] = Field(default_factory=list)
    target_column: str = ""

    input_feature_rows: int = 0
    input_label_rows: int = 0
    joined_rows: int = 0
    eligible_rows: int = 0
    excluded_rows: int = 0
    exclusion_breakdown: dict[str, int] = Field(default_factory=dict)

    battery_group_count: int = 0
    experiment_group_count: int = 0
    cycle_group_count: int = 0
    distinct_target_values: int = 0
    independent_soh_state_count: int | None = None

    target_method_version: str = ""
    soc_label_temporality: str | None = None
    frame_random_split_prohibited: bool = True

    output_path: str = ""
    output_checksum: str = ""
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DatasetSchemaEntry(BaseModel):
    name: str
    dtype: str
    role: str
    unit: str = ""
    source_layer: str = ""
    source_field: str = ""
    predictor_enabled: bool = False
    leakage_note: str = ""

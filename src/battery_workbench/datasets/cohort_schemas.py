"""Typed source and harmonization contract for immutable cohort datasets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CohortSourceDataset(BaseModel):
    """Manifest identity for a source dataset; filesystem paths are server-owned."""

    model_config = ConfigDict(extra="forbid")

    source_dataset_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:@-]+$")
    battery_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)


class CohortTargetMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_target_id: str = Field(min_length=1)
    source_target_ids: dict[str, str] = Field(min_length=2)
    unit: str = Field(min_length=1)
    method_version: str = Field(min_length=1)


class CohortFeatureMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_feature_id: str = Field(min_length=1)
    source_feature_ids: dict[str, str] = Field(min_length=2)
    method_version: str = Field(min_length=1)


class CohortUnitMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_units: dict[str, str] = Field(min_length=2)
    canonical_unit: str = Field(min_length=1)


class CohortDatasetRequest(BaseModel):
    contract_version: Literal["cohort-dataset/1.0"] = "cohort-dataset/1.0"
    cohort_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:@-]+$")
    source_datasets: list[CohortSourceDataset] = Field(min_length=2)
    target_mapping: CohortTargetMapping
    feature_mappings: list[CohortFeatureMapping] = Field(min_length=1)
    unit_mapping: dict[str, CohortUnitMapping]
    harmonization_method_version: str = Field(min_length=1)
    harmonization_policy_id: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    group_column: Literal["battery_id"] = "battery_id"
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_identity_and_mappings(self) -> CohortDatasetRequest:
        if ".." in self.cohort_id:
            raise ValueError("cohort_id must not contain path traversal segments")
        if (
            self.target_mapping.canonical_target_id != "reference_soc_percent"
            or self.target_mapping.unit != "percent"
        ):
            raise ValueError("V1 cohorts support only reference SOC percent as the target")
        battery_ids = [source.battery_id for source in self.source_datasets]
        dataset_ids = [source.source_dataset_id for source in self.source_datasets]
        if len(set(battery_ids)) != len(battery_ids):
            raise ValueError("each cohort source must represent a distinct battery")
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ValueError("source_dataset_id values must be unique")

        source_id_set = set(dataset_ids)
        if not all(value.strip() for value in self.evidence_refs):
            raise ValueError("evidence_refs must contain non-empty references")
        if set(self.target_mapping.source_target_ids) != source_id_set:
            raise ValueError("target mapping must cover every source dataset exactly once")
        if not all(value.strip() for value in self.target_mapping.source_target_ids.values()):
            raise ValueError("source target identifiers must not be empty")

        feature_ids = [mapping.canonical_feature_id for mapping in self.feature_mappings]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("canonical feature ids must be unique")
        if set(self.unit_mapping) != set(feature_ids):
            raise ValueError("unit mapping must cover every canonical feature exactly once")
        for mapping in self.feature_mappings:
            if set(mapping.source_feature_ids) != source_id_set:
                raise ValueError(
                    "each feature mapping must cover every source dataset exactly once"
                )
            if set(self.unit_mapping[mapping.canonical_feature_id].source_units) != source_id_set:
                raise ValueError("each unit mapping must cover every source dataset exactly once")
            if not all(value.strip() for value in mapping.source_feature_ids.values()):
                raise ValueError("source feature identifiers must not be empty")
            units = self.unit_mapping[mapping.canonical_feature_id]
            if not all(value.strip() for value in units.source_units.values()):
                raise ValueError("source units must not be empty")
        return self

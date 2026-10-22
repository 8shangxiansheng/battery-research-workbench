"""Typed contracts and readiness descriptors for evidence-gated capabilities."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from battery_workbench.datasets.cohort_schemas import CohortDatasetRequest


class TimebaseAnchor(BaseModel):
    asset_id: str = Field(min_length=1)
    absolute_start_time: datetime
    source_reference: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("asset_id", "source_reference")
    @classmethod
    def _non_blank_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def _aware_datetime(self) -> TimebaseAnchor:
        if self.absolute_start_time.tzinfo is None or self.absolute_start_time.utcoffset() is None:
            raise ValueError("absolute_start_time must include an explicit UTC offset")
        return self


class TimebaseValidationRequest(BaseModel):
    contract_version: Literal["timebase-validation/1.1"] = "timebase-validation/1.1"
    battery_id: str
    experiment_id: str
    timezone: str = Field(min_length=1)
    anchors: list[TimebaseAnchor] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    maximum_allowed_error_s: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    model_config = ConfigDict(extra="forbid")

    @field_validator("evidence_refs")
    @classmethod
    def _non_blank_evidence_refs(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("evidence_refs must not contain blank values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evidence_refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def _valid_timezone_and_unique_assets(self) -> TimebaseValidationRequest:
        try:
            timezone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        if any(
            anchor.absolute_start_time.astimezone(timezone).utcoffset()
            != anchor.absolute_start_time.utcoffset()
            for anchor in self.anchors
        ):
            raise ValueError("anchor UTC offsets must agree with the declared timezone")
        asset_ids = [anchor.asset_id for anchor in self.anchors]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("anchors must contain each asset_id exactly once")
        missing_anchor_evidence = sorted(
            {anchor.source_reference for anchor in self.anchors} - set(self.evidence_refs)
        )
        if missing_anchor_evidence:
            raise ValueError("evidence_refs must include every anchor source_reference")
        return self


class TimebaseEvidencePreflightRequest(BaseModel):
    contract_version: Literal["timebase-evidence-preflight/1.0"] = "timebase-evidence-preflight/1.0"
    battery_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    model_config = ConfigDict(extra="forbid")

    @field_validator("battery_id", "experiment_id")
    @classmethod
    def _non_blank_evidence_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("battery_id and experiment_id must not be blank")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence_preflight_refs(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("evidence_refs must not contain blank values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evidence_refs must be unique")
        return cleaned


class TimebaseVerifiedEvidenceFile(BaseModel):
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    size_bytes: int = Field(ge=0)
    model_config = ConfigDict(extra="forbid")


class TimebaseEvidencePreflightData(BaseModel):
    status: Literal["SOURCE_FILES_VERIFIED"]
    source_integrity: Literal["VERIFIED"]
    verified_evidence: dict[str, TimebaseVerifiedEvidenceFile]
    model_config = ConfigDict(extra="forbid")


class TimebaseEvidencePreflightEnvelope(BaseModel):
    data: TimebaseEvidencePreflightData
    meta: dict[str, Any]
    model_config = ConfigDict(extra="forbid")


class TimebaseReviewRequest(BaseModel):
    decision: Literal["ACCEPT", "REJECT", "REVOKE"]
    operator_identity: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list)
    error_by_asset_s: dict[str, float] = Field(default_factory=dict)
    ambiguity_free_assets: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

    @field_validator("operator_identity", "rationale")
    @classmethod
    def _non_blank_review_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _non_blank_review_evidence(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("evidence_refs must not contain blank values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("review evidence_refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def _acceptance_has_review_evidence(self) -> TimebaseReviewRequest:
        if any(not math.isfinite(value) for value in self.error_by_asset_s.values()):
            raise ValueError("all reported timebase errors must be finite")
        if self.decision == "ACCEPT":
            if not self.evidence_refs:
                raise ValueError("ACCEPT requires review evidence_refs")
            if not self.error_by_asset_s:
                raise ValueError("ACCEPT requires measured error for every asset")
            if len(self.ambiguity_free_assets) != len(set(self.ambiguity_free_assets)):
                raise ValueError("ambiguity_free_assets must be unique")
        return self


class CohortLOBORequest(BaseModel):
    contract_version: Literal["cohort-lobo-evaluation/1.0"] = "cohort-lobo-evaluation/1.0"
    strategies: list[str] = Field(
        default_factory=lambda: ["DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE"], min_length=1
    )
    random_state: int = 42
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _known_fixed_baselines(self) -> CohortLOBORequest:
        from battery_workbench.modeling.schemas import STRATEGIES

        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError("strategies must be unique")
        unknown = sorted(set(self.strategies) - set(STRATEGIES))
        if unknown:
            raise ValueError(f"unknown fixed baseline strategies: {unknown}")
        return self


class TargetSourceEvidence(BaseModel):
    asset_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    model_config = ConfigDict(extra="forbid")

    @field_validator("asset_id", "source_reference")
    @classmethod
    def _non_blank_target_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target source identity and reference must not be blank")
        return value


class TargetUncertainty(BaseModel):
    status: Literal["QUANTIFIED", "UNKNOWN"]
    standard_uncertainty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str | None = None
    method: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("unit", "method", "reason")
    @classmethod
    def _non_blank_optional_uncertainty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("uncertainty text fields must not be blank")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _unique_uncertainty_evidence(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("uncertainty evidence_refs must not contain blank values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("uncertainty evidence_refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def _uncertainty_is_explicit(self) -> TargetUncertainty:
        if self.status == "UNKNOWN":
            if self.standard_uncertainty is not None:
                raise ValueError("UNKNOWN uncertainty must not include a numeric estimate")
            if self.unit is not None or self.method is not None or self.evidence_refs:
                raise ValueError("UNKNOWN uncertainty must not include quantified evidence fields")
            if not self.reason or not self.reason.strip():
                raise ValueError("UNKNOWN uncertainty requires a reason")
        elif (
            self.standard_uncertainty is None
            or not self.unit
            or not self.unit.strip()
            or not self.method
            or not self.method.strip()
            or not self.evidence_refs
            or any(not ref.strip() for ref in self.evidence_refs)
        ):
            raise ValueError(
                "QUANTIFIED uncertainty requires a value, unit, method and evidence_refs"
            )
        return self


class TargetLabelProvenance(BaseModel):
    semantic_type: Literal["DIRECT_MEASUREMENT", "DERIVED_REFERENCE_LABEL", "DERIVED_HEALTH_STATE"]
    method_id: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    independent_unit: Literal["BATTERY"]
    source_references: list[TargetSourceEvidence] = Field(min_length=1)
    uncertainty: TargetUncertainty
    model_config = ConfigDict(extra="forbid")

    @field_validator("method_id", "method_version", "definition", "unit")
    @classmethod
    def _non_blank_target_definition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target method, version, definition and unit must not be blank")
        return value

    @model_validator(mode="after")
    def _unique_source_assets(self) -> TargetLabelProvenance:
        source_identities = [
            (source.asset_id, source.source_reference) for source in self.source_references
        ]
        if len(source_identities) != len(set(source_identities)):
            raise ValueError(
                "target source_references must use unique DataAsset ID and source path pairs"
            )
        return self


class TargetFeatureLocator(BaseModel):
    feature_name: str = Field(min_length=1)
    gate_id: str | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("feature_name")
    @classmethod
    def _valid_feature_name(cls, value: str) -> str:
        value = value.strip()
        if not value or "@" in value:
            raise ValueError("feature_name must be non-blank and must not contain '@'")
        return value

    @field_validator("gate_id")
    @classmethod
    def _valid_gate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or "@" in value:
            raise ValueError("gate_id must be non-blank and must not contain '@'")
        return value

    @property
    def locator(self) -> str:
        return f"{self.feature_name}@{self.gate_id}" if self.gate_id else self.feature_name


class TargetDatasetRequest(BaseModel):
    contract_version: Literal["target-dataset/1.0"] = "target-dataset/1.0"
    battery_ids: list[str] = Field(min_length=1)
    experiment_ids: list[str] = Field(min_length=1)
    target_id: Literal["reference_soc_percent", "temperature_c", "soh_capacity_reference_percent"]
    target_grain: Literal["MEASUREMENT_EVENT", "CYCLE", "EXPERIMENT", "BATTERY"]
    minimum_independent_states: int | None = Field(
        default=None,
        ge=3,
        description=(
            "SOH-only cycle-state readiness threshold; repeated event rows do not count as states."
        ),
    )
    feature_locators: list[TargetFeatureLocator] = Field(min_length=1)
    label_provenance: TargetLabelProvenance
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _target_semantics_match_grain(self) -> TargetDatasetRequest:
        if self.target_id == "soh_capacity_reference_percent":
            if self.minimum_independent_states is None:
                raise ValueError("SOH target requires minimum_independent_states")
        elif self.minimum_independent_states is not None:
            raise ValueError("minimum_independent_states only applies to SOH targets")
        if len(self.battery_ids) != len(self.experiment_ids):
            raise ValueError(
                "battery_ids and experiment_ids must have one-to-one positional pairing"
            )
        if any(not item.strip() for item in self.battery_ids + self.experiment_ids):
            raise ValueError("battery_ids and experiment_ids must not contain blanks")
        experiment_keys = list(zip(self.battery_ids, self.experiment_ids, strict=True))
        if len(experiment_keys) != len(set(experiment_keys)):
            raise ValueError("battery_id/experiment_id pairs must be unique")
        locators = [item.locator for item in self.feature_locators]
        if len(locators) != len(set(locators)):
            raise ValueError("feature locator identities must be unique")
        required = {
            "reference_soc_percent": (
                "MEASUREMENT_EVENT",
                "DERIVED_REFERENCE_LABEL",
                "percent",
            ),
            "temperature_c": ("MEASUREMENT_EVENT", "DIRECT_MEASUREMENT", "celsius"),
            "soh_capacity_reference_percent": (
                "CYCLE",
                "DERIVED_HEALTH_STATE",
                "percent",
            ),
        }[self.target_id]
        observed = (
            self.target_grain,
            self.label_provenance.semantic_type,
            self.label_provenance.unit,
        )
        if observed != required:
            raise ValueError(
                "target_grain, label semantic_type and unit must match target_id "
                f"(expected {required}, got {observed})"
            )
        return self


class TargetSourceVerificationResult(BaseModel):
    asset_id: str = Field(min_length=1)
    verified: Literal[True]
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    parser_provenance: Literal[
        "VERIFIED",
        "NOT_AVAILABLE",
        "NOT_RECORDED",
        "CHECKSUM_VERIFIED_PATH_NOT_RECORDED",
    ]
    model_config = ConfigDict(extra="forbid")


class TargetSourceEvidenceValidationData(BaseModel):
    status: Literal["SOURCE_EVIDENCE_VERIFIED"]
    target_id: Literal["reference_soc_percent", "temperature_c", "soh_capacity_reference_percent"]
    verified_sources: list[TargetSourceVerificationResult] = Field(min_length=1)
    source_integrity: Literal["VERIFIED"]
    label_source_semantics: Literal["NOT_ASSESSED"]
    target_readiness: Literal["NOT_ASSESSED"]
    feature_availability: Literal["NOT_ASSESSED"]
    materialization_enabled: Literal[False]
    model_config = ConfigDict(extra="forbid")


class TargetSourceEvidenceValidationEnvelope(BaseModel):
    data: TargetSourceEvidenceValidationData
    meta: dict[str, Any]
    model_config = ConfigDict(extra="forbid")


class TargetDatasetData(BaseModel):
    """Immutable target-dataset identity after source-evidence verification.

    ``target_readiness`` and ``scientific_validity`` are deliberately
    ``NOT_ASSESSED``: materializing this artifact proves source integrity only,
    never that the target is scientifically usable.
    """

    target_dataset_id: str = Field(pattern=r"^TDS::[a-fA-F0-9]{24}$")
    target_id: Literal[
        "reference_soc_percent", "temperature_c", "soh_capacity_reference_percent"
    ]
    target_grain: Literal["MEASUREMENT_EVENT", "CYCLE", "EXPERIMENT", "BATTERY"]
    independent_unit: Literal["BATTERY"]
    source_integrity: Literal["VERIFIED"]
    target_readiness: Literal["NOT_ASSESSED"]
    scientific_validity: Literal["NOT_ASSESSED"]
    reuse_status: Literal["CREATED", "REUSED"]
    manifest_path: str
    verified_sources: list[TargetSourceVerificationResult]


class TargetDatasetEnvelope(BaseModel):
    data: TargetDatasetData
    meta: dict[str, Any]
    model_config = ConfigDict(extra="forbid")


class TuningStudyRequest(BaseModel):
    contract_version: Literal["tuning-study/1.0"] = "tuning-study/1.0"
    dataset_id: str
    outer_split_id: str
    strategy: str
    search_space: dict[str, list[Any]] = Field(min_length=1)
    inner_group_column: Literal["battery_id", "experiment_id", "cycle_group_id"]
    validation_role: Literal["VALIDATION"]
    held_out_role: Literal["HELD_OUT"] = "HELD_OUT"
    selection_scope: Literal["TRAIN_ONLY_ML_SAFE"] = "TRAIN_ONLY_ML_SAFE"
    objective_metric: str = "macro_mae_percent"
    max_trials: int = Field(default=50, ge=1, le=500)
    random_state: int = 42


class BoundaryReadiness(BaseModel):
    code: str
    status: Literal[
        "READY", "PARTIALLY_READY", "BLOCKED_BY_DATA", "BLOCKED_BY_VALIDATION", "NOT_IMPLEMENTED"
    ]
    can_resolve_with_current_data: bool
    reason: str
    requirements: list[str]
    future_contract: str


class FutureContractDescriptor(BaseModel):
    contract_version: str
    enabled: bool = False
    planned_endpoint: str
    activation_gate: list[str]
    request_schema: dict[str, Any]


class ExtensionReadiness(BaseModel):
    battery_id: str
    experiment_id: str
    observed: dict[str, Any]
    boundaries: list[BoundaryReadiness]
    future_contracts: dict[str, FutureContractDescriptor]


class ExtensionReadinessEnvelope(BaseModel):
    data: ExtensionReadiness
    meta: dict[str, Any]


def _descriptor(
    model: type[BaseModel], endpoint: str, gates: list[str], *, enabled: bool = False
) -> FutureContractDescriptor:
    schema = model.model_json_schema()
    return FutureContractDescriptor(
        contract_version=str(schema["properties"]["contract_version"]["default"]),
        enabled=enabled,
        planned_endpoint=endpoint,
        activation_gate=gates,
        request_schema=schema,
    )


def build_extension_readiness(
    *,
    battery_id: str,
    experiment_id: str,
    battery_count: int,
    timebase_status: str,
    independent_soh_states: int,
    temperature_valid_count: int,
    temperature_range_c: float | None,
    temperature_evidence_verified: bool = False,
    model_beats_dummy: bool | None,
    has_independent_validation: bool,
    eligible_cohort_battery_count: int = 0,
    eligible_cohort_id: str | None = None,
) -> ExtensionReadiness:
    timebase_ready = timebase_status == "VALIDATED"
    soh_data_ready = independent_soh_states >= 3
    temperature_data_ready = temperature_valid_count > 0 and (temperature_range_c or 0.0) >= 2.0
    temperature_ready = temperature_data_ready and temperature_evidence_verified
    cross_battery_ready = eligible_cohort_battery_count >= 2 and bool(eligible_cohort_id)
    boundaries = [
        BoundaryReadiness(
            code="TIMEBASE_VALIDATION",
            status="READY" if timebase_ready else "BLOCKED_BY_VALIDATION",
            can_resolve_with_current_data=timebase_ready,
            reason=f"timebase status is {timebase_status}",
            requirements=[
                "per-asset absolute anchors",
                "timezone",
                "raw-root-relative evidence files with server-verified checksums",
                "error tolerance audit",
                "scientific evidence sufficiency and reviewer identity remain separately assessed",
            ],
            future_contract="timebase-validation/1.1",
        ),
        BoundaryReadiness(
            code="SOH_MODELING",
            status=(
                "PARTIALLY_READY" if soh_data_ready else "BLOCKED_BY_DATA"
            ),
            can_resolve_with_current_data=soh_data_ready,
            reason=(
                (
                    f"{independent_soh_states} independent SOH states meet the minimum; "
                    "SOH modeling is implemented and gated by this count, but the "
                    "threshold is a minimum, not sufficient cross-state evidence"
                )
                if soh_data_ready
                else (
                    f"{independent_soh_states} independent SOH states; event rows are "
                    "not independent states"
                )
            ),
            requirements=[
                "at least 3 independent SOH states",
                "cycle-level target grain",
                "reference-capacity provenance",
                "SOH-specific model implementation and evaluation protocol",
            ],
            future_contract="target-dataset/1.0",
        ),
        BoundaryReadiness(
            code="TEMPERATURE_MODELING",
            status=(
                "READY"
                if temperature_ready
                else ("BLOCKED_BY_VALIDATION" if temperature_data_ready else "BLOCKED_BY_DATA")
            ),
            can_resolve_with_current_data=temperature_ready,
            reason=(
                "temperature target available"
                if temperature_ready
                else (
                    "sensor location/calibration evidence is not verified"
                    if temperature_data_ready
                    else "temperature channel absent or variation < 2 °C"
                )
            ),
            requirements=[
                "measured temperature channel",
                "coverage audit",
                "at least 2 °C observed variation",
                "verified sensor location and calibration evidence",
            ],
            future_contract="target-dataset/1.0",
        ),
        BoundaryReadiness(
            code="CROSS_BATTERY_GENERALIZATION",
            status="PARTIALLY_READY" if cross_battery_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=cross_battery_ready,
            reason=(
                f"eligible harmonized cohort {eligible_cohort_id} contains "
                f"{eligible_cohort_battery_count} batteries"
                if cross_battery_ready
                else f"{eligible_cohort_battery_count} eligible cohort batteries; "
                "a validated harmonized cohort with at least 2 batteries is required "
                f"({battery_count} registered batteries are not sufficient evidence)"
            ),
            requirements=[
                "2+ independent batteries",
                "harmonized feature/target definitions",
                "BATTERY grouped outer split",
            ],
            future_contract="cohort-dataset/1.0",
        ),
        BoundaryReadiness(
            code="HYPERPARAMETER_TUNING",
            status="NOT_IMPLEMENTED",
            can_resolve_with_current_data=False,
            reason=(
                "no tuning route; fixed baselines only"
                if not has_independent_validation
                else "activation review required"
            ),
            requirements=[
                "independent VALIDATION role",
                "untouched HELD_OUT role",
                "nested grouped selection",
                "bounded search space",
            ],
            future_contract="tuning-study/1.0",
        ),
        BoundaryReadiness(
            code="MODEL_ADVANTAGE_OVER_DUMMY",
            status="READY" if model_beats_dummy else "PARTIALLY_READY",
            can_resolve_with_current_data=model_beats_dummy is not None,
            reason=(
                "a peer model beat Dummy"
                if model_beats_dummy is True
                else "no evaluated peer beat Dummy; this is a result, not a software fault"
                if model_beats_dummy is False
                else "no comparable Dummy and peer result is available"
            ),
            requirements=[
                "improve evidence/features or collect more independent data",
                "retain Dummy-first comparison",
            ],
            future_contract="tuning-study/1.0",
        ),
    ]
    contracts = {
        "timebase_validation": _descriptor(
            TimebaseValidationRequest,
            "/api/v1/experiments/{battery_id}/{experiment_id}/timebase-validations",
            [
                "manifest-registered DataAsset IDs",
                "server-verified raw-root-relative evidence file checksums and explicit timezone",
                "per-asset error evidence and ambiguity review",
                "authenticated review identity before scientific promotion",
            ],
            enabled=True,
        ),
        "cohort_dataset": _descriptor(
            CohortDatasetRequest,
            "/api/v1/cohort-datasets",
            ["2+ eligible source datasets", "manifest-backed harmonization policy"],
            enabled=True,
        ),
        "target_dataset": _descriptor(
            TargetDatasetRequest,
            "/api/v1/target-datasets",
            [
                "target-specific grain, semantic type and unit must agree",
                "manifest-backed source DataAsset IDs and checksums",
                "method/formula version and explicit uncertainty status",
                "Battery remains the independent outer grouping unit",
                "sensor/calibration and reference-label evidence gates",
                "SOH threshold counts independent cycle states only",
            ],
        ),
        "tuning_study": _descriptor(
            TuningStudyRequest,
            "/api/v1/tuning-studies",
            ["independent validation", "nested grouped protocol"],
        ),
    }
    return ExtensionReadiness(
        battery_id=battery_id,
        experiment_id=experiment_id,
        observed={
            "battery_count": battery_count,
            "eligible_cohort_battery_count": eligible_cohort_battery_count,
            "eligible_cohort_id": eligible_cohort_id,
            "timebase_status": timebase_status,
            "independent_soh_states": independent_soh_states,
            "temperature_valid_count": temperature_valid_count,
            "temperature_range_c": temperature_range_c,
            "model_beats_dummy": model_beats_dummy,
            "has_independent_validation": has_independent_validation,
        },
        boundaries=boundaries,
        future_contracts=contracts,
    )

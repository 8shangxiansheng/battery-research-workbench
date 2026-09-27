"""Typed contracts and readiness descriptors for evidence-gated capabilities."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from battery_workbench.datasets.cohort_schemas import CohortDatasetRequest


class TimebaseAnchor(BaseModel):
    asset_id: str = Field(min_length=1)
    absolute_start_time: datetime
    source_reference: str | None = None


class TimebaseValidationRequest(BaseModel):
    contract_version: Literal["timebase-validation/1.0"] = "timebase-validation/1.0"
    battery_id: str
    experiment_id: str
    timezone: str = Field(min_length=1)
    anchors: list[TimebaseAnchor] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    maximum_allowed_error_s: float = Field(default=1.0, gt=0)


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


class TargetDatasetRequest(BaseModel):
    contract_version: Literal["target-dataset/1.0"] = "target-dataset/1.0"
    battery_ids: list[str] = Field(min_length=1)
    experiment_ids: list[str] = Field(min_length=1)
    target_id: Literal["reference_soc_percent", "temperature_c", "soh_capacity_reference_percent"]
    target_grain: Literal["MEASUREMENT_EVENT", "CYCLE", "EXPERIMENT", "BATTERY"]
    minimum_independent_states: int = Field(default=3, ge=3)
    feature_locators: list[dict[str, Any]] = Field(min_length=1)


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
    model_beats_dummy: bool | None,
    has_independent_validation: bool,
    eligible_cohort_battery_count: int = 0,
    eligible_cohort_id: str | None = None,
) -> ExtensionReadiness:
    timebase_ready = timebase_status == "VALIDATED"
    soh_ready = independent_soh_states >= 3
    temperature_ready = temperature_valid_count > 0 and (temperature_range_c or 0.0) >= 2.0
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
                "source evidence",
                "error tolerance audit",
            ],
            future_contract="timebase-validation/1.0",
        ),
        BoundaryReadiness(
            code="SOH_MODELING",
            status="READY" if soh_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=soh_ready,
            reason=f"{independent_soh_states} independent SOH states; event rows are not independent states",
            requirements=[
                "at least 3 independent SOH states",
                "cycle-level target grain",
                "reference-capacity provenance",
            ],
            future_contract="target-dataset/1.0",
        ),
        BoundaryReadiness(
            code="TEMPERATURE_MODELING",
            status="READY" if temperature_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=temperature_ready,
            reason=(
                "temperature target available"
                if temperature_ready
                else "temperature channel absent or variation < 2 °C"
            ),
            requirements=[
                "measured temperature channel",
                "coverage audit",
                "at least 2 °C observed variation",
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
            "/api/v1/timebase-validations",
            ["evidence-backed asset anchors"],
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
            ["target readiness", "independent-state threshold"],
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

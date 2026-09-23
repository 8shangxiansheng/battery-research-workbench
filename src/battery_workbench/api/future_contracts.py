"""Dormant, typed contracts for scientific capabilities blocked by current evidence.

These models intentionally do not have write routes.  The readiness endpoint
publishes their JSON schemas so future implementations can be additive without
pretending that the current single-cell experiment satisfies their gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class CohortDatasetRequest(BaseModel):
    contract_version: Literal["cohort-dataset/1.0"] = "cohort-dataset/1.0"
    cohort_id: str = Field(min_length=1)
    battery_ids: list[str] = Field(min_length=2)
    target_id: str = Field(min_length=1)
    feature_locators: list[dict[str, Any]] = Field(default_factory=list)
    group_column: Literal["battery_id"] = "battery_id"
    harmonization_policy_id: str | None = None

    @model_validator(mode="after")
    def _unique_batteries(self) -> CohortDatasetRequest:
        if len(set(self.battery_ids)) != len(self.battery_ids):
            raise ValueError("battery_ids must be unique")
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


def _descriptor(model: type[BaseModel], endpoint: str, gates: list[str]) -> FutureContractDescriptor:
    schema = model.model_json_schema()
    return FutureContractDescriptor(
        contract_version=str(schema["properties"]["contract_version"]["default"]),
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
) -> ExtensionReadiness:
    timebase_ready = timebase_status == "VALIDATED"
    soh_ready = independent_soh_states >= 3
    temperature_ready = temperature_valid_count > 0 and (temperature_range_c or 0.0) >= 2.0
    cross_battery_ready = battery_count >= 2
    boundaries = [
        BoundaryReadiness(
            code="TIMEBASE_VALIDATION",
            status="READY" if timebase_ready else "BLOCKED_BY_VALIDATION",
            can_resolve_with_current_data=timebase_ready,
            reason=f"timebase status is {timebase_status}",
            requirements=["per-asset absolute anchors", "timezone", "source evidence", "error tolerance audit"],
            future_contract="timebase-validation/1.0",
        ),
        BoundaryReadiness(
            code="SOH_MODELING",
            status="READY" if soh_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=soh_ready,
            reason=f"{independent_soh_states} independent SOH states; event rows are not independent states",
            requirements=["at least 3 independent SOH states", "cycle-level target grain", "reference-capacity provenance"],
            future_contract="target-dataset/1.0",
        ),
        BoundaryReadiness(
            code="TEMPERATURE_MODELING",
            status="READY" if temperature_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=temperature_ready,
            reason=("temperature target available" if temperature_ready else "temperature channel absent or variation < 2 °C"),
            requirements=["measured temperature channel", "coverage audit", "at least 2 °C observed variation"],
            future_contract="target-dataset/1.0",
        ),
        BoundaryReadiness(
            code="CROSS_BATTERY_GENERALIZATION",
            status="PARTIALLY_READY" if cross_battery_ready else "BLOCKED_BY_DATA",
            can_resolve_with_current_data=cross_battery_ready,
            reason=f"{battery_count} registered battery/batteries; at least 2 required",
            requirements=["2+ independent batteries", "harmonized feature/target definitions", "BATTERY grouped outer split"],
            future_contract="cohort-dataset/1.0",
        ),
        BoundaryReadiness(
            code="HYPERPARAMETER_TUNING",
            status="NOT_IMPLEMENTED",
            can_resolve_with_current_data=False,
            reason=("no tuning route; fixed baselines only" if not has_independent_validation else "activation review required"),
            requirements=["independent VALIDATION role", "untouched HELD_OUT role", "nested grouped selection", "bounded search space"],
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
            requirements=["improve evidence/features or collect more independent data", "retain Dummy-first comparison"],
            future_contract="tuning-study/1.0",
        ),
    ]
    contracts = {
        "timebase_validation": _descriptor(TimebaseValidationRequest, "/api/v1/timebase-validations", ["evidence-backed asset anchors"]),
        "cohort_dataset": _descriptor(CohortDatasetRequest, "/api/v1/cohort-datasets", ["2+ batteries", "harmonization policy"]),
        "target_dataset": _descriptor(TargetDatasetRequest, "/api/v1/target-datasets", ["target readiness", "independent-state threshold"]),
        "tuning_study": _descriptor(TuningStudyRequest, "/api/v1/tuning-studies", ["independent validation", "nested grouped protocol"]),
    }
    return ExtensionReadiness(
        battery_id=battery_id,
        experiment_id=experiment_id,
        observed={
            "battery_count": battery_count,
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

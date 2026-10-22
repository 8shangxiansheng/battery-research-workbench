"""BRW-024 public API DTOs — versioned, internal dataclasses not exposed."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- stable public field names frozen in task pack §23 ----
class SystemStatus(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    version: str
    api_version: str = "v1"


class Capabilities(BaseModel):
    software_capabilities: dict[str, Any] = Field(default_factory=dict)
    experiment_readiness: dict[str, Any] = Field(default_factory=dict)


class ExperimentSummary(BaseModel):
    battery_id: str
    experiment_id: str
    experiment_composite_id: str
    dataset_id: str | None = None
    split_id: str | None = None
    label_set_id: str | None = None
    gate_set_id: str | None = None
    feature_set_id: str | None = None
    scientific_status: str = ""
    limitations: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    latest_canonical_artifacts: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    status: str
    battery_id: str
    experiment_id: str
    created_at: str | None = None
    user_actions_pending: list[dict[str, Any]] = Field(default_factory=list)


class PlanSummary(BaseModel):
    plan_id: str
    profile: str
    battery_id: str
    experiment_id: str
    nodes: list[str] = Field(default_factory=list)


class DryRunResult(BaseModel):
    plan_id: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    reuse_summary: dict[str, Any] = Field(default_factory=dict)


class EventRecord(BaseModel):
    node: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)


class EventsResponse(BaseModel):
    run_id: str
    events: list[EventRecord] = Field(default_factory=list)


class UserActionInfo(BaseModel):
    action_id: str
    action_kind: str
    run_id: str
    node_id: str | None = None
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "PENDING"


class ArtifactDescriptor(BaseModel):
    artifact_id: str
    artifact_type: str
    availability: str = "AVAILABLE"
    status: str = ""
    row_count: int | None = None
    preview: list[dict[str, Any]] = Field(default_factory=list)
    path_hint: str | None = None  # debug/admin metadata only


class FeatureInfo(BaseModel):
    feature_name: str
    role: str | None = None
    availability: str = "AVAILABLE"
    gate_id: str | None = None
    tof_definition_id: str | None = None
    missing_reason: str | None = None


class CorrelationAlignmentAssessment(BaseModel):
    status: Literal["VALIDATED", "PROVISIONAL", "UNKNOWN"]
    validated_sync: bool
    association_scope: Literal["EXPLORATORY_ONLY"]
    confirmatory_inference_allowed: Literal[False]
    limitation: str


class CycleCorrelationComponent(BaseModel):
    coefficient: float | None
    method: str
    n_events: int | None = None
    n_cycle_groups: int


class CycleCorrelationDecomposition(BaseModel):
    policy: str
    status: str
    interpretation: str
    n_input_events: int
    n_events: int
    n_cycle_groups: int
    n_batteries: int
    declared_battery_group_count: int
    physical_battery_count: int | None = None
    battery_identity_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    group_count_semantics: Literal["DECLARED_BATTERY_ID"] = "DECLARED_BATTERY_ID"
    missing_feature_count: int
    missing_state_count: int
    excluded_ineligible_count: int
    within_cycle: CycleCorrelationComponent
    between_cycle: CycleCorrelationComponent
    limitations: list[str] = Field(default_factory=list)


class DeclaredConditionCorrelation(BaseModel):
    feature_code: str
    policy: str
    feature_variant: str
    gate_id: str | None
    condition_axis_id: str
    condition_value: str
    unit: str | None
    declaration_status: Literal["OPERATOR_DECLARED"]
    absolute_timebase_status: Literal["NOT_ASSESSED"]
    synchronization_status: Literal["NOT_ASSESSED"]
    method: Literal["pearson", "spearman"]
    coefficient: float | None
    n_input_events: int
    n_valid_pairs: int
    missing_feature_count: int
    missing_state_count: int
    excluded_ineligible_count: int
    battery_count: int
    group_count_semantics: Literal["DECLARED_BATTERY_ID"] = "DECLARED_BATTERY_ID"
    battery_identity_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    physical_battery_count: int | None = None
    cycle_count: int
    segment_ids: list[str]
    time_reference_asset_ids: list[str]
    analysis_mode: Literal["EXPLORATORY"]
    status: str
    limitations: list[str]


class DeclaredConditionAnalysis(BaseModel):
    status: Literal["AVAILABLE", "NOT_CONFIGURED", "NO_SEGMENTS"]
    declaration_status: Literal["OPERATOR_DECLARED", "NOT_CONFIGURED", "NOT_APPLICABLE"]
    absolute_timebase_status: Literal["NOT_ASSESSED"]
    synchronization_status: Literal["NOT_ASSESSED"]
    segment_count: int
    events_assessed: int
    assignment_status_counts: dict[str, int]
    results: list[DeclaredConditionCorrelation]
    limitations: list[str]


class CorrelationInferenceAssessment(BaseModel):
    analysis_mode: Literal["EXPLORATORY"]
    claim_scope: Literal["ASSOCIATION_ONLY"]
    independent_unit: Literal["BATTERY"]
    group_count_semantics: Literal["DECLARED_BATTERY_ID"]
    group_identity_status: Literal["NOT_ASSESSED"]
    physical_battery_count: int | None = None
    correlation_results_included: bool
    study_protocol_status: str
    analysis_plan: dict[str, Any]
    confidence_interval: dict[str, Any]
    p_value: dict[str, Any]
    multiple_comparison: dict[str, Any]
    confounder_adjustment: dict[str, Any]


class FeatureCorrelationResult(BaseModel):
    battery_id: str | None = None
    state_scope: str | None = Field(
        default=None,
        description=(
            "Electrochemical phase slice: overall, charge, discharge, or rest; "
            "not an experiment condition_id."
        ),
    )
    analysis_id: str
    feature_code: str
    gate_id: str | None
    feature_variant: str
    state_variable: str
    scope: str
    method: str
    coefficient: float | None
    n_input: int
    n_input_unit: str
    n_valid: int
    n_valid_unit: str
    independent_group_count: int | None = None
    independent_unit: str | None = None
    group_identity_status: str = "NOT_ASSESSED"
    distinct_state_count: int | None = None
    missing_feature_count: int
    missing_state_count: int
    missing_count_unit: str
    excluded_ineligible_count: int
    excluded_ineligible_unit: str
    analysis_mode: str
    ml_safe_selection: bool
    # P4 exploratory uncertainty fields. Absent/None means "not estimated for
    # this row"; they are never filled with a plausible-looking substitute.
    ci_low: float | None = None
    ci_high: float | None = None
    interval_method: str | None = None
    p_value_raw: float | None = None
    p_value_adjusted: float | None = None
    multiplicity_correction: str | None = None
    replication_factor: float | None = Field(
        default=None,
        description=(
            "Rows per independent unit (n_valid / independent_group_count). "
            "Greater than 1 means event rows are repeated measures of the same unit."
        ),
    )
    pseudo_replication_status: str | None = None
    limitations: list[str] = Field(default_factory=list)
    status: str


class FeatureCorrelationsData(BaseModel):
    feature_code: str
    n_events: int
    soc: list[FeatureCorrelationResult]
    soc_battery_decomposition: dict[str, Any]
    soc_diagnostic_scatter: dict[str, Any]
    soc_by_battery_condition: list[FeatureCorrelationResult] = Field(
        description=(
            "Backward-compatible property name. Rows are Battery × "
            "overall/charge/discharge/rest slices, not experiment condition slices."
        ),
    )
    soc_by_cycle: list[FeatureCorrelationResult]
    soc_cycle_decomposition: CycleCorrelationDecomposition
    alignment_assessment: CorrelationAlignmentAssessment
    inference_assessment: CorrelationInferenceAssessment
    uncertainty_summary: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Declared-family uncertainty read-out: interval method, family size and "
            "how many intervals were estimable. Exploratory only."
        ),
    )
    temperature: FeatureCorrelationResult
    soh: FeatureCorrelationResult
    soh_cycle_summary: list[dict[str, Any]]
    declared_condition_analysis: DeclaredConditionAnalysis


class CorrelationPolicyVersions(BaseModel):
    feature_state_correlation: str
    feature_state_join: str
    battery_decomposition: str
    cycle_within_between_correlation: str
    condition_stratification: str
    battery_scatter_diagnostic: str


class FeatureCorrelationAnalysisScope(BaseModel):
    diagnostic_point_limit: int = Field(ge=1)
    analyzed_event_rows: int = Field(ge=0)
    diagnostic_points_returned: int = Field(ge=0)
    join_key: Literal["measurement_event_id"]
    coefficient_eligibility: Literal["analysis_eligible=true"]
    analysis_mode: Literal["EXPLORATORY"]


class FeatureCorrelationsMeta(BaseModel):
    policy: str
    policy_versions: CorrelationPolicyVersions
    analysis_scope: FeatureCorrelationAnalysisScope
    gate_calibration_id: str | None = None
    note: str


class FeatureCorrelationsEnvelope(BaseModel):
    data: FeatureCorrelationsData
    meta: FeatureCorrelationsMeta


class LimitationInfo(BaseModel):
    code: str
    severity: str
    description: str


class EvidenceInfo(BaseModel):
    evidence_id: str
    evidence_type: str
    evidence_ref: str
    source_artifact_id: str | None = None
    description: str = ""


class LineageInfo(BaseModel):
    battery_id: str
    experiment_id: str
    lineage_chain: list[dict[str, Any]] = Field(default_factory=list)


class PaginationMeta(BaseModel):
    limit: int
    cursor: str | None = None
    next_cursor: str | None = None
    total: int | None = None


class ResponseEnvelope(BaseModel):
    data: Any = None
    meta: PaginationMeta | dict | None = None

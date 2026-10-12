"""BRW-013X V2.2 — Feature–state correlation workbench.

Canonical grain: one row per eligible MeasurementEvent per FeatureLocator.

Electrical context alignment (§38 join policy):
- All features extracted from the same ultrasound frame inherit the SAME
  measurement_event_id and the same electrical/state context.
- Join key is measurement_event_id ONLY — never cycle, never a gate sample
  position, never a per-gate timestamp rematch.
- Ambiguous synchronization (analysis_eligible=False) is EXCLUDED from
  correlation but keeps ultrasound-only artifacts.

Correlation policy (§39/§129/§139):
- SOC: Pearson + Spearman (average ranks for ties), stratified overall / charge / discharge /
  rest / per-cycle. No causal claims.
- Temperature: only when available; INSUFFICIENT_VARIATION when range too
  small; missing stays null.
- SOH: cycle-level aggregation with pseudoreplication guard; current two
  distinct states are NOT_READY for robust correlation/modeling.
- No naive frame-level p-values (frames are temporally autocorrelated).
"""

from __future__ import annotations

import math
import random
from typing import Any, Literal, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from scipy.stats import rankdata

from battery_workbench.conditions.assignment import ConditionAssignment

CORRELATION_POLICY_ID = "FEATURE_STATE_CORRELATION_POLICY_V5"
JOIN_POLICY_ID = "FEATURE_STATE_JOIN_POLICY_V1"
BATTERY_DECOMPOSITION_POLICY_ID = "BATTERY_WITHIN_BETWEEN_CORRELATION_V1"
CYCLE_DECOMPOSITION_POLICY_ID = "CYCLE_WITHIN_BETWEEN_CORRELATION_V1"
CONDITION_STRATIFICATION_POLICY_ID = "OPERATOR_DECLARED_CONDITION_SOC_STRATIFICATION_V1"
SCATTER_DIAGNOSTIC_POLICY_ID = "BATTERY_STRATIFIED_SCATTER_DIAGNOSTIC_V1"
CORRELATION_POLICY_VERSIONS = {
    "feature_state_correlation": CORRELATION_POLICY_ID,
    "feature_state_join": JOIN_POLICY_ID,
    "battery_decomposition": BATTERY_DECOMPOSITION_POLICY_ID,
    "cycle_within_between_correlation": CYCLE_DECOMPOSITION_POLICY_ID,
    "condition_stratification": CONDITION_STRATIFICATION_POLICY_ID,
    "battery_scatter_diagnostic": SCATTER_DIAGNOSTIC_POLICY_ID,
}

TEMPERATURE_VARIATION_MIN_C = 2.0
SOH_MIN_DISTINCT_STATES = 3  # current data has 2 → NOT_READY


def exploratory_inference_assessment(
    *,
    correlation_results_included: bool,
    study_protocol_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Machine-readable guardrails shared by analysis API and frozen reports.

    A declared plan changes only its displayed registration status. It never
    enables inference or indicates data/scientific readiness.
    """
    protocol = study_protocol_assessment or {
        "status": "NOT_REGISTERED",
        "study_id": None,
        "plan_sha256": None,
        "matching_study_ids": [],
        "invalid_plan_file_count": 0,
        "unresolved_fields": [],
    }
    return {
        "analysis_mode": "EXPLORATORY",
        "claim_scope": "ASSOCIATION_ONLY",
        "independent_unit": "BATTERY",
        "group_count_semantics": "DECLARED_BATTERY_ID",
        "group_identity_status": "NOT_ASSESSED",
        "physical_battery_count": None,
        "correlation_results_included": correlation_results_included,
        "study_protocol_status": protocol.get("status", "UNRESOLVED"),
        "analysis_plan": {
            "status": protocol.get("status", "UNRESOLVED"),
            "study_id": protocol.get("study_id"),
            "plan_sha256": protocol.get("plan_sha256"),
            "matching_study_ids": protocol.get("matching_study_ids", []),
            "invalid_plan_file_count": protocol.get("invalid_plan_file_count", 0),
            "unresolved_fields": protocol.get("unresolved_fields", []),
            "approval_identity_status": protocol.get(
                "approval_identity_status", "NOT_ASSESSED"
            ),
            "approval_evidence_status": protocol.get(
                "approval_evidence_status", "NOT_ASSESSED"
            ),
            "confirmatory_inference_enabled": False,
            "scientific_validity": "NOT_ASSESSED",
            "data_readiness": "NOT_ASSESSED",
        },
        "confidence_interval": {
            "status": "NOT_ESTIMATED",
            "reason": "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN",
        },
        "p_value": {
            "status": "NOT_ESTIMATED",
            "reason": "EVENT_ROWS_ARE_REPEATED_MEASURES",
        },
        "multiple_comparison": {
            "status": "NOT_ASSESSED",
            "reason": "NO_PREDECLARED_TEST_FAMILY",
        },
        "confounder_adjustment": {
            "status": "NOT_ASSESSED",
            "reason": "NO_PREDECLARED_CONFOUNDERS",
        },
    }


class FeatureStateRow(BaseModel):
    """One event-grain analysis input row (§128)."""

    model_config = ConfigDict(validate_assignment=True)

    measurement_event_id: str
    battery_id: str
    experiment_id: str
    cycle: int
    step: int
    state: str  # charge / discharge / rest
    timestamp_s: float
    feature_code: str
    gate_id: str | None = None
    feature_variant: str = "RAW"
    value: float | None
    reference_soc_percent: float | None = None
    temperature_c: float | None = None
    temperature_channel_id: str | None = None
    soh_percent: float | None = None
    analysis_eligible: bool = True

    @field_validator(
        "value", "reference_soc_percent", "temperature_c", "soh_percent",
        mode="before",
    )
    @classmethod
    def normalize_nonfinite_measurements(cls, value: Any) -> Any:
        """Treat NaN/Infinity measurements as missing across all analyses."""
        if value is None:
            return None
        try:
            finite = math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return value
        return value if finite else None


class CorrelationResult(BaseModel):
    """One correlation outcome with honest accounting (§139)."""

    analysis_id: str
    feature_code: str
    gate_id: str | None
    feature_variant: str
    state_variable: str
    scope: str
    method: str
    coefficient: float | None
    n_input: int
    n_input_unit: str = "MEASUREMENT_EVENT"
    n_valid: int
    n_valid_unit: str = "FEATURE_STATE_PAIR"
    independent_group_count: int | None = None
    independent_unit: str | None = None
    group_identity_status: str = "NOT_ASSESSED"
    distinct_state_count: int | None = None
    missing_feature_count: int
    missing_state_count: int
    missing_count_unit: str = "MEASUREMENT_EVENT"
    excluded_ineligible_count: int
    excluded_ineligible_unit: str = "MEASUREMENT_EVENT"
    analysis_mode: str = "EXPLORATORY"
    ml_safe_selection: bool = False
    limitations: list[str] = Field(default_factory=list)
    status: str = "VALID"


class ConditionStratifiedCorrelation(BaseModel):
    """Descriptive SOC association within an operator-declared condition slice."""

    feature_code: str
    policy: str = CONDITION_STRATIFICATION_POLICY_ID
    feature_variant: str
    gate_id: str | None
    condition_axis_id: str
    condition_value: str
    unit: str | None
    declaration_status: str = "OPERATOR_DECLARED"
    absolute_timebase_status: str = "NOT_ASSESSED"
    synchronization_status: str = "NOT_ASSESSED"
    method: str
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
    analysis_mode: str = "EXPLORATORY"
    status: str
    limitations: list[str] = Field(default_factory=list)


def _assert_unique_measurement_event_features(rows: list[FeatureStateRow]) -> None:
    """Reject duplicate rows for an event/feature locator before aggregation."""
    seen: set[tuple[str, str, str, str | None]] = set()
    event_owner: dict[str, tuple[str, str]] = {}
    for row in rows:
        owner = (row.battery_id, row.experiment_id)
        previous_owner = event_owner.setdefault(row.measurement_event_id, owner)
        if previous_owner != owner:
            raise ValueError(
                "MeasurementEvent identity maps to multiple Battery/Experiment groups"
            )
        locator = (
            row.measurement_event_id,
            row.feature_code,
            row.feature_variant,
            row.gate_id,
        )
        if locator in seen:
            raise ValueError(
                "correlation requires one row per MeasurementEvent/FeatureLocator"
            )
        seen.add(locator)


def _select_feature_locator(
    rows: list[FeatureStateRow],
    *,
    feature_code: str,
    gate_id: str | None,
    feature_variant: str,
) -> list[FeatureStateRow]:
    """Select exactly the requested FeatureLocator before calculating."""
    _assert_event_owners(rows)
    return [
        row for row in rows
        if row.feature_code == feature_code
        and row.gate_id == gate_id
        and row.feature_variant == feature_variant
    ]


def _assert_event_owners(rows: list[FeatureStateRow]) -> None:
    event_owner: dict[str, tuple[str, str]] = {}
    for row in rows:
        owner = (row.battery_id, row.experiment_id)
        previous_owner = event_owner.setdefault(row.measurement_event_id, owner)
        if previous_owner != owner:
            raise ValueError(
                "MeasurementEvent identity maps to multiple Battery/Experiment groups"
            )


def _assert_single_feature_locator(rows: list[FeatureStateRow]) -> None:
    """Fail closed when a locator-agnostic summary receives mixed features."""
    locators = {
        (row.feature_code, row.gate_id, row.feature_variant)
        for row in rows
    }
    if len(locators) > 1:
        raise ValueError("analysis requires rows from one FeatureLocator")


def build_event_grain_table(rows: list[FeatureStateRow]) -> list[FeatureStateRow]:
    """Filter to analysis-eligible rows; keep excluded count accounting.

    Ambiguous-sync rows are excluded from correlation by policy (C11) but
    their ultrasound-only feature artifacts remain untouched upstream.
    """
    _assert_unique_measurement_event_features(rows)
    return [r for r in rows if r.analysis_eligible]


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2:
        return float("nan")
    xc = x - x.mean()
    yc = y - y.mean()
    denom = np.sqrt((xc**2).sum() * (yc**2).sum())
    if denom == 0:
        return float("nan")
    return float((xc * yc).sum() / denom)


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2:
        return float("nan")
    rx = rankdata(x, method="average")
    ry = rankdata(y, method="average")
    return _pearson(rx, ry)


def battery_decomposed_soc_correlation(
    rows: list[FeatureStateRow],
) -> dict[str, Any]:
    """Describe within- and between-battery SOC associations separately.

    Within-battery association is calculated after centering feature and SOC
    within each battery, so it describes pooled within-battery co-variation.
    Between-battery association is calculated across declared Battery ID means
    and is only returned when at least three declared groups contribute. This
    structural threshold neither verifies physical identity nor permits
    inferential claims; coefficients are descriptive only.
    """
    _assert_single_feature_locator(rows)
    _assert_unique_measurement_event_features(rows)
    eligible_rows = [row for row in rows if row.analysis_eligible]
    eligible = [
        row for row in eligible_rows
        if row.value is not None
        and row.reference_soc_percent is not None
    ]
    by_battery: dict[str, list[FeatureStateRow]] = {}
    for row in eligible:
        by_battery.setdefault(row.battery_id, []).append(row)

    x_within: list[float] = []
    y_within: list[float] = []
    battery_means: list[tuple[float, float]] = []
    for battery_rows in by_battery.values():
        x = np.asarray([float(cast(float, row.value)) for row in battery_rows])
        y = np.asarray([
            float(cast(float, row.reference_soc_percent)) for row in battery_rows
        ])
        x_within.extend((x - x.mean()).tolist())
        y_within.extend((y - y.mean()).tolist())
        battery_means.append((float(x.mean()), float(y.mean())))

    batteries = len(by_battery)
    within = _pearson(np.asarray(x_within), np.asarray(y_within))
    within_coefficient = None if np.isnan(within) else within
    between_coefficient: float | None = None
    if batteries >= 3:
        means = np.asarray(battery_means)
        between = _pearson(means[:, 0], means[:, 1])
        between_coefficient = None if np.isnan(between) else between

    limitations = [
        "descriptive only; no confidence interval or p-value is estimated",
        "Battery is the independent outer grouping unit",
        "Battery IDs are declared keys; physical battery identity is not independently assessed",
    ]
    if batteries < 3:
        status = "INSUFFICIENT_BATTERY_GROUPS"
        interpretation = "WITHIN_ONLY"
        limitations.append(
            "between-battery association requires at least 3 declared Battery ID groups; "
            "physical identities are not independently assessed and event rows are not independent groups"
        )
    elif within_coefficient is None or between_coefficient is None:
        status = "UNDEFINED_ZERO_VARIANCE"
        interpretation = "UNDEFINED"
        limitations.append("within- or between-battery correlation has zero variance")
    elif within_coefficient * between_coefficient < 0:
        status = "VALID"
        interpretation = "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT"
        limitations.append(
            "between- and within-battery directions disagree; pooled correlation may mislead"
        )
    else:
        status = "VALID"
        interpretation = "DIRECTIONS_NOT_OPPOSED"

    return {
        "policy": BATTERY_DECOMPOSITION_POLICY_ID,
        "status": status,
        "interpretation": interpretation,
        "n_input_events": len(rows),
        "n_events": len(eligible),
        "n_batteries": batteries,
        "declared_battery_group_count": batteries,
        "physical_battery_count": None,
        "battery_identity_status": "NOT_ASSESSED",
        "missing_feature_count": sum(row.value is None for row in eligible_rows),
        "missing_state_count": sum(
            row.value is not None and row.reference_soc_percent is None
            for row in eligible_rows
        ),
        "excluded_ineligible_count": len(rows) - len(eligible_rows),
        "within_battery": {
            "coefficient": within_coefficient,
            "method": "PEARSON_ON_BATTERY_CENTERED_EVENT_VALUES",
            "n_events": len(eligible),
            "n_batteries": batteries,
        },
        "between_battery": {
            "coefficient": between_coefficient,
            "method": "PEARSON_ON_BATTERY_MEANS",
            "n_batteries": batteries if batteries >= 3 else 0,
            "group_count_semantics": "DECLARED_BATTERY_ID",
        },
        "group_count_semantics": "DECLARED_BATTERY_ID",
        "limitations": limitations,
    }


def battery_scatter_diagnostic(
    rows: list[FeatureStateRow],
    *,
    feature_code: str,
    gate_id: str | None = None,
    feature_variant: str = "RAW",
    max_points: int = 300,
    random_seed: int = 21,
) -> dict[str, Any]:
    """Build bounded event points and full-data battery means for diagnostics.

    Event points are sampled deterministically and stratified across batteries;
    the battery mean markers are calculated from every eligible complete pair,
    not from the visualization sample. No fit, interval, or inferential test is
    computed here.
    """
    if max_points < 1:
        raise ValueError("max_points must be positive")

    rows = _select_feature_locator(
        rows, feature_code=feature_code, gate_id=gate_id,
        feature_variant=feature_variant,
    )
    _assert_unique_measurement_event_features(rows)
    eligible = [row for row in rows if row.analysis_eligible]
    complete = [
        row for row in eligible
        if row.value is not None and row.reference_soc_percent is not None
    ]
    by_battery: dict[str, list[FeatureStateRow]] = {}
    for row in complete:
        by_battery.setdefault(row.battery_id, []).append(row)

    n_valid = len(complete)
    cap = min(max_points, n_valid)
    battery_ids = sorted(by_battery)
    allocation = {battery_id: 0 for battery_id in battery_ids}
    if cap >= len(battery_ids):
        for battery_id in battery_ids:
            allocation[battery_id] = 1
        remaining = cap - len(battery_ids)
        if remaining:
            weights = {
                battery_id: max(0, len(by_battery[battery_id]) - 1)
                for battery_id in battery_ids
            }
            total_weight = sum(weights.values())
            exact = {
                battery_id: remaining * weights[battery_id] / total_weight
                if total_weight else 0.0
                for battery_id in battery_ids
            }
            floors = {battery_id: int(exact[battery_id]) for battery_id in battery_ids}
            for battery_id, count in floors.items():
                allocation[battery_id] += count
            left = remaining - sum(floors.values())
            remainder_order = sorted(
                battery_ids,
                key=lambda battery_id: (-(exact[battery_id] - floors[battery_id]), battery_id),
            )
            for battery_id in remainder_order[:left]:
                allocation[battery_id] += 1
    else:
        for battery_id in battery_ids[:cap]:
            allocation[battery_id] = 1

    rng = random.Random(random_seed)
    points: list[dict[str, Any]] = []
    battery_means: list[dict[str, Any]] = []
    for battery_id in battery_ids:
        group = by_battery[battery_id]
        count = allocation[battery_id]
        selected = group if count == len(group) else rng.sample(group, count)
        points.extend(
            {
                "battery_id": battery_id,
                "cycle": row.cycle,
                "state": row.state,
                "feature_value": float(cast(float, row.value)),
                "target_value": float(cast(float, row.reference_soc_percent)),
            }
            for row in selected
        )
        battery_means.append({
            "battery_id": battery_id,
            "n_valid": len(group),
            "feature_mean": float(np.mean([row.value for row in group])),
            "target_mean": float(np.mean([row.reference_soc_percent for row in group])),
        })

    return {
        "policy": SCATTER_DIAGNOSTIC_POLICY_ID,
        "feature_code": feature_code,
        "gate_id": gate_id,
        "feature_variant": feature_variant,
        "target_id": "reference_soc_percent",
        "n_input": len(rows),
        "n_valid": n_valid,
        "missing_feature_count": sum(row.value is None for row in eligible),
        "missing_state_count": sum(
            row.value is not None and row.reference_soc_percent is None for row in eligible
        ),
        "excluded_ineligible_count": len(rows) - len(eligible),
        "sampled": n_valid > len(points),
        "max_points": max_points,
        "random_seed": random_seed,
        "group_coverage_complete": len(points) >= len(battery_ids),
        "points": points,
        "battery_means": battery_means,
        "limitation": (
            "Exploratory visualization only; means use all complete eligible pairs. "
            "No trend fit, confidence interval, or inferential test is computed."
        ),
    }


def cycle_decomposed_soc_correlation(
    rows: list[FeatureStateRow],
) -> dict[str, Any]:
    """Compare descriptive within-cycle and between-cycle SOC directions.

    Cycle groups are nested within Battery/Experiment. Between-cycle
    correlations are suppressed below three groups because two group means
    would force a correlation of exactly +1 or -1.
    """
    _assert_single_feature_locator(rows)
    _assert_unique_measurement_event_features(rows)
    eligible_rows = [row for row in rows if row.analysis_eligible]
    complete = [
        row for row in eligible_rows
        if row.value is not None and row.reference_soc_percent is not None
    ]
    grouped: dict[tuple[str, str, int], list[FeatureStateRow]] = {}
    for row in complete:
        key = (row.battery_id, row.experiment_id, row.cycle)
        grouped.setdefault(key, []).append(row)

    within_x: list[float] = []
    within_y: list[float] = []
    cycle_means: list[tuple[float, float]] = []
    for group in grouped.values():
        x = np.asarray([float(cast(float, row.value)) for row in group])
        y = np.asarray([
            float(cast(float, row.reference_soc_percent)) for row in group
        ])
        within_x.extend((x - x.mean()).tolist())
        within_y.extend((y - y.mean()).tolist())
        cycle_means.append((float(x.mean()), float(y.mean())))

    within = _pearson(np.asarray(within_x), np.asarray(within_y))
    within_coefficient = None if np.isnan(within) else within
    between_coefficient: float | None = None
    cycle_count = len(grouped)
    if cycle_count >= 3:
        means = np.asarray(cycle_means)
        between = _pearson(means[:, 0], means[:, 1])
        between_coefficient = None if np.isnan(between) else between

    limitations = [
        "descriptive only; no confidence interval or p-value is estimated",
        "Cycle groups are nested within Battery/Experiment and are not independent batteries",
    ]
    if cycle_count < 3:
        status = "INSUFFICIENT_CYCLE_GROUPS"
        interpretation = "WITHIN_ONLY"
        limitations.append(
            "between-cycle correlation requires at least 3 complete cycle groups"
        )
    elif within_coefficient is None or between_coefficient is None:
        status = "UNDEFINED_ZERO_VARIANCE"
        interpretation = "UNDEFINED"
        limitations.append("within- or between-cycle correlation has zero variance")
    elif within_coefficient * between_coefficient < 0:
        status = "VALID"
        interpretation = "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT"
        limitations.append(
            "between- and within-cycle directions disagree; pooled correlation may mislead"
        )
    else:
        status = "VALID"
        interpretation = "DIRECTIONS_NOT_OPPOSED"

    return {
        "policy": CYCLE_DECOMPOSITION_POLICY_ID,
        "status": status,
        "interpretation": interpretation,
        "n_input_events": len(rows),
        "n_events": len(complete),
        "n_cycle_groups": cycle_count,
        "n_batteries": len({row.battery_id for row in complete}),
        "declared_battery_group_count": len({row.battery_id for row in complete}),
        "physical_battery_count": None,
        "battery_identity_status": "NOT_ASSESSED",
        "group_count_semantics": "DECLARED_BATTERY_ID",
        "missing_feature_count": sum(row.value is None for row in eligible_rows),
        "missing_state_count": sum(
            row.value is not None and row.reference_soc_percent is None
            for row in eligible_rows
        ),
        "excluded_ineligible_count": len(rows) - len(eligible_rows),
        "within_cycle": {
            "coefficient": within_coefficient,
            "method": "PEARSON_ON_CYCLE_CENTERED_EVENT_VALUES",
            "n_events": len(complete),
            "n_cycle_groups": cycle_count,
        },
        "between_cycle": {
            "coefficient": between_coefficient,
            "method": "PEARSON_ON_CYCLE_MEANS",
            "n_cycle_groups": cycle_count if cycle_count >= 3 else 0,
        },
        "limitations": limitations,
    }


def _stratified(rows: list[FeatureStateRow], state_var: str, scopes: list[str], analysis_id: str,
                feature_code: str, gate_id: str | None, variant: str) -> list[CorrelationResult]:
    results: list[CorrelationResult] = []
    for scope in scopes:
        scoped = [r for r in rows if r.state == scope] if scope != "overall" else rows
        results.append(
            correlate_feature_state(
                scoped, state_variable=state_var, method="pearson",
                analysis_id=f"{analysis_id}:{scope}", feature_code=feature_code,
                gate_id=gate_id, feature_variant=variant, scope=scope,
            )
        )
    return results


def correlate_feature_state(
    rows: list[FeatureStateRow],
    *,
    state_variable: str,
    method: str,
    analysis_id: str,
    feature_code: str,
    gate_id: str | None = None,
    feature_variant: str = "RAW",
    scope: str = "overall",
) -> CorrelationResult:
    """One correlation computation with full honest accounting."""
    rows = _select_feature_locator(
        rows, feature_code=feature_code, gate_id=gate_id,
        feature_variant=feature_variant,
    )
    _assert_unique_measurement_event_features(rows)
    total = len(rows)
    eligible = [r for r in rows if r.analysis_eligible]
    excluded_ineligible = total - len(eligible)

    def _vals(getter) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for r in eligible:
            v = r.value
            s = getter(r)
            if v is None:
                continue
            if s is None:
                continue
            xs.append(float(v))
            ys.append(float(s))
        return xs, ys

    if state_variable == "reference_soc_percent":
        getter = lambda r: r.reference_soc_percent
    elif state_variable == "temperature_c":
        getter = lambda r: r.temperature_c
    elif state_variable == "soh_percent":
        getter = lambda r: r.soh_percent
    else:
        raise ValueError(f"unsupported state variable: {state_variable}")

    xs_all, ys_all = _vals(getter)
    missing_feature = sum(1 for r in eligible if r.value is None)
    missing_state = sum(
        1 for r in eligible if r.value is not None and getter(r) is None
    )
    complete_rows = [
        r for r in eligible if r.value is not None and getter(r) is not None
    ]
    independent_unit = "BATTERY"
    independent_group_count = len({r.battery_id for r in complete_rows})
    distinct_state_count: int | None = None

    limitations: list[str] = []
    status = "VALID"
    coef: float | None = None

    if state_variable == "soh_percent":
        # Summarize repeated event rows first; they are not independent SOH samples.
        grouped: dict[tuple[str, str, int], tuple[list[float], list[float]]] = {}
        for row in complete_rows:
            key = (row.battery_id, row.experiment_id, row.cycle)
            features, states = grouped.setdefault(key, ([], []))
            features.append(float(cast(float, row.value)))
            states.append(float(cast(float, row.soh_percent)))
        xs_all = [float(np.median(features)) for features, _ in grouped.values()]
        ys_all = [float(np.median(states)) for _, states in grouped.values()]
        independent_unit = "BATTERY_EXPERIMENT_CYCLE"
        independent_group_count = len(grouped)
        n_valid_unit = "BATTERY_EXPERIMENT_CYCLE_GROUP"
        # Readiness is based on distinct cycle-level SOH states, not frame rows.
        distinct = len(set(ys_all))
        distinct_state_count = distinct
        limitations.append(
            "SOH association uses median feature and SOH per Battery/Experiment/Cycle; "
            "cycle groups remain nested within batteries and event rows are pseudoreplicated"
        )
        if distinct < SOH_MIN_DISTINCT_STATES:
            status = "NOT_READY_INSUFFICIENT_SOH_STATES"
            limitations.append(
                f"only {distinct} distinct SOH states; robust correlation/modeling "
                f"requires >= {SOH_MIN_DISTINCT_STATES}"
            )
            return CorrelationResult(
                analysis_id=analysis_id, feature_code=feature_code, gate_id=gate_id,
                feature_variant=feature_variant, state_variable=state_variable,
                scope=scope, method=method, coefficient=None,
                n_input=total,
                n_valid_unit=n_valid_unit,
                independent_group_count=independent_group_count,
                independent_unit=independent_unit,
                distinct_state_count=distinct_state_count,
                n_valid=len(xs_all), missing_feature_count=missing_feature,
                missing_state_count=missing_state,
                excluded_ineligible_count=excluded_ineligible,
                limitations=limitations, status=status,
            )

    if state_variable == "temperature_c":
        vals = [getter(r) for r in eligible if getter(r) is not None]
        if not vals:
            status = "TEMPERATURE_UNAVAILABLE"
            limitations.append("temperature missing stays null; no imputation")
            return CorrelationResult(
                analysis_id=analysis_id, feature_code=feature_code, gate_id=gate_id,
                feature_variant=feature_variant, state_variable=state_variable,
                scope=scope, method=method, coefficient=None,
                n_input=total,
                independent_group_count=independent_group_count,
                independent_unit=independent_unit,
                n_valid=0, missing_feature_count=missing_feature,
                missing_state_count=missing_state,
                excluded_ineligible_count=excluded_ineligible,
                limitations=limitations, status=status,
            )
        spread = float(np.max(vals) - np.min(vals))
        limitations.append(
            f"temperature variation screen: observed range {spread:.3g} °C; "
            f"{TEMPERATURE_VARIATION_MIN_C:.3g} °C is only a minimum-variation "
            "screen, not sensor-calibration evidence or target readiness"
        )
        if spread < TEMPERATURE_VARIATION_MIN_C:
            status = "INSUFFICIENT_VARIATION"
            limitations.append(
                f"temperature range {spread:.3g} °C < {TEMPERATURE_VARIATION_MIN_C} °C"
            )
            return CorrelationResult(
                analysis_id=analysis_id, feature_code=feature_code, gate_id=gate_id,
                feature_variant=feature_variant, state_variable=state_variable,
                scope=scope, method=method, coefficient=None,
                n_input=total,
                independent_group_count=independent_group_count,
                independent_unit=independent_unit,
                n_valid=len(xs_all), missing_feature_count=missing_feature,
                missing_state_count=missing_state,
                excluded_ineligible_count=excluded_ineligible,
                limitations=limitations, status=status,
            )

    if len(xs_all) < 3:
        status = "INSUFFICIENT_OVERLAP"
        limitations.append(f"only {len(xs_all)} valid feature×state pairs")
    else:
        x = np.asarray(xs_all)
        y = np.asarray(ys_all)
        if method == "pearson":
            coef = _pearson(x, y)
        elif method == "spearman":
            coef = _spearman(x, y)
        else:
            raise ValueError(f"unsupported method: {method}")
        if np.isnan(coef):
            status = "NUMERICAL_NAN"
            limitations.append("zero-variance input; coefficient undefined")

    # No naive p-value: frames are temporally autocorrelated.
    limitations.append(
        "no naive frame-level p-value: waveform frames are temporally correlated"
    )

    return CorrelationResult(
        analysis_id=analysis_id, feature_code=feature_code, gate_id=gate_id,
        feature_variant=feature_variant, state_variable=state_variable,
        scope=scope, method=method, coefficient=coef,
        n_input=total,
        n_valid_unit=(
            n_valid_unit
            if state_variable == "soh_percent"
            else "FEATURE_STATE_PAIR"
        ),
        independent_group_count=independent_group_count,
        independent_unit=independent_unit,
        distinct_state_count=distinct_state_count,
        n_valid=len(xs_all), missing_feature_count=missing_feature,
        missing_state_count=missing_state,
        excluded_ineligible_count=excluded_ineligible,
        limitations=limitations, status=status,
    )


def soc_correlation_suite(
    rows: list[FeatureStateRow],
    *,
    analysis_id: str,
    feature_code: str,
    gate_id: str | None = None,
    feature_variant: str = "RAW",
) -> list[CorrelationResult]:
    """SOC Pearson + Spearman with charge/discharge/rest stratification (§129).

    Rest is included "where meaningful" — a rest-only scope with < 3 rows is
    reported with INSUFFICIENT_OVERLAP rather than dropped silently.
    """
    out: list[CorrelationResult] = []
    for method in ("pearson", "spearman"):
        for scope in ("overall", "charge", "discharge", "rest"):
            scoped = (
                rows if scope == "overall"
                else [r for r in rows if r.state == scope]
            )
            out.append(
                correlate_feature_state(
                    scoped, state_variable="reference_soc_percent", method=method,
                    analysis_id=f"{analysis_id}:{method}:{scope}",
                    feature_code=feature_code, gate_id=gate_id,
                    feature_variant=feature_variant, scope=scope,
                )
            )
    return out


def condition_stratified_soc(
    rows: list[FeatureStateRow],
    assignments: list[ConditionAssignment],
) -> list[ConditionStratifiedCorrelation]:
    """Describe feature–Reference-SOC associations within explicit condition values.

    Only same-asset-clock assignments are eligible. The result is exploratory,
    operator-declared, and event-grain; it does not estimate uncertainty or
    treat repeated events as independent experimental units.
    """
    _assert_unique_measurement_event_features(rows)
    row_by_identity: dict[tuple[str, str, str, str | None], FeatureStateRow] = {}
    for row in rows:
        identity = (
            row.measurement_event_id,
            row.feature_code,
            row.feature_variant,
            row.gate_id,
        )
        row_by_identity[identity] = row

    grouped: dict[
        tuple[str, str, str | None, str, str, str, str | None],
        list[tuple[FeatureStateRow, ConditionAssignment]],
    ] = {}
    seen_assignments: set[tuple[str, str]] = set()
    for assignment in assignments:
        assignment_identity = (assignment.event_id, assignment.condition_axis_id)
        if assignment_identity in seen_assignments:
            raise ValueError("at most one condition assignment is allowed per event and axis")
        seen_assignments.add(assignment_identity)
        if assignment.status != "ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK":
            continue
        if assignment.condition_value is None:
            raise ValueError("assigned condition must include condition_value")
        matches = [
            row
            for (event_id, _, _, _), row in row_by_identity.items()
            if event_id == assignment.event_id
        ]
        for row in matches:
            key = (
                row.feature_code,
                row.feature_variant,
                row.gate_id,
                assignment.condition_axis_id,
                assignment.condition_value,
                assignment.unit or "",
                assignment.time_reference_asset_id,
            )
            grouped.setdefault(key, []).append((row, assignment))

    results: list[ConditionStratifiedCorrelation] = []
    for key, members in sorted(
        grouped.items(),
        key=lambda item: tuple("" if part is None else part for part in item[0]),
    ):
        feature_code, variant, gate_id, axis, value, unit, _ = key
        feature_rows = [row for row, _ in members]
        segment_ids = sorted({assignment.segment_id for _, assignment in members if assignment.segment_id})
        reference_assets = sorted(
            {assignment.time_reference_asset_id for _, assignment in members
             if assignment.time_reference_asset_id}
        )
        for method in ("pearson", "spearman"):
            result = correlate_feature_state(
                feature_rows,
                state_variable="reference_soc_percent",
                method=method,
                analysis_id=f"condition:{axis}:{value}:{method}",
                feature_code=feature_code,
                gate_id=gate_id,
                feature_variant=variant,
                scope=f"condition:{axis}={value}",
            )
            complete = [
                row for row in feature_rows
                if row.analysis_eligible
                and row.value is not None
                and row.reference_soc_percent is not None
            ]
            limitations = [
                *result.limitations,
                "condition value is operator-declared; achievement was not independently verified",
                "condition-time assignment does not validate absolute timebase or cross-modal synchronization",
                "battery_count is a declared Battery ID group count; physical Battery identity is not assessed",
                "descriptive event-grain association only; no confidence interval or p-value",
            ]
            results.append(
                ConditionStratifiedCorrelation(
                    feature_code=feature_code,
                    feature_variant=variant,
                    gate_id=gate_id,
                    condition_axis_id=axis,
                    condition_value=value,
                    unit=unit or None,
                    method=method,
                    coefficient=result.coefficient,
                    n_input_events=result.n_input,
                    n_valid_pairs=result.n_valid,
                    missing_feature_count=result.missing_feature_count,
                    missing_state_count=result.missing_state_count,
                    excluded_ineligible_count=result.excluded_ineligible_count,
                    battery_count=len({row.battery_id for row in complete}),
                    group_count_semantics="DECLARED_BATTERY_ID",
                    battery_identity_status="NOT_ASSESSED",
                    physical_battery_count=None,
                    cycle_count=len({(row.battery_id, row.experiment_id, row.cycle)
                                     for row in complete}),
                    segment_ids=segment_ids,
                    time_reference_asset_ids=reference_assets,
                    status=result.status,
                    limitations=limitations,
                )
            )
    return results


def cycle_stratified_soc(
    rows: list[FeatureStateRow], *, analysis_id: str, feature_code: str,
    gate_id: str | None = None, feature_variant: str = "RAW",
) -> list[CorrelationResult]:
    """Per-cycle SOC correlation (C16)."""
    rows = _select_feature_locator(
        rows, feature_code=feature_code, gate_id=gate_id,
        feature_variant=feature_variant,
    )
    out: list[CorrelationResult] = []
    for cycle in sorted({r.cycle for r in rows}):
        scoped = [r for r in rows if r.cycle == cycle]
        out.append(
            correlate_feature_state(
                scoped, state_variable="reference_soc_percent", method="pearson",
                analysis_id=f"{analysis_id}:cycle{cycle}", feature_code=feature_code,
                gate_id=gate_id, feature_variant=feature_variant,
                scope=f"cycle:{cycle}",
            )
        )
    return out


def battery_condition_stratified_soc(
    rows: list[FeatureStateRow],
    *,
    analysis_id: str,
    feature_code: str,
    gate_id: str | None = None,
    feature_variant: str = "RAW",
) -> list[dict[str, Any]]:
    """Return descriptive SOC correlations by battery and operating state."""
    rows = _select_feature_locator(
        rows, feature_code=feature_code, gate_id=gate_id,
        feature_variant=feature_variant,
    )
    out: list[dict[str, Any]] = []
    for battery_id in sorted({row.battery_id for row in rows}):
        battery_rows = [row for row in rows if row.battery_id == battery_id]
        for scope in ("overall", "charge", "discharge", "rest"):
            scoped = (
                battery_rows
                if scope == "overall"
                else [row for row in battery_rows if row.state == scope]
            )
            result = correlate_feature_state(
                scoped,
                state_variable="reference_soc_percent",
                method="pearson",
                analysis_id=f"{analysis_id}:{battery_id}:{scope}",
                feature_code=feature_code,
                gate_id=gate_id,
                feature_variant=feature_variant,
                scope=f"battery:{battery_id}:{scope}",
            )
            out.append({
                "battery_id": battery_id,
                "state_scope": scope,
                **result.model_dump(),
            })
    return out


def soh_cycle_summary(
    rows: list[FeatureStateRow],
) -> list[dict[str, Any]]:
    """Cycle-level SOH descriptive summary (§39) — no frame-level claims."""
    _assert_single_feature_locator(rows)
    eligible = build_event_grain_table(rows)
    out: list[dict[str, Any]] = []
    for cycle in sorted({r.cycle for r in eligible}):
        crows = [r for r in eligible if r.cycle == cycle]
        vals = [r.value for r in crows if r.value is not None]
        soh = [r.soh_percent for r in crows if r.soh_percent is not None]
        out.append(
            {
                "cycle": cycle,
                "soh_percent": float(np.mean(soh)) if soh else None,
                "feature_median": float(np.median(vals)) if vals else None,
                "feature_mean": float(np.mean(vals)) if vals else None,
                "feature_std": float(np.std(vals, ddof=1)) if len(vals) > 1 else None,
                "n_frames": len(crows),
            }
        )
    return out

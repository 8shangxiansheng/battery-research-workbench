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
- SOC: Pearson + Spearman, stratified overall / charge / discharge /
  rest / per-cycle. No causal claims.
- Temperature: only when available; INSUFFICIENT_VARIATION when range too
  small; missing stays null.
- SOH: cycle-level aggregation with pseudoreplication guard; current two
  distinct states are NOT_READY for robust correlation/modeling.
- No naive frame-level p-values (frames are temporally autocorrelated).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

CORRELATION_POLICY_ID = "FEATURE_STATE_CORRELATION_POLICY_V1"
JOIN_POLICY_ID = "FEATURE_STATE_JOIN_POLICY_V1"

TEMPERATURE_VARIATION_MIN_C = 2.0
SOH_MIN_DISTINCT_STATES = 3  # current data has 2 → NOT_READY


class FeatureStateRow(BaseModel):
    """One event-grain analysis input row (§128)."""

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
    n_valid: int
    missing_feature_count: int
    missing_state_count: int
    excluded_ineligible_count: int
    analysis_mode: str = "EXPLORATORY"
    ml_safe_selection: bool = False
    limitations: list[str] = Field(default_factory=list)
    status: str = "VALID"


def build_event_grain_table(rows: list[FeatureStateRow]) -> list[FeatureStateRow]:
    """Filter to analysis-eligible rows; keep excluded count accounting.

    Ambiguous-sync rows are excluded from correlation by policy (C11) but
    their ultrasound-only feature artifacts remain untouched upstream.
    """
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
    rx = np.argsort(np.argsort(x)).astype(np.float64)
    ry = np.argsort(np.argsort(y)).astype(np.float64)
    return _pearson(rx, ry)


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

    limitations: list[str] = []
    status = "VALID"
    coef: float | None = None

    if state_variable == "soh_percent":
        # SOH is cycle/group-level — frame rows are pseudoreplicated.
        distinct = len({r.soh_percent for r in eligible if r.soh_percent is not None})
        limitations.append(
            "SOH is cycle-level, not frame-independent; frame rows are pseudoreplicated"
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
                n_valid=0, missing_feature_count=missing_feature,
                missing_state_count=missing_state,
                excluded_ineligible_count=excluded_ineligible,
                limitations=limitations, status=status,
            )
        spread = float(np.max(vals) - np.min(vals))
        if spread < TEMPERATURE_VARIATION_MIN_C:
            status = "INSUFFICIENT_VARIATION"
            limitations.append(
                f"temperature range {spread:.3g} °C < {TEMPERATURE_VARIATION_MIN_C} °C"
            )
            return CorrelationResult(
                analysis_id=analysis_id, feature_code=feature_code, gate_id=gate_id,
                feature_variant=feature_variant, state_variable=state_variable,
                scope=scope, method=method, coefficient=None,
                n_valid=len(vals), missing_feature_count=missing_feature,
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
    eligible = build_event_grain_table(rows)
    out: list[CorrelationResult] = []
    for method in ("pearson", "spearman"):
        for scope in ("overall", "charge", "discharge", "rest"):
            scoped = (
                eligible if scope == "overall"
                else [r for r in eligible if r.state == scope]
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


def cycle_stratified_soc(
    rows: list[FeatureStateRow], *, analysis_id: str, feature_code: str,
    gate_id: str | None = None,
) -> list[CorrelationResult]:
    """Per-cycle SOC correlation (C16)."""
    eligible = build_event_grain_table(rows)
    out: list[CorrelationResult] = []
    for cycle in sorted({r.cycle for r in eligible}):
        scoped = [r for r in eligible if r.cycle == cycle]
        out.append(
            correlate_feature_state(
                scoped, state_variable="reference_soc_percent", method="pearson",
                analysis_id=f"{analysis_id}:cycle{cycle}", feature_code=feature_code,
                gate_id=gate_id, scope=f"cycle:{cycle}",
            )
        )
    return out


def soh_cycle_summary(
    rows: list[FeatureStateRow],
) -> list[dict[str, Any]]:
    """Cycle-level SOH descriptive summary (§39) — no frame-level claims."""
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

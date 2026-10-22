"""BRW-021 analysis engine: descriptive / correlation / subgroup / trend /
gate comparison / redundancy, with a structurally TRAIN-only ML-safe input.

Wording: association / monotonic association / observed relationship only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.feature_analysis.resolve import columns_for, resolve_candidates
from battery_workbench.feature_analysis.schemas import (
    FeatureAnalysisSpec,
)

REDUNDANCY_THRESHOLD = 0.95
REDUNDANCY_POLICY_VERSION = "0.1.0"
MIN_ROWS = 3
MISSING_HEAVY_FRACTION = 0.5
VISUALIZATION_ONLY = "VISUALIZATION_ONLY"


@dataclass
class TrainFeatureAnalysisInput:
    """ML-safe input: physically carries only TRAIN rows for one fold.

    HELD_OUT rows (and therefore their targets) are absent from this object —
    no caller discipline is required.
    """

    frame: pd.DataFrame
    fold: str
    split_id: str
    train_row_count: int
    held_out_row_count: int


def train_feature_input(
    frame: pd.DataFrame, assignments: pd.DataFrame, *, fold: str
) -> TrainFeatureAnalysisInput:
    fold_assign = assignments[assignments["fold"] == fold]
    train_ids = set(fold_assign[fold_assign["role"] == "TRAIN"]["measurement_event_id"])
    train_frame = frame[frame["measurement_event_id"].isin(train_ids)].copy()
    split_id = ""
    if "split_id" in assignments.columns and len(assignments):
        value = assignments["split_id"].dropna()
        if not value.empty:
            split_id = str(value.iloc[0])
    return TrainFeatureAnalysisInput(
        frame=train_frame,
        fold=fold,
        split_id=split_id,
        train_row_count=len(train_frame),
        held_out_row_count=len(fold_assign) - len(train_frame),
    )


def _series(frame: pd.DataFrame | pd.Series, column: str = "") -> pd.Series:
    if isinstance(frame, pd.Series):
        return pd.to_numeric(frame, errors="coerce")
    return pd.to_numeric(frame[column], errors="coerce")


def descriptive_stats(frame: pd.DataFrame, locators: list[str]) -> list[dict[str, Any]]:
    stats = []
    for locator in locators:
        s = _series(frame, locator)
        valid = s.dropna()
        entry = {
            "feature_locator": locator,
            "feature_name": locator.split("@")[0],
            "n": int(s.size),
            "missing_count": int(s.isna().sum()),
            "missing_fraction": float(s.isna().mean()) if s.size else 0.0,
        }
        if valid.empty:
            entry.update(
                {
                    "mean": None,
                    "std": None,
                    "min": None,
                    "p25": None,
                    "median": None,
                    "p75": None,
                    "max": None,
                }
            )
        else:
            entry.update(
                {
                    "mean": float(valid.mean()),
                    "std": float(valid.std(ddof=0)),
                    "min": float(valid.min()),
                    "p25": float(valid.quantile(0.25)),
                    "median": float(valid.median()),
                    "p75": float(valid.quantile(0.75)),
                    "max": float(valid.max()),
                }
            )
        stats.append(entry)
    return stats


def pair_correlation(
    x: pd.Series,
    y: pd.Series,
    method: str,
    *,
    min_rows: int = MIN_ROWS,
    missing_heavy_fraction: float = MISSING_HEAVY_FRACTION,
) -> dict[str, Any]:
    if method not in ("pearson", "spearman"):
        raise ValueError(f"unknown correlation method: {method}")
    data = pd.DataFrame({"x": _series(x, "x"), "y": _series(y, "y")})
    n = len(data.dropna())
    if n < min_rows:
        return {"coefficient": None, "n": n, "status": "INSUFFICIENT_ROWS"}
    missing_fraction = float(data.isna().any(axis=1).mean())
    if missing_fraction >= missing_heavy_fraction:
        return {"coefficient": None, "n": n, "status": "MISSING_HEAVY"}
    x_valid = data["x"].dropna()
    y_valid = data["y"].dropna()
    if x_valid.nunique() <= 1 or y_valid.nunique() <= 1:
        return {"coefficient": None, "n": n, "status": "CONSTANT_FEATURE"}
    paired = data.dropna()
    if paired["x"].nunique() <= 1 or paired["y"].nunique() <= 1:
        return {"coefficient": None, "n": n, "status": "CONSTANT_FEATURE"}
    if method == "pearson":
        coeff = float(paired["x"].corr(paired["y"], method="pearson"))
    else:
        coeff = float(paired["x"].corr(paired["y"], method="spearman"))
    if np.isnan(coeff):
        return {"coefficient": None, "n": n, "status": "NOT_COMPUTABLE"}
    return {"coefficient": coeff, "n": n, "status": "OK"}


def fisher_z_interval(
    coefficient: float | None,
    *,
    n: int,
    confidence: float = 0.95,
    min_rows: int = MIN_ROWS,
) -> tuple[float | None, float | None]:
    """Analytic confidence interval for a correlation via the Fisher z transform.

    Deterministic and seed-free. Returns ``(None, None)`` when the estimate or
    sample is unusable rather than inventing bounds: fewer than ``min_rows``
    pairs, a missing coefficient, or a perfectly correlated sample whose Fisher
    z is infinite.
    """
    from scipy import stats

    if coefficient is None or n < max(min_rows, 4):
        return (None, None)
    if not -1.0 < coefficient < 1.0:
        return (None, None)
    z_value = float(np.arctanh(coefficient))
    standard_error = 1.0 / np.sqrt(n - 3)
    z_critical = float(stats.norm.ppf(0.5 + confidence / 2.0))
    return (
        float(np.tanh(z_value - z_critical * standard_error)),
        float(np.tanh(z_value + z_critical * standard_error)),
    )


def bootstrap_correlation_interval(
    x: pd.Series,
    y: pd.Series,
    method: str,
    *,
    seed: int | None = None,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    min_rows: int = MIN_ROWS,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap interval for a correlation; requires an explicit seed.

    Row resampling ignores grouping, so for pseudo-replicated data prefer the
    aggregated mode of the pseudo-replication diagnostic first. A seed is
    mandatory so a report is reproducible; omitting it raises instead of
    silently drawing random bounds.
    """
    if seed is None:
        raise ValueError("bootstrap correlation interval requires an explicit seed")
    data = pd.DataFrame({"x": _series(x, "x"), "y": _series(y, "y")}).dropna()
    if len(data) < max(min_rows, 4):
        return (None, None)
    if data["x"].nunique() <= 1 or data["y"].nunique() <= 1:
        return (None, None)
    rng = np.random.default_rng(seed)
    x_values = data["x"].to_numpy()
    y_values = data["y"].to_numpy()
    drawn: list[float] = []
    for _ in range(n_resamples):
        positions = rng.integers(0, len(data), len(data))
        sample_x = x_values[positions]
        sample_y = y_values[positions]
        if np.unique(sample_x).size <= 1 or np.unique(sample_y).size <= 1:
            continue
        value = float(pd.Series(sample_x).corr(pd.Series(sample_y), method=method))
        if not np.isnan(value):
            drawn.append(value)
    if not drawn:
        return (None, None)
    tail = (1.0 - confidence) / 2.0 * 100.0
    return (
        float(np.percentile(drawn, tail)),
        float(np.percentile(drawn, 100.0 - tail)),
    )


def benjamini_hochberg(
    p_values: list[float | None], *, alpha: float = 0.05
) -> list[float | None]:
    """Benjamini-Hochberg adjusted p-values, preserving input order.

    ``None`` entries are carried through untouched and excluded from the family
    size, so an incomputable feature cannot inflate or shrink the correction.
    The adjusted value answers one question only: does this association survive
    multiplicity at ``alpha``? It is still an exploratory statement, not a
    confirmatory or causal claim.
    """
    indexed = [(position, value) for position, value in enumerate(p_values) if value is not None]
    adjusted: list[float | None] = [None] * len(p_values)
    if not indexed:
        return adjusted
    ordered = sorted(indexed, key=lambda item: item[1])
    family_size = len(ordered)
    monotone = 1.0
    for rank in range(family_size, 0, -1):
        position, value = ordered[rank - 1]
        monotone = min(monotone, float(value) * family_size / rank)
        adjusted[position] = min(1.0, max(0.0, monotone))
    return adjusted


def effective_independent_units(frame: pd.DataFrame, *, group_column: str) -> int | None:
    """Number of distinct independent units (group values) in a frame."""
    if group_column not in frame.columns:
        return None
    return int(frame[group_column].dropna().astype(str).nunique())


def pseudo_replication_diagnostic(
    frame: pd.DataFrame,
    *,
    target: str,
    group_column: str = "cycle_group_id",
) -> dict[str, Any]:
    """Compare nominal rows with independent units for the target.

    Frames within one cycle/event share a reference target, so the row count
    overstates independent evidence. This reports the gap instead of silently
    treating every row as an independent observation.
    """
    nominal_rows = len(frame)
    units = effective_independent_units(frame, group_column=group_column)
    if units is None:
        return {
            "target": target,
            "group_column": group_column,
            "nominal_rows": nominal_rows,
            "independent_units": None,
            "replication_factor": None,
            "status": "GROUP_COLUMN_ABSENT",
            "message": (
                f"no {group_column!r} column; independent-unit count cannot be assessed "
                "and rows must not be assumed independent"
            ),
            "action": "REPORT_ONLY",
        }
    if units == 0:
        return {
            "target": target,
            "group_column": group_column,
            "nominal_rows": nominal_rows,
            "independent_units": 0,
            "replication_factor": None,
            "status": "NO_UNITS",
            "message": "no independent units with a non-null group key",
            "action": "REPORT_ONLY",
        }
    replication_factor = nominal_rows / units
    replicated = replication_factor > 1.0
    return {
        "target": target,
        "group_column": group_column,
        "nominal_rows": nominal_rows,
        "independent_units": units,
        "replication_factor": replication_factor,
        "status": "PSEUDO_REPLICATED" if replicated else "OK",
        "message": (
            f"{nominal_rows} rows span only {units} independent {group_column} units "
            f"(x{replication_factor:.1f}); rows are not independent observations"
            if replicated
            else f"{nominal_rows} rows map to {units} independent {group_column} units"
        ),
        "action": "AGGREGATE_PER_UNIT_OPTIONAL (report the row-to-unit gap regardless)",
    }


def subgroup_effect_split(
    frame: pd.DataFrame,
    locator: str,
    target: str,
    *,
    group_column: str,
    min_rows: int = MIN_ROWS,
) -> dict[str, Any]:
    """Separate pooled, between-group and within-group association.

    A pooled coefficient can hide a reversal between the group-level trend and
    the trend inside every group (Simpson's paradox). This reports all three and
    a verdict instead of one blended number.
    """
    if group_column not in frame.columns:
        return {
            "group_column": group_column,
            "status": "GROUP_COLUMN_ABSENT",
            "pooled_rho": None,
            "between_rho": None,
            "within_rho": None,
            "verdict": "NOT_ASSESSABLE",
        }
    data = frame[[group_column, locator, target]].rename(
        columns={group_column: "g", locator: "x", target: "y"}
    ).dropna()
    pooled = pair_correlation(data["x"], data["y"], "spearman", min_rows=min_rows)
    per_group: list[float] = []
    means: list[tuple[float, float]] = []
    for _, group in data.groupby("g", observed=True):
        if len(group) < max(min_rows, 3):
            continue
        means.append((float(group["x"].mean()), float(group["y"].mean())))
        result = pair_correlation(group["x"], group["y"], "spearman", min_rows=min_rows)
        if result["coefficient"] is not None:
            per_group.append(float(result["coefficient"]))
    within = float(np.median(per_group)) if per_group else None
    between = None
    if len(means) >= 3:
        between_result = pair_correlation(
            pd.Series([m[0] for m in means]),
            pd.Series([m[1] for m in means]),
            "spearman",
            min_rows=3,
        )
        between = between_result["coefficient"]
    pooled_value = pooled["coefficient"]
    verdict = "NOT_ASSESSABLE"
    if pooled_value is not None and within is not None and between is not None:
        disagrees = (pooled_value * within < 0) or (between * within < 0)
        verdict = "GROUP_AND_WITHIN_DISAGREE" if disagrees else "CONSISTENT"
    elif pooled_value is not None and within is not None:
        verdict = "WITHIN_ONLY (too few groups for a between-group trend)"
    return {
        "group_column": group_column,
        "status": "OK",
        "group_count": int(data["g"].nunique()),
        "pooled_rho": pooled_value,
        "between_rho": between,
        "within_rho": within,
        "per_group_rho": [round(value, 6) for value in per_group],
        "verdict": verdict,
        "interpretation": (
            "association only; a disagreement between group-level and within-group "
            "trends means the pooled coefficient must not be reported alone"
        ),
    }


def feature_target_correlation(
    frame: pd.DataFrame, locators: list[str], target: str, *, methods: list[str]
) -> list[dict[str, Any]]:
    rows = []
    correlation_methods = [m for m in methods if m in ("pearson", "spearman")]
    for locator in locators:
        for method in correlation_methods:
            r = pair_correlation(frame[locator], frame[target], method)
            rows.append(
                {
                    "feature_locator": locator,
                    "feature_name": locator.split("@")[0],
                    "target": target,
                    "method": method,
                    **r,
                }
            )
    return rows


def pairwise_correlation(frame: pd.DataFrame, locators: list[str]) -> pd.DataFrame:
    rows = []
    for i, a in enumerate(locators):
        for b in locators[i + 1 :]:
            pearson = pair_correlation(frame[a], frame[b], "pearson")
            spearman = pair_correlation(frame[a], frame[b], "spearman")
            rows.append(
                {
                    "feature_a": a,
                    "feature_b": b,
                    "pearson_r": pearson["coefficient"],
                    "spearman_rho": spearman["coefficient"],
                    "n": pearson["n"],
                }
            )
    return pd.DataFrame(rows)


def redundancy_diagnostics(
    pairwise: pd.DataFrame, *, threshold: float = REDUNDANCY_THRESHOLD
) -> list[dict[str, Any]]:
    rows = []
    for _, r in pairwise.iterrows():
        verdict = "NOT_COMPUTABLE"
        max_r = (
            max(abs(v) for v in (r["pearson_r"], r["spearman_rho"]) if v is not None)
            if (r["pearson_r"] is not None or r["spearman_rho"] is not None)
            else None
        )
        if max_r is not None:
            verdict = "HIGH_REDUNDANCY" if max_r >= threshold else "OK"
        rows.append(
            {
                "feature_a": r["feature_a"],
                "feature_b": r["feature_b"],
                "max_abs_association": max_r,
                "threshold": threshold,
                "verdict": verdict,
                "action": "FLAG_ONLY (no automatic deletion)",
            }
        )
    return rows


def trend_bins(
    frame: pd.DataFrame, locator: str, target: str, *, n_bins: int = 10
) -> list[dict[str, Any]]:
    """Visualization-only binned trend; must not be used for splitting."""
    data = pd.DataFrame({"f": _series(frame, locator), "t": _series(frame, target)})
    quantized = data.dropna()
    if quantized.empty:
        return []
    try:
        quantized = quantized.assign(bin=pd.qcut(quantized["t"], q=n_bins, duplicates="drop"))
    except ValueError:
        return []
    rows = []
    for _, g in quantized.groupby("bin", observed=True):
        rows.append(
            {
                "target_min": float(g["t"].min()),
                "target_max": float(g["t"].max()),
                "feature_mean": float(g["f"].mean()),
                "feature_median": float(g["f"].median()),
                "feature_std": float(g["f"].std(ddof=0)),
                "count": len(g),
                "purpose": VISUALIZATION_ONLY,
            }
        )
    return rows


def subgroup_analysis(
    frame: pd.DataFrame,
    locators: list[str],
    target: str,
    *,
    subgroup_by: str,
    min_rows: int = MIN_ROWS,
) -> list[dict[str, Any]]:
    rows = []
    for subgroup, g in frame.groupby(subgroup_by, observed=True):
        for locator in locators:
            entry: dict[str, Any] = {
                "subgroup_by": subgroup_by,
                "subgroup": str(subgroup),
                "feature_locator": locator,
                "n": len(g),
            }
            if len(g) < min_rows:
                entry["status"] = "INSUFFICIENT_ROWS"
                entry["spearman_rho"] = None
            else:
                r = pair_correlation(g[locator], g[target], "spearman")
                entry["status"] = r["status"]
                entry["spearman_rho"] = r["coefficient"]
            rows.append(entry)
    return rows


def gate_comparison(
    frame: pd.DataFrame,
    feature_name: str,
    gate_ids: list[str],
    target: str,
) -> list[dict[str, float | int | str | None]]:
    """Same feature across gates: association / distribution / coverage.
    Never announces a best gate."""
    rows: list[dict[str, float | int | str | None]] = []
    for gate_id in gate_ids:
        locator = f"{feature_name}@{gate_id}"
        if locator not in frame.columns:
            rows.append({"gate_id": gate_id, "locator": locator, "status": "MISSING_COLUMN"})
            continue
        s = _series(frame, locator)
        corr = pair_correlation(frame[locator], frame[target], "spearman")
        rows.append(
            {
                "gate_id": gate_id,
                "locator": locator,
                "pearson_r": pair_correlation(frame[locator], frame[target], "pearson")[
                    "coefficient"
                ],
                "spearman_rho": corr["coefficient"],
                "n": corr["n"],
                "coverage": float(s.notna().mean()) if s.size else 0.0,
                "mean": float(s.mean()) if s.notna().any() else None,
                "std": float(s.std(ddof=0)) if s.notna().any() else None,
            }
        )
    return rows


def run_analysis(spec: FeatureAnalysisSpec, frame: pd.DataFrame) -> dict[str, Any]:
    resolved = resolve_candidates(spec.candidate_features, frame, mode=spec.analysis_mode.value)
    available = columns_for(resolved)
    target_ok = spec.target in frame.columns
    result: dict[str, Any] = {
        "analysis_id": spec.analysis_id,
        "analysis_mode": spec.analysis_mode.value,
        "availability": resolved,
        "descriptive": [],
        "correlations": [],
        "redundancy": [],
        "trend_bins": {},
        "subgroups": {},
        "subgroup_effects": {},
        "pseudo_replication": {},
        "gate_comparison": {},
        "auto_removed_features": [],
    }
    if not available or not target_ok:
        return result
    result["descriptive"] = descriptive_stats(frame, available)
    result["correlations"] = feature_target_correlation(
        frame, available, spec.target, methods=spec.methods
    )
    # P4: attach uncertainty intervals to every computable association.
    for row in result["correlations"]:
        coefficient = row.get("coefficient")
        if spec.interval_method == "BOOTSTRAP":
            locator = row.get("feature_locator")
            if locator in frame.columns:
                low, high = bootstrap_correlation_interval(
                    frame[locator],
                    frame[spec.target],
                    row.get("method", "pearson"),
                    seed=spec.bootstrap_seed,
                    n_resamples=spec.bootstrap_resamples,
                )
            else:
                low, high = (None, None)
        else:
            low, high = fisher_z_interval(coefficient, n=int(row.get("n") or 0))
        row["ci_low"] = low
        row["ci_high"] = high
        row["interval_method"] = spec.interval_method

    # P4: BH-FDR across the whole feature x method family; raw values are kept
    # so an adjusted verdict is always comparable to the unadjusted one.
    if spec.multiplicity_correction == "BENJAMINI_HOCHBERG":
        from scipy import stats

        p_values = []
        for row in result["correlations"]:
            coefficient = row.get("coefficient")
            n = int(row.get("n") or 0)
            if coefficient is None or n < 4 or abs(coefficient) >= 1.0:
                p_values.append(None)
                continue
            statistic = float(np.arctanh(coefficient)) * np.sqrt(n - 3)
            p_values.append(float(2.0 * stats.norm.sf(abs(statistic))))
        for row, raw_p, adjusted in zip(
            result["correlations"], p_values, benjamini_hochberg(p_values)
        ):
            row["p_value_raw"] = raw_p
            row["p_value_adjusted"] = adjusted
            row["multiplicity_correction"] = "BENJAMINI_HOCHBERG"

    # P4: report the row-to-independent-unit gap so pseudo replication is
    # visible rather than silently treated as independent evidence.
    result["pseudo_replication"] = pseudo_replication_diagnostic(
        frame, target=spec.target, group_column=spec.pseudo_replication_group_column
    )
    if spec.pseudo_replication_group_column in frame.columns:
        result["subgroup_effects"] = {
            locator: subgroup_effect_split(
                frame,
                locator,
                spec.target,
                group_column=spec.pseudo_replication_group_column,
            )
            for locator in available
        }
    pairwise = pairwise_correlation(frame, available)
    result["pairwise"] = pairwise
    result["redundancy"] = redundancy_diagnostics(pairwise)
    for locator in available:
        result["trend_bins"][locator] = trend_bins(frame, locator, spec.target)
    if "step_type" in frame.columns and "step_type" in spec.subgroup_by:
        result["subgroups"]["direction"] = subgroup_analysis(
            frame, available, spec.target, subgroup_by="step_type"
        )
    if "cycle_group_id" in frame.columns and "cycle" in spec.subgroup_by:
        result["subgroups"]["cycle"] = subgroup_analysis(
            frame, available, spec.target, subgroup_by="cycle_group_id"
        )
    gated = [r for r in resolved if r["role"] == "GATED" and r["status"] == "AVAILABLE"]
    by_name: dict[str, list[str]] = {}
    for r in gated:
        by_name.setdefault(r["feature_name"], []).append(r["gate_id"])
    for name, gate_ids in by_name.items():
        if len(gate_ids) >= 2:
            result["gate_comparison"][name] = gate_comparison(frame, name, gate_ids, spec.target)
    return result

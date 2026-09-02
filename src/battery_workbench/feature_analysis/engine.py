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
        "gate_comparison": {},
        "auto_removed_features": [],
    }
    if not available or not target_ok:
        return result
    result["descriptive"] = descriptive_stats(frame, available)
    result["correlations"] = feature_target_correlation(
        frame, available, spec.target, methods=spec.methods
    )
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

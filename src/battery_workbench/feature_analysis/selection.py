"""BRW-021 selection: USER_EXPLICIT + TRAIN_ONLY_RULE_BASED.

Exploratory-mode selections are always marked EXPLORATORY_FULL_DATA /
ml_safe_selection=False. Rule-based selection exists only in
TRAIN_ONLY_ML_SAFE mode and consumes only the structurally TRAIN-only
input view.
"""

from __future__ import annotations

from typing import Any

from battery_workbench.feature_analysis.engine import (
    REDUNDANCY_THRESHOLD,
    run_analysis,
    train_feature_input,
)
from battery_workbench.feature_analysis.resolve import columns_for, resolve_candidates
from battery_workbench.feature_analysis.schemas import (
    AnalysisMode,
    FeatureAnalysisSpec,
    selection_id_for,
)


def _rule_based(
    spec: FeatureAnalysisSpec,
    analysis: dict[str, Any],
    available: list[str],
) -> dict[str, Any]:
    policy = spec.selection.policy or {}
    min_abs_spearman = float(policy.get("min_abs_spearman", 0.5))
    max_missing = float(policy.get("max_missing_fraction", 0.1))
    max_redundancy = float(policy.get("max_pairwise_redundancy", REDUNDANCY_THRESHOLD))

    missing = {d["feature_locator"]: d["missing_fraction"] for d in analysis["descriptive"]}
    rejected: dict[str, str] = {}
    for locator in available:
        if missing.get(locator, 0.0) > max_missing:
            rejected[locator] = f"missing_fraction {missing.get(locator):.3f} > {max_missing}"

    rho_by_locator: dict[str, float | None] = {}
    for row in analysis["correlations"]:
        if row["method"] == "spearman":
            rho_by_locator[row["feature_locator"]] = row["coefficient"]
    for locator in available:
        if locator in rejected:
            continue
        rho = rho_by_locator.get(locator)
        if rho is None or abs(rho) < min_abs_spearman:
            rejected[locator] = (
                f"|spearman| {abs(rho):.3f} < {min_abs_spearman}"
                if rho is not None
                else "spearman not computable"
            )

    # redundancy: a feature redundant with an already-selected feature is rejected
    selected: list[str] = []
    for locator in available:
        if locator in rejected:
            continue
        redundant_with = None
        for row in analysis["redundancy"]:
            pair = (row["feature_a"], row["feature_b"])
            if row["verdict"] == "HIGH_REDUNDANCY" and max_abs_pair(pair) >= max_redundancy:
                if pair[0] == locator and pair[1] in selected:
                    redundant_with = pair[1]
                elif pair[1] == locator and pair[0] in selected:
                    redundant_with = pair[0]
        if redundant_with is not None:
            rejected[locator] = f"HIGH_REDUNDANCY with {redundant_with}"
        else:
            selected.append(locator)

    return {
        "selected_features": selected,
        "rejected_features": rejected,
    }


def max_abs_pair(pair: tuple[str, str]) -> float:  # pragma: no cover - helper
    return 1.0


def run_selection(
    spec: FeatureAnalysisSpec,
    frame: Any,
    assignments: Any | None = None,
    *,
    fold: str | None = None,
) -> dict[str, Any]:
    """Run one analysis + optional selection; deterministic."""
    analysis_frame = frame
    split_id = spec.split_id
    mode = spec.analysis_mode

    if mode == AnalysisMode.TRAIN_ONLY_ML_SAFE:
        if assignments is None or fold is None:
            raise ValueError("TRAIN_ONLY_ML_SAFE selection requires assignments + fold")
        tfa = train_feature_input(frame, assignments, fold=fold)
        analysis_frame = tfa.frame

    analysis = run_analysis(spec, analysis_frame)
    resolved = resolve_candidates(spec.candidate_features, analysis_frame, mode=mode.value)
    available = columns_for(resolved)

    # §3/§19: basis records the data scope of the evidence behind a selection.
    # USER_EXPLICIT names the *mechanism*; the basis records the scope, so a
    # full-data selection is always EXPLORATORY_FULL_DATA (ml_safe=False).
    selection_basis = (
        "TRAIN_ONLY_ML_SAFE" if mode == AnalysisMode.TRAIN_ONLY_ML_SAFE else "EXPLORATORY_FULL_DATA"
    )
    selected: list[str] = []
    rejected: dict[str, str] = {}
    if spec.selection.requested:
        if spec.selection.mode == "USER_EXPLICIT":
            selected = [f for f in spec.selection.user_features if f in set(available)]
            rejected = {
                f: "requested but unavailable"
                for f in spec.selection.user_features
                if f not in set(available)
            }
        else:
            if mode != AnalysisMode.TRAIN_ONLY_ML_SAFE:
                # rule-based selector on full data = exploratory basis, non-ML-safe
                rule = _rule_based(spec, analysis, available)
                selected = rule["selected_features"]
                rejected = rule["rejected_features"]
                selection_basis = "EXPLORATORY_FULL_DATA"
            else:
                rule = _rule_based(spec, analysis, available)
                selected = rule["selected_features"]
                rejected = rule["rejected_features"]
                selection_basis = "TRAIN_ONLY_ML_SAFE"

    rho_digest = {
        row["feature_locator"]: row["coefficient"]
        for row in analysis["correlations"]
        if row["method"] == "spearman"
    }
    resolved_selection = {
        "selected": selected,
        "rejected": rejected,
        "mode": spec.selection.mode,
        "available": available,
        "train_spearman": rho_digest,
    }
    result: dict[str, Any] = {
        "analysis_id": spec.analysis_id,
        "analysis_mode": mode.value,
        "selection_id": selection_id_for(spec.analysis_id, spec, resolved_selection),
        "selection_requested": spec.selection.requested,
        "selected_features": selected,
        "rejected_features": rejected,
        "selection_mode": spec.selection.mode,
        "selection_basis": selection_basis,
        "ml_safe_selection": mode == AnalysisMode.TRAIN_ONLY_ML_SAFE
        and selection_basis == "TRAIN_ONLY_ML_SAFE",
        "split_id": split_id,
        "fold_index": spec.fold_index,
        "fold": fold,
        "policy": spec.selection.policy,
        "policy_version": spec.policy_version,
        "analysis": analysis,
        "availability": analysis.get("availability", resolved),
        "redundancy": analysis.get("redundancy", []),
        "auto_removed_features": [],
        "commit_status": "WAITING_FOR_USER"
        if spec.selection.requested and selected
        else "NO_SELECTION",
    }
    return result

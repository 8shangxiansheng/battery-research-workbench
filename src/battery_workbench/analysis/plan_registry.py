"""Resolve an experiment's explicitly declared study analysis plan read-only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from battery_workbench.analysis.plan_preflight import (
    AnalysisPlanPreflightError,
    assess_analysis_plan,
)


def _empty_assessment(status: str, *, invalid_count: int = 0) -> dict[str, Any]:
    return {
        "status": status,
        "study_id": None,
        "plan_sha256": None,
        "study_status": None,
        "approval_identity_status": "NOT_ASSESSED",
        "approval_evidence_status": "NOT_ASSESSED",
        "claim_scope": None,
        "unresolved_fields": [],
        "matching_study_ids": [],
        "invalid_plan_file_count": invalid_count,
        "requested_confirmatory_inference": False,
        "confirmatory_inference_enabled": False,
        "scientific_validity": "NOT_ASSESSED",
        "data_readiness": "NOT_ASSESSED",
    }


def _eligible_pair_matches(
    assessment: dict[str, Any], battery_id: str, experiment_id: str
) -> bool:
    pairs = assessment.get("eligible_batteries_and_experiments")
    if not isinstance(pairs, list) or not pairs:
        return False
    if any(
        not isinstance(pair, dict)
        or not isinstance(pair.get("battery_id"), str)
        or not isinstance(pair.get("experiment_id"), str)
        for pair in pairs
    ):
        return False
    return any(
        pair["battery_id"].strip() == battery_id
        and pair["experiment_id"].strip() == experiment_id
        for pair in pairs
    )


def resolve_experiment_analysis_plan(
    raw_root: str | Path, *, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Match a plan only by an exact declared Battery/Experiment pair.

    Plans live at ``data/annotations/studies/{study_id}/analysis-plan.yaml``.
    Invalid or ambiguous files are surfaced rather than treated as absent or
    implicitly choosing one plan. Results never authorize statistical work.
    """
    data_root = Path(raw_root).resolve().parent
    annotations_root = data_root / "annotations"
    root = annotations_root / "studies"
    try:
        resolved_data_root = data_root.resolve(strict=False)
        resolved_annotations_root = annotations_root.resolve(strict=False)
        resolved_root = root.resolve()
        resolved_annotations_root.relative_to(resolved_data_root)
        resolved_root.relative_to(resolved_annotations_root)
    except OSError:
        return _empty_assessment("UNRESOLVED_INVALID_PLAN_FILES", invalid_count=1)
    except (RuntimeError, ValueError):
        return _empty_assessment("UNRESOLVED_INVALID_PLAN_FILES", invalid_count=1)
    if not resolved_root.is_dir():
        return _empty_assessment("NOT_REGISTERED")

    matching: list[dict[str, Any]] = []
    invalid_count = 0
    try:
        study_directories = sorted(resolved_root.iterdir(), key=lambda item: item.name)
    except OSError:
        return _empty_assessment("UNRESOLVED_INVALID_PLAN_FILES", invalid_count=1)

    for study_directory in study_directories:
        if not study_directory.is_dir():
            if study_directory.is_symlink():
                invalid_count += 1
            continue
        try:
            resolved_directory = study_directory.resolve(strict=True)
            resolved_directory.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            invalid_count += 1
            continue
        plan_path = resolved_directory / "analysis-plan.yaml"
        if not plan_path.exists() and not plan_path.is_symlink():
            continue
        try:
            resolved_plan = plan_path.resolve(strict=True)
            resolved_plan.relative_to(resolved_root)
            if not resolved_plan.is_file():
                invalid_count += 1
                continue
            assessment = assess_analysis_plan(resolved_plan)
        except (OSError, RuntimeError, ValueError, AnalysisPlanPreflightError):
            invalid_count += 1
            continue

        if assessment.get("study_id") != study_directory.name:
            invalid_count += 1
            continue
        pairs = assessment.get("eligible_batteries_and_experiments")
        if not isinstance(pairs, list) or any(
            not isinstance(pair, dict)
            or not isinstance(pair.get("battery_id"), str)
            or not isinstance(pair.get("experiment_id"), str)
            for pair in pairs
        ):
            invalid_count += 1
            continue
        if _eligible_pair_matches(assessment, battery_id, experiment_id):
            matching.append(assessment)

    matched_ids = sorted(
        str(plan["study_id"]) for plan in matching if isinstance(plan.get("study_id"), str)
    )
    if invalid_count:
        result = _empty_assessment(
            "UNRESOLVED_INVALID_PLAN_FILES", invalid_count=invalid_count
        )
        result["matching_study_ids"] = matched_ids
        return result
    if not matching:
        return _empty_assessment("NOT_REGISTERED")
    if len(matching) > 1:
        result = _empty_assessment("AMBIGUOUS")
        result["matching_study_ids"] = matched_ids
        return result

    result = dict(matching[0])
    result["matching_study_ids"] = matched_ids
    result["invalid_plan_file_count"] = 0
    result["confirmatory_inference_enabled"] = False
    result["scientific_validity"] = "NOT_ASSESSED"
    result["data_readiness"] = "NOT_ASSESSED"
    return result

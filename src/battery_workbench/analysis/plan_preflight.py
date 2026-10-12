"""Read-only decision-completeness preflight for research analysis plans.

This module checks declarations only. It never executes a statistical method,
assesses scientific validity, or enables confirmatory inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ANALYSIS_PLAN_VERSION = "brw-analysis-plan-template/1.1"
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "study",
    "research_question",
    "primary_analysis",
    "repeated_measurement_structure",
    "uncertainty_and_inference",
    "confounding_and_sensitivity",
    "data_and_sync_gates",
    "evaluation_separation",
    "decision_log",
    "limitations_and_open_questions",
}


class AnalysisPlanPreflightError(ValueError):
    """The analysis plan cannot be read or does not match its declared version."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing analysis plan mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _get(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _text_present(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "UNDECIDED"


def _decision_complete(
    plan: dict[str, Any], unresolved: list[str], invalid: list[str]
) -> None:
    required_text = (
        "study.study_id",
        "study.title",
        "study.version",
        "research_question.question",
        "research_question.target_population",
        "primary_analysis.endpoint.target_id",
        "primary_analysis.endpoint.operational_definition",
        "primary_analysis.endpoint.unit",
        "primary_analysis.endpoint.source_and_method_version",
        "primary_analysis.endpoint.observation_grain",
        "primary_analysis.endpoint.uncertainty_source",
        "primary_analysis.feature.feature_id",
        "primary_analysis.feature.feature_variant",
        "primary_analysis.feature.operational_definition_and_version",
        "primary_analysis.feature.unit",
        "primary_analysis.relationship.estimand",
        "primary_analysis.relationship.method",
        "primary_analysis.relationship.scope",
        "primary_analysis.relationship.directionality",
        "repeated_measurement_structure.within_battery_dependence_handling",
        "repeated_measurement_structure.between_battery_estimand",
        "repeated_measurement_structure.aggregation_or_weighting",
        "uncertainty_and_inference.resampling_method",
        "data_and_sync_gates.accepted_target_semantics",
        "data_and_sync_gates.minimum_sync_status",
        "data_and_sync_gates.ambiguity_policy",
        "data_and_sync_gates.missing_data_policy",
        "data_and_sync_gates.protocol_deviation_policy",
    )
    required_lists = (
        "primary_analysis.inclusion_rule_ids",
        "primary_analysis.exclusion_rule_ids",
        "repeated_measurement_structure.hierarchy",
        "data_and_sync_gates.required_target_provenance",
        "data_and_sync_gates.required_feature_provenance",
    )
    for path in required_text:
        if not _text_present(_get(plan, path)):
            unresolved.append(path)
    for path in required_lists:
        value = _get(plan, path)
        if (
            not isinstance(value, list)
            or not value
            or any(not _text_present(item) for item in value)
        ):
            unresolved.append(path)

    eligible_pairs = _get(plan, "primary_analysis.eligible_batteries_and_experiments")
    if not isinstance(eligible_pairs, list) or not eligible_pairs:
        unresolved.append("primary_analysis.eligible_batteries_and_experiments")
    else:
        normalized_pairs: list[tuple[str, str]] = []
        for pair in eligible_pairs:
            if not isinstance(pair, dict):
                unresolved.append("primary_analysis.eligible_batteries_and_experiments")
                break
            battery_id = pair.get("battery_id")
            experiment_id = pair.get("experiment_id")
            if not _text_present(battery_id) or not _text_present(experiment_id):
                unresolved.append("primary_analysis.eligible_batteries_and_experiments")
                break
            normalized_pairs.append((battery_id.strip(), experiment_id.strip()))
        if len(normalized_pairs) != len(set(normalized_pairs)):
            invalid.append("eligible Battery/Experiment pairs must be unique")

    scope = _get(plan, "research_question.intended_claim_scope")
    if not isinstance(scope, str) or scope not in {"EXPLORATORY", "CONFIRMATORY"}:
        unresolved.append("research_question.intended_claim_scope")
    directionality = _get(plan, "primary_analysis.relationship.directionality")
    if not isinstance(directionality, str) or directionality not in {
        "TWO_SIDED", "POSITIVE", "NEGATIVE"
    }:
        unresolved.append("primary_analysis.relationship.directionality")

    for path in (
        "primary_analysis.independent_unit",
        "uncertainty_and_inference.resampling_unit",
        "evaluation_separation.held_out_unit",
    ):
        if _get(plan, path) != "BATTERY":
            invalid.append(f"{path} must remain BATTERY")

    _check_choice(
        plan,
        "repeated_measurement_structure.review_status",
        {"REVIEWED"},
        unresolved,
        invalid,
    )
    _check_choice(
        plan,
        "uncertainty_and_inference.confidence_interval.status",
        {"PLANNED", "NOT_PLANNED"},
        unresolved,
        invalid,
    )
    _check_choice(
        plan,
        "uncertainty_and_inference.p_value.status",
        {"PLANNED", "NOT_PLANNED"},
        unresolved,
        invalid,
    )
    _check_choice(
        plan,
        "uncertainty_and_inference.multiple_comparison.status",
        {"ADJUST", "NOT_APPLICABLE"},
        unresolved,
        invalid,
    )
    _check_choice(
        plan,
        "confounding_and_sensitivity.confounder_review_status",
        {"REVIEWED_NONE", "CANDIDATES_SPECIFIED"},
        unresolved,
        invalid,
    )
    for path in (
        "confounding_and_sensitivity.adjustment.status",
        "confounding_and_sensitivity.sensitivity.status",
        "confounding_and_sensitivity.subgroup.status",
        "evaluation_separation.tuning.status",
    ):
        _check_choice(plan, path, {"PLANNED", "NOT_PLANNED"}, unresolved, invalid)

    if _get(plan, "confounding_and_sensitivity.confounder_review_status") == "CANDIDATES_SPECIFIED":
        if not _nonempty_list(_get(plan, "confounding_and_sensitivity.candidate_confounders")):
            unresolved.append("confounding_and_sensitivity.candidate_confounders")
    elif (
        _get(plan, "confounding_and_sensitivity.confounder_review_status") == "REVIEWED_NONE"
        and _get(plan, "confounding_and_sensitivity.candidate_confounders") != []
    ):
        invalid.append("candidate_confounders must be empty when REVIEWED_NONE")

    _planned_or_reasoned(
        plan,
        "uncertainty_and_inference.confidence_interval",
        ("confidence_level", "method", "planned_resampling_replicates", "random_seed_policy"),
        unresolved,
    )
    _planned_or_reasoned(
        plan, "uncertainty_and_inference.p_value", ("method",), unresolved
    )
    _planned_or_reasoned(
        plan, "uncertainty_and_inference.multiple_comparison",
        ("hypothesis_family_id", "method", "family_definition"), unresolved,
        planned_status="ADJUST", not_planned_status="NOT_APPLICABLE",
    )
    for base in (
        "confounding_and_sensitivity.adjustment",
        "confounding_and_sensitivity.sensitivity",
        "confounding_and_sensitivity.subgroup",
        "evaluation_separation.tuning",
    ):
        if _get(plan, f"{base}.status") == "PLANNED":
            required = ("method",) if base.endswith("adjustment") else (
                ("policy",) if base.endswith("tuning") else ("analyses",)
            )
            for field in required:
                value = _get(plan, f"{base}.{field}")
                if field == "analyses":
                    if not _nonempty_list(value):
                        unresolved.append(f"{base}.{field}")
                elif not _text_present(value):
                    unresolved.append(f"{base}.{field}")
        elif _get(plan, f"{base}.status") == "NOT_PLANNED":
            if not _text_present(_get(plan, f"{base}.rationale")):
                unresolved.append(f"{base}.rationale")

    if _get(plan, "evaluation_separation.held_out_data_may_influence_feature_or_model_selection") is not False:
        invalid.append(
            "evaluation_separation.held_out_data_may_influence_feature_or_model_selection must be false"
        )
    maximum_error = _get(plan, "data_and_sync_gates.maximum_sync_error_s")
    if (
        not isinstance(maximum_error, (int, float))
        or isinstance(maximum_error, bool)
        or not math.isfinite(float(maximum_error))
        or float(maximum_error) <= 0
    ):
        unresolved.append("data_and_sync_gates.maximum_sync_error_s")

    status = _get(plan, "study.status")
    if not isinstance(status, str) or status not in {"DRAFT", "APPROVED", "SUPERSEDED"}:
        unresolved.append("study.status")
    if status == "SUPERSEDED":
        invalid.append("superseded plans cannot be used as the current declaration")
    if status == "APPROVED":
        if not _text_present(_get(plan, "study.approved_by")):
            unresolved.append("study.approved_by")
        approved_at = _get(plan, "study.approved_at")
        if approved_at is None:
            unresolved.append("study.approved_at")
        elif not _is_offset_datetime(approved_at):
            invalid.append("study.approved_at must be an ISO-8601 datetime with UTC offset")
    authored_at = _get(plan, "study.authored_at")
    if authored_at is None:
        unresolved.append("study.authored_at")
    elif not _is_offset_datetime(authored_at):
        invalid.append("study.authored_at must be an ISO-8601 datetime with UTC offset")
    inference_flag = _get(plan, "uncertainty_and_inference.confirmatory_inference_allowed")
    if not isinstance(inference_flag, bool):
        unresolved.append("uncertainty_and_inference.confirmatory_inference_allowed")
    model_evaluation = _get(plan, "evaluation_separation.model_evaluation_in_scope")
    if not isinstance(model_evaluation, bool):
        unresolved.append("evaluation_separation.model_evaluation_in_scope")


def _check_choice(
    plan: dict[str, Any],
    path: str,
    allowed: set[str],
    unresolved: list[str],
    invalid: list[str],
) -> None:
    value = _get(plan, path)
    if value is None or value == "UNDECIDED":
        unresolved.append(path)
    elif not isinstance(value, str) or value not in allowed:
        invalid.append(f"{path} has unsupported choice {value!r}")


def _planned_or_reasoned(
    plan: dict[str, Any],
    base: str,
    planned_fields: tuple[str, ...],
    unresolved: list[str],
    *,
    planned_status: str = "PLANNED",
    not_planned_status: str = "NOT_PLANNED",
) -> None:
    status = _get(plan, f"{base}.status")
    if status == planned_status:
        for field in planned_fields:
            value = _get(plan, f"{base}.{field}")
            value_path = f"{base}.{field}"
            if field == "confidence_level":
                complete = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and 0 < float(value) < 1
                )
            elif field == "planned_resampling_replicates":
                complete = isinstance(value, int) and not isinstance(value, bool) and value > 0
            else:
                complete = _text_present(value)
            if not complete:
                unresolved.append(value_path)
    elif status == not_planned_status and not _text_present(
        _get(plan, f"{base}.rationale")
    ):
        unresolved.append(f"{base}.rationale")


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _is_offset_datetime(value: Any) -> bool:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return False
    else:
        return False
    return parsed.utcoffset() is not None


def assess_analysis_plan(plan_path: str | Path) -> dict[str, Any]:
    """Read a plan and report unresolved decisions without enabling inference."""
    path = Path(plan_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AnalysisPlanPreflightError("analysis plan is missing or unreadable") from exc
    try:
        plan = yaml.load(raw, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise AnalysisPlanPreflightError(
            "analysis plan is invalid YAML or contains duplicate mapping keys"
        ) from exc
    if not isinstance(plan, dict):
        raise AnalysisPlanPreflightError("analysis plan root must be a mapping")
    if plan.get("schema_version") != ANALYSIS_PLAN_VERSION:
        raise AnalysisPlanPreflightError(f"schema_version must be {ANALYSIS_PLAN_VERSION}")
    unexpected = sorted(set(plan) - _TOP_LEVEL_FIELDS)
    if unexpected:
        raise AnalysisPlanPreflightError(
            f"unexpected top-level fields: {', '.join(unexpected)}"
        )

    unresolved: list[str] = []
    invalid: list[str] = []
    _decision_complete(plan, unresolved, invalid)
    if invalid:
        raise AnalysisPlanPreflightError("; ".join(sorted(set(invalid))))
    unresolved_fields = sorted(set(unresolved))
    study_status = _get(plan, "study.status")
    if unresolved_fields:
        status = "INCOMPLETE"
    elif study_status == "DRAFT":
        status = "DRAFT_COMPLETE_REQUIRES_APPROVAL"
    else:
        status = "DECLARATION_COMPLETE_REQUIRES_EVIDENCE_REVIEW"
    requested_confirmatory = (
        _get(plan, "uncertainty_and_inference.confirmatory_inference_allowed") is True
    )
    approval_declared = study_status == "APPROVED"
    return {
        "status": status,
        "schema_version": ANALYSIS_PLAN_VERSION,
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "study_id": _get(plan, "study.study_id"),
        "eligible_batteries_and_experiments": _get(
            plan, "primary_analysis.eligible_batteries_and_experiments"
        ),
        "study_status": study_status,
        "approval_identity_status": (
            "SELF_DECLARED_NOT_AUTHENTICATED" if approval_declared else "NOT_APPLICABLE"
        ),
        "approval_evidence_status": "NOT_VERIFIED" if approval_declared else "NOT_APPLICABLE",
        "claim_scope": _get(plan, "research_question.intended_claim_scope"),
        "unresolved_fields": unresolved_fields,
        "requested_confirmatory_inference": requested_confirmatory,
        "confirmatory_inference_enabled": False,
        "scientific_validity": "NOT_ASSESSED",
        "data_readiness": "NOT_ASSESSED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only analysis-plan declaration preflight; does not assess science "
            "or enable confirmatory inference."
        )
    )
    parser.add_argument("analysis_plan", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess_analysis_plan(args.analysis_plan)
    except AnalysisPlanPreflightError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

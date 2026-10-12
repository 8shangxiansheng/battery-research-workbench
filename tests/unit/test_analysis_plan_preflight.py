from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from battery_workbench.analysis.plan_preflight import (
    AnalysisPlanPreflightError,
    assess_analysis_plan,
    main,
)

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "analysis-plan.yaml"
)


def _complete_plan() -> dict:
    plan = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    plan["study"].update(
        {
            "study_id": "SYNTHETIC_STUDY",
            "title": "Synthetic declaration-completeness fixture",
            "version": "1.0",
            "authored_at": "2026-01-01T00:00:00+00:00",
        }
    )
    plan["research_question"].update(
        {
            "question": "Does the synthetic feature associate with the synthetic target?",
            "intended_claim_scope": "EXPLORATORY",
            "target_population": "Synthetic batteries only",
        }
    )
    plan["primary_analysis"].update(
        {
            "endpoint": {
                "target_id": "synthetic_target",
                "operational_definition": "Synthetic target definition",
                "unit": "unit",
                "source_and_method_version": "synthetic-source/1",
                "observation_grain": "MEASUREMENT_EVENT",
                "uncertainty_source": "Synthetic fixture; not a measurement claim",
            },
            "feature": {
                "feature_id": "synthetic_feature",
                "gate_id": None,
                "feature_variant": "RAW",
                "operational_definition_and_version": "Synthetic feature/1",
                "unit": "unit",
            },
            "relationship": {
                "estimand": "Exploratory Pearson association",
                "method": "PEARSON",
                "scope": "OVERALL",
                "directionality": "TWO_SIDED",
            },
            "eligible_batteries_and_experiments": [
                {"battery_id": "SYNTHETIC_BATTERY", "experiment_id": "SYNTHETIC_EXPERIMENT"}
            ],
            "inclusion_rule_ids": ["INCLUDE_SYNTHETIC"],
            "exclusion_rule_ids": ["EXCLUDE_SYNTHETIC"],
        }
    )
    plan["repeated_measurement_structure"].update(
        {
            "review_status": "REVIEWED",
            "hierarchy": ["Battery", "Experiment", "Cycle", "MeasurementEvent"],
            "within_battery_dependence_handling": "Descriptive; no event-level inference",
            "between_battery_estimand": "Not estimated in this synthetic exploratory plan",
            "aggregation_or_weighting": "Equal weight per Battery for group summaries",
        }
    )
    plan["uncertainty_and_inference"].update(
        {
            "resampling_method": "NOT_PLANNED_EXPLORATORY",
            "confidence_interval": {
                "status": "NOT_PLANNED",
                "confidence_level": None,
                "method": None,
                "planned_resampling_replicates": None,
                "random_seed_policy": None,
                "rationale": "Exploratory contract fixture; no interval claim.",
            },
            "p_value": {
                "status": "NOT_PLANNED",
                "method": None,
                "rationale": "Exploratory contract fixture; no p-value claim.",
            },
            "multiple_comparison": {
                "status": "NOT_APPLICABLE",
                "hypothesis_family_id": None,
                "method": None,
                "family_definition": None,
                "rationale": "One synthetic primary feature only.",
            },
            "confirmatory_inference_allowed": False,
        }
    )
    plan["confounding_and_sensitivity"].update(
        {
            "confounder_review_status": "REVIEWED_NONE",
            "candidate_confounders": [],
            "adjustment": {
                "status": "NOT_PLANNED",
                "method": None,
                "rationale": "Exploratory synthetic fixture.",
            },
            "sensitivity": {
                "status": "NOT_PLANNED",
                "analyses": [],
                "rationale": "Exploratory synthetic fixture.",
            },
            "subgroup": {
                "status": "NOT_PLANNED",
                "analyses": [],
                "rationale": "Exploratory synthetic fixture.",
            },
        }
    )
    plan["data_and_sync_gates"].update(
        {
            "accepted_target_semantics": "SYNTHETIC_ONLY",
            "required_target_provenance": ["synthetic-source/1"],
            "required_feature_provenance": ["synthetic-feature/1"],
            "minimum_sync_status": "PROVISIONAL",
            "maximum_sync_error_s": 0.1,
            "ambiguity_policy": "Exclude ambiguous matches",
            "missing_data_policy": "Report missingness; no imputation",
            "protocol_deviation_policy": "Record and exclude per declared rules",
        }
    )
    plan["evaluation_separation"].update(
        {
            "model_evaluation_in_scope": False,
            "held_out_unit": "BATTERY",
            "held_out_data_may_influence_feature_or_model_selection": False,
            "tuning": {
                "status": "NOT_PLANNED",
                "policy": None,
                "rationale": "No model evaluation in this synthetic plan.",
            },
        }
    )
    return plan


def test_blank_template_reports_unresolved_decisions_and_never_enables_inference() -> None:
    original = TEMPLATE.read_bytes()

    result = assess_analysis_plan(TEMPLATE)

    assert result["status"] == "INCOMPLETE"
    assert "research_question.intended_claim_scope" in result["unresolved_fields"]
    assert result["confirmatory_inference_enabled"] is False
    assert result["scientific_validity"] == "NOT_ASSESSED"
    assert TEMPLATE.read_bytes() == original


def test_complete_draft_only_becomes_ready_for_human_approval(tmp_path: Path) -> None:
    plan = _complete_plan()
    path = tmp_path / "analysis-plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "DRAFT_COMPLETE_REQUIRES_APPROVAL"
    assert result["unresolved_fields"] == []
    assert result["confirmatory_inference_enabled"] is False
    assert result["data_readiness"] == "NOT_ASSESSED"


def test_confirmatory_claim_cannot_bypass_approval_or_data_assessment(tmp_path: Path) -> None:
    plan = _complete_plan()
    plan["research_question"]["intended_claim_scope"] = "CONFIRMATORY"
    plan["uncertainty_and_inference"]["confirmatory_inference_allowed"] = True
    path = tmp_path / "analysis-plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "DRAFT_COMPLETE_REQUIRES_APPROVAL"
    assert result["confirmatory_inference_enabled"] is False
    assert result["requested_confirmatory_inference"] is True
    assert result["data_readiness"] == "NOT_ASSESSED"


def test_invalid_yaml_and_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: v1\nschema_version: v2\n", encoding="utf-8")

    try:
        assess_analysis_plan(path)
    except AnalysisPlanPreflightError as exc:
        assert "duplicate" in str(exc).lower()
    else:
        raise AssertionError("duplicate YAML keys must be rejected")


def test_malformed_choice_types_are_reported_as_incomplete_or_invalid(tmp_path: Path) -> None:
    plan = _complete_plan()
    plan["research_question"]["intended_claim_scope"] = {"typo": "EXPLORATORY"}
    path = tmp_path / "malformed-choice.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "INCOMPLETE"
    assert "research_question.intended_claim_scope" in result["unresolved_fields"]


def test_planned_interval_requires_method_replicates_and_seed_policy(tmp_path: Path) -> None:
    plan = _complete_plan()
    plan["uncertainty_and_inference"]["confidence_interval"].update(
        {"status": "PLANNED", "confidence_level": 0.95, "planned_resampling_replicates": 1000}
    )
    path = tmp_path / "missing-interval-method.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "INCOMPLETE"
    assert "uncertainty_and_inference.confidence_interval.method" in result[
        "unresolved_fields"
    ]


def test_planned_method_must_be_text_and_eligible_pair_must_have_both_ids(
    tmp_path: Path,
) -> None:
    plan = _complete_plan()
    plan["uncertainty_and_inference"]["confidence_interval"].update(
        {
            "status": "PLANNED",
            "confidence_level": 0.95,
            "method": ["BATTERY_BOOTSTRAP"],
            "planned_resampling_replicates": 1000,
            "random_seed_policy": "Fixed and recorded",
        }
    )
    plan["primary_analysis"]["eligible_batteries_and_experiments"] = [
        {"battery_id": "SYNTHETIC_BATTERY", "experiment_id": " "}
    ]
    path = tmp_path / "malformed-declarations.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "INCOMPLETE"
    assert "uncertainty_and_inference.confidence_interval.method" in result[
        "unresolved_fields"
    ]
    assert "primary_analysis.eligible_batteries_and_experiments" in result[
        "unresolved_fields"
    ]


def test_cli_emits_json_without_claiming_readiness(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    path = tmp_path / "complete-plan.yaml"
    path.write_text(yaml.safe_dump(_complete_plan(), sort_keys=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["analysis-plan-preflight", str(path)])

    assert main() == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["status"] == "DRAFT_COMPLETE_REQUIRES_APPROVAL"
    assert result["confirmatory_inference_enabled"] is False


def test_approved_plan_keeps_execution_disabled(tmp_path: Path) -> None:
    plan = _complete_plan()
    plan["study"].update(
        {"status": "APPROVED", "approved_at": "2026-01-02T00:00:00+00:00", "approved_by": "PI"}
    )
    path = tmp_path / "analysis-plan.yaml"
    path.write_text(yaml.safe_dump(deepcopy(plan), sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "DECLARATION_COMPLETE_REQUIRES_EVIDENCE_REVIEW"
    assert result["confirmatory_inference_enabled"] is False
    assert result["scientific_validity"] == "NOT_ASSESSED"
    assert result["approval_identity_status"] == "SELF_DECLARED_NOT_AUTHENTICATED"
    assert result["approval_evidence_status"] == "NOT_VERIFIED"


def test_approved_plan_without_approval_metadata_remains_incomplete(tmp_path: Path) -> None:
    plan = _complete_plan()
    plan["study"]["status"] = "APPROVED"
    path = tmp_path / "unapproved-metadata.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = assess_analysis_plan(path)

    assert result["status"] == "INCOMPLETE"
    assert "study.approved_at" in result["unresolved_fields"]
    assert "study.approved_by" in result["unresolved_fields"]

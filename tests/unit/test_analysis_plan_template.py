from __future__ import annotations

from pathlib import Path

import yaml

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "analysis-plan.yaml"
)


def _load_template() -> dict:
    with TEMPLATE.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    assert isinstance(payload, dict)
    return payload


def test_analysis_plan_template_keeps_unselected_scientific_choices_undecided() -> None:
    plan = _load_template()

    assert plan["schema_version"] == "brw-analysis-plan-template/1.1"
    assert plan["research_question"]["intended_claim_scope"] is None
    assert plan["repeated_measurement_structure"]["review_status"] == "UNDECIDED"
    assert plan["uncertainty_and_inference"]["resampling_unit"] == "BATTERY"
    assert plan["uncertainty_and_inference"]["confidence_interval"]["status"] == "UNDECIDED"
    assert plan["uncertainty_and_inference"]["p_value"]["status"] == "UNDECIDED"
    assert plan["uncertainty_and_inference"]["multiple_comparison"]["status"] == "UNDECIDED"
    assert plan["confounding_and_sensitivity"]["confounder_review_status"] == "UNDECIDED"
    assert plan["confounding_and_sensitivity"]["sensitivity"]["status"] == "UNDECIDED"
    assert plan["confounding_and_sensitivity"]["subgroup"]["status"] == "UNDECIDED"
    assert plan["evaluation_separation"]["tuning"]["status"] == "UNDECIDED"


def test_analysis_plan_has_rationale_slots_for_explicit_nonplanning_decisions() -> None:
    plan = _load_template()
    inference = plan["uncertainty_and_inference"]
    multiple_comparison = inference["multiple_comparison"]
    sensitivity = plan["confounding_and_sensitivity"]["sensitivity"]

    assert inference["p_value"]["status"] == "UNDECIDED"
    assert inference["p_value"]["rationale"] is None
    assert multiple_comparison["status"] == "UNDECIDED"
    assert multiple_comparison["rationale"] is None
    assert sensitivity["status"] == "UNDECIDED"
    assert sensitivity["rationale"] is None

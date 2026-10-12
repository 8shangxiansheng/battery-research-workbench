from __future__ import annotations

from pathlib import Path

import yaml

from battery_workbench.analysis.plan_registry import resolve_experiment_analysis_plan

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "analysis-plan.yaml"
)


def _write_plan(data_root: Path, study_id: str, battery_id: str, experiment_id: str) -> Path:
    plan = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    plan["study"].update({"study_id": study_id, "title": f"Plan {study_id}"})
    plan["primary_analysis"]["eligible_batteries_and_experiments"] = [
        {"battery_id": battery_id, "experiment_id": experiment_id}
    ]
    directory = data_root / "annotations" / "studies" / study_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "analysis-plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return path


def test_missing_plan_is_explicitly_not_registered(tmp_path: Path) -> None:
    result = resolve_experiment_analysis_plan(
        tmp_path / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "NOT_REGISTERED"
    assert result["matching_study_ids"] == []
    assert result["confirmatory_inference_enabled"] is False
    assert result["scientific_validity"] == "NOT_ASSESSED"
    assert result["data_readiness"] == "NOT_ASSESSED"


def test_exact_pair_matches_but_incomplete_plan_stays_incomplete(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_plan(data_root, "STUDY_A", "CELL_A", "EXP_1")

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "INCOMPLETE"
    assert result["study_id"] == "STUDY_A"
    assert result["matching_study_ids"] == ["STUDY_A"]
    assert result["plan_sha256"]
    assert result["confirmatory_inference_enabled"] is False
    assert result["approval_identity_status"] == "NOT_APPLICABLE"


def test_approved_plan_reports_self_declared_unverified_approval(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    path = _write_plan(data_root, "STUDY_A", "CELL_A", "EXP_1")
    plan = yaml.safe_load(path.read_text(encoding="utf-8"))
    plan["study"].update({
        "status": "APPROVED",
        "approved_at": "2026-01-02T00:00:00+00:00",
        "approved_by": "PI",
    })
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["study_status"] == "APPROVED"
    assert result["approval_identity_status"] == "SELF_DECLARED_NOT_AUTHENTICATED"
    assert result["approval_evidence_status"] == "NOT_VERIFIED"
    assert result["confirmatory_inference_enabled"] is False


def test_plan_for_other_pair_is_not_applied_to_current_experiment(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_plan(data_root, "STUDY_A", "CELL_B", "EXP_2")

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "NOT_REGISTERED"
    assert result["matching_study_ids"] == []


def test_multiple_matching_studies_are_never_implicitly_selected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_plan(data_root, "STUDY_A", "CELL_A", "EXP_1")
    _write_plan(data_root, "STUDY_B", "CELL_A", "EXP_1")

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "AMBIGUOUS"
    assert result["study_id"] is None
    assert result["matching_study_ids"] == ["STUDY_A", "STUDY_B"]
    assert result["confirmatory_inference_enabled"] is False


def test_invalid_plan_file_prevents_false_not_registered_claim(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    directory = data_root / "annotations" / "studies" / "STUDY_BROKEN"
    directory.mkdir(parents=True)
    (directory / "analysis-plan.yaml").write_text("schema_version: wrong\n", encoding="utf-8")

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "UNRESOLVED_INVALID_PLAN_FILES"
    assert result["invalid_plan_file_count"] == 1
    assert result["confirmatory_inference_enabled"] is False


def test_plan_symlink_cannot_escape_study_annotation_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    studies = data_root / "annotations" / "studies"
    study = studies / "STUDY_LINK"
    study.mkdir(parents=True)
    external_plan = tmp_path / "external-analysis-plan.yaml"
    external_plan.write_text("schema_version: invalid\n", encoding="utf-8")
    (study / "analysis-plan.yaml").symlink_to(external_plan)

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "UNRESOLVED_INVALID_PLAN_FILES"
    assert result["invalid_plan_file_count"] == 1
    assert result["confirmatory_inference_enabled"] is False


def test_studies_root_symlink_cannot_escape_annotations_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    annotations = data_root / "annotations"
    annotations.mkdir(parents=True)
    external_data_root = tmp_path / "external-data"
    _write_plan(external_data_root, "STUDY_EXTERNAL", "CELL_A", "EXP_1")
    external_studies = external_data_root / "annotations" / "studies"
    (annotations / "studies").symlink_to(external_studies, target_is_directory=True)

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "UNRESOLVED_INVALID_PLAN_FILES"
    assert result["invalid_plan_file_count"] == 1
    assert result["matching_study_ids"] == []
    assert result["confirmatory_inference_enabled"] is False


def test_broken_study_symlink_is_not_reported_as_unregistered(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    studies = data_root / "annotations" / "studies"
    studies.mkdir(parents=True)
    (studies / "STUDY_BROKEN").symlink_to(tmp_path / "missing-study", target_is_directory=True)

    result = resolve_experiment_analysis_plan(
        data_root / "raw", battery_id="CELL_A", experiment_id="EXP_1"
    )

    assert result["status"] == "UNRESOLVED_INVALID_PLAN_FILES"
    assert result["invalid_plan_file_count"] == 1
    assert result["confirmatory_inference_enabled"] is False

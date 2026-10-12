from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "analysis-plan.yaml"
)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            raw_root=tmp_path / "data" / "raw",
            processed_root=tmp_path / "data" / "processed",
            runs_root=tmp_path / "runs",
        )
    )


def _write_plan(tmp_path: Path, study_id: str, battery_id: str, experiment_id: str) -> None:
    payload = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    payload["study"].update({"study_id": study_id, "title": study_id})
    payload["primary_analysis"]["eligible_batteries_and_experiments"] = [
        {"battery_id": battery_id, "experiment_id": experiment_id}
    ]
    plan_dir = tmp_path / "data" / "annotations" / "studies" / study_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "analysis-plan.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def test_status_endpoint_reports_unregistered_and_never_enables_inference(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path).get(
        "/api/v1/experiments/CELL_A/EXP_1/analysis-plan-status"
    )

    assert response.status_code == 200
    assessment = response.json()["data"]
    assert assessment["status"] == "NOT_REGISTERED"
    assert assessment["confirmatory_inference_enabled"] is False
    assert assessment["scientific_validity"] == "NOT_ASSESSED"
    assert response.json()["meta"]["read_only"] is True


def test_status_endpoint_matches_only_declared_pair_and_surfaces_incomplete_plan(
    tmp_path: Path,
) -> None:
    _write_plan(tmp_path, "STUDY_A", "CELL_A", "EXP_1")
    client = _client(tmp_path)

    matched = client.get("/api/v1/experiments/CELL_A/EXP_1/analysis-plan-status")
    wrong_pair = client.get("/api/v1/experiments/CELL_B/EXP_1/analysis-plan-status")

    assert matched.status_code == 200
    assert matched.json()["data"]["status"] == "INCOMPLETE"
    assert matched.json()["data"]["study_id"] == "STUDY_A"
    assert matched.json()["data"]["confirmatory_inference_enabled"] is False
    assert wrong_pair.json()["data"]["status"] == "NOT_REGISTERED"


def test_status_endpoint_reports_ambiguous_matching_plans(tmp_path: Path) -> None:
    _write_plan(tmp_path, "STUDY_A", "CELL_A", "EXP_1")
    _write_plan(tmp_path, "STUDY_B", "CELL_A", "EXP_1")

    response = _client(tmp_path).get(
        "/api/v1/experiments/CELL_A/EXP_1/analysis-plan-status"
    )

    assert response.json()["data"]["status"] == "AMBIGUOUS"
    assert response.json()["data"]["matching_study_ids"] == ["STUDY_A", "STUDY_B"]
    assert response.json()["data"]["confirmatory_inference_enabled"] is False

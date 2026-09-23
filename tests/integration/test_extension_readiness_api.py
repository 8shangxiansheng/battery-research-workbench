from pathlib import Path

from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]


def test_extension_readiness_is_read_only_and_honest(tmp_path: Path) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    response = client.get("/api/v1/experiments/CELL_001/EXP_001/extension-readiness")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["battery_id"] == "CELL_001"
    assert data["future_contracts"]["cohort_dataset"]["enabled"] is False
    assert data["future_contracts"]["tuning_study"]["enabled"] is False
    assert all("requirements" in boundary for boundary in data["boundaries"])


def test_future_write_endpoints_are_not_published(tmp_path: Path) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=tmp_path / "runs",
    )
    paths = app.openapi()["paths"]
    assert "/api/v1/tuning-studies" not in paths
    assert "/api/v1/cohort-datasets" not in paths
    assert "/api/v1/timebase-validations" not in paths


def test_extension_readiness_has_a_typed_openapi_response(tmp_path: Path) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=tmp_path / "runs",
    )
    operation = app.openapi()["paths"][
        "/api/v1/experiments/{battery_id}/{experiment_id}/extension-readiness"
    ]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ExtensionReadinessEnvelope")

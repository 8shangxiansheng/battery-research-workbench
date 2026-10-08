from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]


def test_extension_readiness_is_read_only_and_honest(tmp_path: Path, monkeypatch) -> None:
    from battery_workbench.api.routes import extensions

    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    service = SimpleNamespace(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        get_results=lambda *args, **kwargs: [],
    )
    (tmp_path / "raw/manifests").mkdir(parents=True)
    (tmp_path / "raw/manifests/batteries.csv").write_text("battery_id\nCELL_001\n")
    monkeypatch.setattr(extensions, "get_service", lambda request: service)
    monkeypatch.setattr(
        extensions,
        "list_targets",
        lambda *args: {
            "data": {
                "targets": [
                    {"target_id": "soh_capacity_reference_percent", "coverage": {"independent_states": 2}},
                    {"target_id": "temperature_c", "coverage": {"valid": 0}, "range": None},
                ]
            }
        },
    )
    monkeypatch.setattr(
        extensions,
        "alignment_summary",
        lambda *args: {"data": {"sync_quality": {"timebase_status": "PROVISIONAL"}}},
    )
    monkeypatch.setattr(
        extensions,
        "load_batteries",
        lambda path: [SimpleNamespace(battery_id="CELL_001")],
    )
    client = TestClient(app)
    response = client.get("/api/v1/experiments/CELL_001/EXP_001/extension-readiness")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["battery_id"] == "CELL_001"
    assert data["future_contracts"]["cohort_dataset"]["enabled"] is True
    assert data["future_contracts"]["tuning_study"]["enabled"] is False
    assert data["observed"]["has_independent_validation"] is False
    assert data["observed"]["independent_validation_evidence"]["available"] is False
    assert all("requirements" in boundary for boundary in data["boundaries"])


def test_only_cohort_dataset_endpoint_is_published_from_future_contracts(tmp_path: Path) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=tmp_path / "runs",
    )
    paths = app.openapi()["paths"]
    assert "/api/v1/tuning-studies" not in paths
    assert "/api/v1/cohort-datasets" in paths
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

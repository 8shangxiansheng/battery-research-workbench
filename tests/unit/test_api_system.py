"""BRW-024 T01-T12: API v1 system, experiments, health, capabilities, summary."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

has_real = (PROCESSED / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e").exists()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED)
    return TestClient(app)


def test_t01_api_v1(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_t02_openapi_builds(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["openapi"].startswith("3.")


def test_t03_health(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    data = resp.json()
    assert data["data"]["status"] == "ok"


def test_t04_capabilities(client: TestClient) -> None:
    resp = client.get("/api/v1/capabilities")
    data = resp.json()
    assert "software_capabilities" in data["data"]
    caps = data["data"]["software_capabilities"]
    assert len(caps) > 0


def test_t05_workspace_summary(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/workspace-summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "limitations" in data
    assert "readiness" in data


def test_t06_status_consistency(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    r1 = client.get("/api/v1/experiments/CELL_001/EXP_001/status")
    r2 = client.get("/api/v1/experiments/CELL_001/EXP_001/status")
    assert r1.json()["data"] == r2.json()["data"]


def test_list_experiments(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments")
    assert resp.status_code == 200
    assert "data" in resp.json()


def test_get_experiment(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001")
    assert resp.status_code == 200
    assert resp.json()["data"]["battery_id"] == "CELL_001"


def test_experiment_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/NOPE/NOPE")
    assert resp.status_code == 404


def test_results(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/results")
    assert resp.status_code == 200
    data = resp.json()["data"]
    items = data if isinstance(data, list) else data.get("results", [])
    assert len(items) > 0


def test_limitations(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/limitations")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["limitations"]) >= 11


def test_evidence(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/evidence")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["evidence"]) > 0


def test_lineage(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/lineage")
    assert resp.status_code == 200
    assert "lineage_chain" in resp.json()["data"]


def test_response_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    body = resp.json()
    assert "data" in body
    assert "error" not in body or body["error"] is None

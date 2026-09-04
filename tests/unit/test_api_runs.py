"""BRW-024 T07-T14: run API, user actions, idempotency, errors."""

from __future__ import annotations

import json
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
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


def test_t07_plan(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/runs/plan",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["plan_id"].startswith("PLAN::")


def test_t08_dry_run(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/runs/dry-run",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    assert resp.status_code == 200
    assert "nodes" in resp.json()["data"]


def test_t09_start(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["run_id"].startswith("RUN::")


def test_t09b_idempotent_start(client: TestClient) -> None:
    body = {
        "profile": "INGEST_TO_MEASUREMENT_EVENTS",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
    }
    headers = {"Idempotency-Key": "test-key-123"}
    r1 = client.post("/api/v1/runs", json=body, headers=headers)
    r2 = client.post("/api/v1/runs", json=body, headers=headers)
    assert r1.status_code == r2.status_code
    assert r1.json()["data"]["run_id"] == r2.json()["data"]["run_id"]


def test_t09c_idempotency_conflict(client: TestClient) -> None:
    headers = {"Idempotency-Key": "conflict-key"}
    client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
        headers=headers,
    )
    r2 = client.post(
        "/api/v1/runs",
        json={
            "profile": "SCIENTIFIC_ANALYSIS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
        headers=headers,
    )
    assert r2.status_code == 409


def test_t10_get_run(client: TestClient) -> None:
    r = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    run_id = r.json()["data"]["run_id"]
    resp = client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] in {"SUCCEEDED", "FAILED", "WAITING_FOR_USER", "PARTIAL"}


def test_t11_events(client: TestClient) -> None:
    r = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    run_id = r.json()["data"]["run_id"]
    resp = client.get(f"/api/v1/runs/{run_id}/events")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["events"], list)


def test_run_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/runs/RUN::nonexistent")
    assert resp.status_code == 404


def test_validation_error(client: TestClient) -> None:
    resp = client.post("/api/v1/runs/plan", json={"profile": 123})
    assert resp.status_code in {400, 422}


def test_t41_traversal_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/artifacts/../../etc/passwd")
    assert resp.status_code in {400, 404}


def test_t44_invalid_id_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/runs/invalid id with spaces!")
    assert resp.status_code in {400, 404}


def test_error_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/runs/RUN::nonexistent")
    body = resp.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "request_id" in body["error"]


def test_no_traceback_leak(client: TestClient) -> None:
    resp = client.get("/api/v1/runs/RUN::nonexistent")
    body = resp.json()
    assert "traceback" not in json.dumps(body).lower()
    assert "Traceback" not in json.dumps(body)

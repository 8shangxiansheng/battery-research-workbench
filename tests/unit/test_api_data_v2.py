"""BRW-025R API additive tests: data-quality / synchronization / measurement-events / load-demo."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
REAL = (REPO / "data/processed/CELL_001" if (REPO / "data/processed/multimodal").exists() else None)


@pytest.fixture()
def demo_client() -> TestClient:
    app = create_app(raw_root=REPO / "data/raw", processed_root=REPO / "data/processed")
    return TestClient(app)


def test_data_quality_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/data-quality")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["electrical"]["records"] > 0
    assert data["ultrasound"]["frames"] == 3999
    # cadence reported as cadence, NOT as fs
    assert data["ultrasound"]["sampling_rate_hz"] is None
    assert data["ultrasound"]["sampling_rate_status"] == "UNKNOWN"
    assert "not a waveform sampling rate" in data["ultrasound"]["note"]


def test_synchronization_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/synchronization")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["match_state"] in ("MATCHED_UNIQUE", "AMBIGUOUS")
    assert data["validated_sync"] is False  # provisional never promoted
    assert data["timebase_status"] == "PROVISIONAL"


def test_measurement_events_paginated(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] >= 10
    assert len(body["data"]["events"]) == 10
    assert body["meta"]["next_cursor"] is not None
    page2 = demo_client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events",
        params={"limit": 10, "cursor": body["meta"]["next_cursor"]},
    )
    assert page2.status_code == 200
    assert page2.json()["data"]["events"] != body["data"]["events"]


def test_load_demo_idempotent(demo_client: TestClient) -> None:
    resp = demo_client.post("/api/v1/experiments/CELL_001/EXP_001/load-demo")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_demo"] is True
    again = demo_client.post("/api/v1/experiments/CELL_001/EXP_001/load-demo")
    assert again.status_code == 200
    assert again.json()["data"]["is_demo"] is True


def test_load_demo_not_found(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))
    resp = client.post("/api/v1/experiments/NOPE/NOPE/load-demo")
    assert resp.status_code == 404

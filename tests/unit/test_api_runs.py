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


def test_run_plan_pins_temperature_channel_as_a_scientific_choice(client: TestClient) -> None:
    common = {
        "profile": "INGEST_TO_MEASUREMENT_EVENTS",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
    }
    t1 = client.post(
        "/api/v1/runs/plan",
        json={**common, "measurement_events": {"temperature_channel_id": "T1"}},
    )
    t2 = client.post(
        "/api/v1/runs/plan",
        json={**common, "measurement_events": {"temperature_channel_id": "T2"}},
    )

    assert t1.status_code == t2.status_code == 200
    plan_t1, plan_t2 = t1.json()["data"], t2.json()["data"]
    assert plan_t1["measurement_events"]["temperature_channel_id"] == "T1"
    assert plan_t2["measurement_events"]["temperature_channel_id"] == "T2"
    assert plan_t1["plan_id"] != plan_t2["plan_id"]


def test_build_dataset_profile_preserves_user_selected_features(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/runs/plan",
        json={
            "profile": "BUILD_DATASET",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "target": "soc_reference_percent",
            "features": {"selected_features": ["SWA"]},
        },
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()["data"]
    assert plan["profile"] == "BUILD_DATASET"
    assert plan["target"] == "soc_reference_percent"
    assert plan["features"]["selected_features"] == ["SWA"]
    assert plan["stages"][-1] == "DATASET"


def test_evaluation_split_profile_is_available_and_materializes_only_dataset_and_split(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/v1/runs/plan",
        json={
            "profile": "EVALUATION_SPLIT",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "target": "soc_reference_percent",
            "features": {"selected_features": ["waveform_rms_a_u"]},
            "split": {
                "strategy": "LEAVE_ONE_GROUP_OUT",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    plan = resp.json()["data"]
    assert plan["profile"] == "EVALUATION_SPLIT"
    assert plan["stages"] == ["DATASET", "SPLIT"]
    assert plan["features"]["selected_features"] == ["waveform_rms_a_u"]
    assert plan["split"]["split_unit"] == "CYCLE"


def test_modeling_plan_preserves_fold_and_feature_analysis(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/runs/plan",
        json={
            "profile": "FULL_PRE_MODEL",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "target": "soc_reference_percent",
            "features": {"selected_features": ["SWA"]},
            "split_id": "SPLIT::s1",
            "fold_index": 1,
            "feature_analysis": {
                "analysis_mode": "TRAIN_ONLY_ML_SAFE",
                "target": "soc_reference_percent",
                "candidate_features": ["SWA"],
                "selection": {"requested": True, "mode": "TRAIN_ONLY_RULE_BASED"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()["data"]
    assert plan["fold_index"] == 1
    assert plan["split_id"] == "SPLIT::s1"
    assert plan["feature_analysis"]["analysis_mode"] == "TRAIN_ONLY_ML_SAFE"


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


def test_temperature_dataset_dry_run_is_blocked_before_soh_family_routing(
    client: TestClient,
) -> None:
    soh_manifests = set(
        (PROCESSED / "datasets/CELL_001/EXP_001/SOH_CAPACITY").glob("*/dataset_manifest.json")
    )
    resp = client.post(
        "/api/v1/runs/dry-run",
        json={
            "profile": "BUILD_DATASET",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "target": "temperature_c",
        },
    )

    assert resp.status_code == 200, resp.text
    dataset_node = next(
        node for node in resp.json()["data"]["nodes"] if node["node_id"] == "DATASET"
    )
    assert dataset_node["state"] == "BLOCKED"
    assert "BLOCKED_BY_VALIDATION" in dataset_node["reason"]
    assert (
        set((PROCESSED / "datasets/CELL_001/EXP_001/SOH_CAPACITY").glob("*/dataset_manifest.json"))
        == soh_manifests
    )


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

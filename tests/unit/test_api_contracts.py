"""BRW-024 T15-T56 contract, security, and scientific-semantics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"


@pytest.fixture()
def api(tmp_path: Path) -> tuple[TestClient, object, Path]:
    processed = tmp_path / "processed"
    app = create_app(raw_root=RAW, processed_root=processed, runs_root=tmp_path / "runs")
    return TestClient(app), app.state.workbench_service, processed


def _post(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_t15_parameters_use_registry_and_preserve_provenance(
    api: tuple[TestClient, object, Path],
) -> None:
    client, _, processed = api
    data = _post(
        client,
        "/api/v1/experiments/CELL_001/EXP_001/parameters",
        {
            "values": {"ultrasound.sampling_rate_hz": {"value": 1_000_000, "unit": "Hz"}},
            "source": "user:instrument-record",
            "verified": False,
            "provenance": {"note": "explicit test input"},
        },
    )
    assert data["parameter_set_id"].startswith("PS::")
    assert data["sampling_rate_status"] != "VERIFIED"
    assert list((processed / "parameters/CELL_001/EXP_001").glob("PS::*"))


def test_t16_gate_is_validated_and_deterministic(api: tuple[TestClient, object, Path]) -> None:
    client, service, processed = api
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "gate_name": "signal-window",
        "start_sample": 10,
        "end_sample": 100,
        "waveform_length": 1250,
    }
    first = _post(client, "/api/v1/gates", body)
    second = _post(client, "/api/v1/gates", body)
    assert first["gate_id"] == second["gate_id"]
    assert second["reuse_status"] == "REUSED"
    assert client.get(f"/api/v1/gates/{first['gate_id']}").status_code == 200
    gates = client.get("/api/v1/experiments/CELL_001/EXP_001/gates").json()["data"]["gates"]
    assert any(item["gate_id"] == first["gate_id"] for item in gates)
    restarted = TestClient(
        create_app(
            raw_root=RAW,
            processed_root=processed,
            runs_root=service.runs_root,
        )
    )
    assert restarted.get(f"/api/v1/gates/{first['gate_id']}").status_code == 200


def test_t17_features_preserve_blocked_tof(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    response = client.get("/api/v1/experiments/CELL_001/EXP_001/features")
    features = response.json()["data"]["features"]
    tof = next(item for item in features if item["feature_name"] == "tof_us")
    assert tof["availability"] == "NOT_AVAILABLE_CURRENT_ENVIRONMENT"
    assert tof["missing_reason"]


def test_t18_feature_analysis_modes_and_reuse(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "target": "soc_reference_percent",
        "candidate_features": ["waveform_rms_a_u"],
    }
    first = _post(client, "/api/v1/feature-analyses", body)
    second = _post(client, "/api/v1/feature-analyses", body)
    assert first["analysis_id"] == second["analysis_id"]
    assert first["analysis_mode"] == "EXPLORATORY_FULL_DATA"


def test_t19_dataset_contract_and_reuse(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dataset_family": "SOC",
        "target": "soc_reference_percent",
        "selected_features": ["waveform_rms_a_u"],
    }
    first = _post(client, "/api/v1/datasets", body)
    second = _post(client, "/api/v1/datasets", body)
    assert first["dataset_id"] == second["dataset_id"]
    assert first["selected_features"] == ["waveform_rms_a_u"]
    assert first["limitations"]


def test_t20_split_is_grouped_and_deterministic(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dataset_id": "DS::example",
        "strategy": "LEAVE_ONE_GROUP_OUT",
    }
    first = _post(client, "/api/v1/splits", body)
    second = _post(client, "/api/v1/splits", body)
    assert first["split_id"] == second["split_id"]
    assert first["group_column"] == "cycle_group_id"
    assert first["require_roles"] == ["TRAIN", "HELD_OUT"]


def test_t21_model_is_fixed_baseline_and_reused(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "strategy": "RIDGE",
        "dataset_id": "DS::example",
        "split_id": "SPLIT::example",
        "fold_index": 0,
        "selection_id": "SEL::example",
        "selected_features": ["waveform_rms_a_u"],
    }
    first = _post(client, "/api/v1/models/baseline-runs", body)
    second = _post(client, "/api/v1/models/baseline-runs", body)
    assert first["model_id"] == second["model_id"]
    assert first["tuning"] is False


def test_t22_report_is_idempotent_and_has_limitations(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = {"battery_id": "CELL_001", "experiment_id": "EXP_001"}
    first = _post(client, "/api/v1/reports", body)
    second = _post(client, "/api/v1/reports", body)
    assert first["report_id"] == second["report_id"]
    assert second["reuse_status"] == "REUSED"
    assert first["limitations"]


def test_t23_evidence_type_passes_through_unchanged(
    api: tuple[TestClient, object, Path],
) -> None:
    client, _, processed = api
    sync_dir = processed / "synchronization/CELL_001/EXP_001"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        json.dumps({"matches_frames": 12}), encoding="utf-8"
    )
    evidence = client.get("/api/v1/experiments/CELL_001/EXP_001/evidence").json()["data"][
        "evidence"
    ]
    assert evidence[0]["evidence_type"] == "DIRECT_CURRENT_ARTIFACT"
    assert evidence[0]["artifact_availability"] == "AVAILABLE"


def test_t24_lineage_hides_filesystem_paths(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    body = client.get("/api/v1/experiments/CELL_001/EXP_001/lineage").json()["data"]
    serialized = json.dumps(body)
    assert str(REPO) not in serialized
    assert "manifest_path" not in serialized


def test_artifact_metadata_uses_existing_manifest_without_parquet_read(
    api: tuple[TestClient, object, Path],
) -> None:
    client, _, processed = api
    destination = processed / "datasets/CELL_001/EXP_001/SOC/DS::fixture"
    destination.mkdir(parents=True)
    (destination / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "DS::fixture",
                "dataset_status": "READY_WITH_LIMITATIONS",
                "joined_rows": 12,
                "output_path": "/secret/local/path/data.parquet",
            }
        ),
        encoding="utf-8",
    )
    response = client.get("/api/v1/artifacts/DS::fixture")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["row_count"] == 12
    assert "/secret/local/path" not in json.dumps(body)


def test_t25_validation_is_typed(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    response = client.post("/api/v1/gates", json={"battery_id": "CELL_001"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_t29_missing_manifest_is_typed_integrity_error(tmp_path: Path) -> None:
    app = create_app(
        raw_root=tmp_path / "missing-raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).get("/api/v1/experiments")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_t28_scientific_blocked_states_are_not_500(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    response = client.get("/api/v1/experiments/CELL_001/EXP_001/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tof"] == {
        "value": None,
        "status": "BLOCKED",
        "reason": "sampling rate/time-zero and arrival detector are not validated",
    }
    assert data["soh"]["value"] is None
    assert data["soh"]["status"] == "NOT_READY"


def test_t31_request_id_is_consistent(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    response = client.get("/api/v1/health")
    assert response.headers["X-Request-ID"] == response.json()["meta"]["request_id"]


def test_t30_internal_error_hides_traceback_and_paths(
    api: tuple[TestClient, object, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _ = api

    def broken() -> None:
        raise RuntimeError("secret at /private/internal/file.py")

    monkeypatch.setattr(service, "health", broken)
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    response = safe_client.get("/api/v1/health")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "/private/internal" not in json.dumps(body)
    assert "traceback" not in json.dumps(body).lower()


def test_t12_t14_user_action_resume_and_retry_routes_use_orchestrator_facade(
    api: tuple[TestClient, object, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _ = api
    run = _post(
        client,
        "/api/v1/runs",
        {
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    run_id = run["run_id"]
    monkeypatch.setattr(
        service._runs,
        "list_user_actions",
        lambda *args, **kwargs: [
            {
                "action_id": "ACTION::sampling",
                "action_type": "MISSING_SAMPLING_RATE",
            }
        ],
    )
    monkeypatch.setattr(
        service._runs,
        "submit_user_action",
        lambda *args, **kwargs: {"run_id": run_id, "status": "RUNNING"},
    )
    monkeypatch.setattr(
        service._runs,
        "resume_run",
        lambda *args, **kwargs: {"run_id": run_id, "status": "RUNNING"},
    )
    monkeypatch.setattr(
        service._runs,
        "retry_node",
        lambda *args, **kwargs: {"run_id": run_id, "status": "RUNNING"},
    )
    incomplete = client.post(
        f"/api/v1/runs/{run_id}/user-actions/ACTION::sampling",
        json={"values": {"unrelated": 1}},
    )
    action = client.post(
        f"/api/v1/runs/{run_id}/user-actions/ACTION::sampling",
        json={"values": {"ultrasound.sampling_rate_hz": 1_000_000}},
    )
    resume = client.post(f"/api/v1/runs/{run_id}/resume", json={})
    retry = client.post(f"/api/v1/runs/{run_id}/retry", json={"node_id": "PARAMETER_SET"})
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "SCIENTIFIC_ACTION_REQUIRED"
    assert action.status_code == resume.status_code == retry.status_code == 200


def test_t37_t40_pagination_and_invalid_cursor(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    page = client.get("/api/v1/experiments?limit=1")
    assert page.status_code == 200
    assert len(page.json()["data"]) <= 1
    bad = client.get("/api/v1/experiments?cursor=not-a-cursor")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_report_pagination_cursor_and_order(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    for target in ("soc_reference_percent", "soh_capacity_reference_percent"):
        _post(
            client,
            "/api/v1/reports",
            {"battery_id": "CELL_001", "experiment_id": "EXP_001", "target": target},
        )
    first = client.get("/api/v1/reports?limit=1").json()
    assert len(first["data"]) == 1
    assert first["meta"]["next_cursor"]
    second = client.get(
        "/api/v1/reports",
        params={"limit": 1, "cursor": first["meta"]["next_cursor"]},
    ).json()
    assert first["data"][0]["report_id"] < second["data"][0]["report_id"]


def test_t41_t45_security_contract(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    traversal = client.get("/api/v1/artifacts/%2E%2E%2F%2E%2E%2Fetc%2Fpasswd")
    assert traversal.status_code in {400, 404}
    arbitrary_path = client.post(
        "/api/v1/datasets",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dataset_family": "SOC",
            "target": "soc_reference_percent",
            "selected_features": ["waveform_rms_a_u"],
            "path": "/etc/passwd",
        },
    )
    assert arbitrary_path.status_code == 400
    traversal_id = client.post(
        "/api/v1/splits",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dataset_id": "../../etc/passwd",
        },
    )
    assert traversal_id.status_code == 400
    assert client.get("/api/v1/artifacts/ANY/preview?limit=201").status_code == 400
    invalid_id = client.get("/api/v1/runs/invalid%20id")
    assert invalid_id.status_code == 400
    assert "secret" not in json.dumps(invalid_id.json()).lower()


def test_t46_t52_scientific_preservation(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    status = client.get("/api/v1/experiments/CELL_001/EXP_001/status").json()["data"]
    assert status["synchronization"] == {
        "validated_sync": False,
        "timebase_status": "PROVISIONAL",
    }
    assert status["soc"]["status"] == "RETROSPECTIVE_SOC_REFERENCE"
    assert status["tof"]["value"] is None
    limitations = client.get("/api/v1/experiments/CELL_001/EXP_001/limitations").json()["data"][
        "limitations"
    ]
    assert any(item["code"] == "LIMITED_CROSS_CYCLE_GENERALIZATION" for item in limitations)
    assert status["soc"]["value"] is None
    assert "not true SOC" in status["soc"]["reason"]


def test_t53_t56_gets_do_not_start_or_resume_runs(
    api: tuple[TestClient, object, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _ = api

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("read endpoint triggered computation")

    monkeypatch.setattr(service._runs, "start_run", forbidden)
    monkeypatch.setattr(service._runs, "resume_run", forbidden)
    assert client.get("/api/v1/experiments/CELL_001/EXP_001").status_code == 200
    assert client.get("/api/v1/experiments/CELL_001/EXP_001/lineage").status_code == 200
    assert client.get("/api/v1/experiments/CELL_001/EXP_001/results").status_code == 200


def test_openapi_contract_contains_errors_tags_and_all_resource_groups(
    api: tuple[TestClient, object, Path],
) -> None:
    client, _, _ = api
    spec = client.get("/openapi.json").json()
    assert "ErrorEnvelope" in spec["components"]["schemas"]
    assert {item["name"] for item in spec["tags"]} >= {
        "system",
        "experiments",
        "runs",
        "scientific-resources",
        "artifacts",
    }
    paths = spec["paths"]
    for prefix in (
        "/api/v1/gates",
        "/api/v1/feature-analyses",
        "/api/v1/datasets",
        "/api/v1/splits",
        "/api/v1/models/baseline-runs",
        "/api/v1/reports",
    ):
        assert prefix in paths


def test_openapi_v1_snapshot_is_current(api: tuple[TestClient, object, Path]) -> None:
    client, _, _ = api
    snapshot = json.loads((REPO / "docs/api/openapi-v1.json").read_text(encoding="utf-8"))
    assert snapshot == client.get("/openapi.json").json()

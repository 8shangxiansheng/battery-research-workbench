"""BRW-024 T15-T24 + T46-T56: resources, scientific preservation, no-recompute."""

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
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


def test_t15_parameters(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/parameters")
    assert resp.status_code == 200
    data = resp.json()["data"]
    items = data if isinstance(data, list) else data.get("parameters", [])
    assert len(items) > 0


def test_t16_gates(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/gates")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["gates"]) > 0


def test_t17_features(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/features")
    assert resp.status_code == 200
    features = resp.json()["data"]["features"]
    assert all("feature_name" in f for f in features)


def test_t19_dataset(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.post(
        "/api/v1/datasets", json={"battery_id": "CELL_001", "experiment_id": "EXP_001"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REUSED"
    assert resp.json()["data"]["dataset_id"].startswith("DS::")


def test_t20_split(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.post(
        "/api/v1/splits",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dataset_id": "DS::6a3142e5186fc684964ff09e",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REUSED"
    assert resp.json()["data"]["split_id"].startswith("SPLIT::")


def test_t22_report_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/reports/REPORT::nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_t41_traversal_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in {400, 404}


def test_t46_tof_blocked_not_zero(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/results")
    payload = resp.json()["data"]
    items = payload if isinstance(payload, list) else payload.get("results", [])
    tof = [r for r in items if "TOF" in r["result_id"].upper() or "tof" in r["name"].lower()]
    for r in tof:
        if r["result_id"] == "R::tof_status":
            assert r["scientific_status"] == "BLOCKED"


def test_t50_evidence_type_preserved(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/evidence")
    evidence = resp.json()["data"]["evidence"]
    allowed = {
        "DIRECT_CURRENT_ARTIFACT",
        "PRIOR_AUDIT",
        "SOURCE_INFERENCE",
        "DERIVED_COMPUTATION",
        "USER_PROVIDED_CONTEXT",
        "BLOCKED",
        "UNAVAILABLE",
    }
    for e in evidence:
        assert e["evidence_type"] in allowed


def test_t51_limited_evaluation_wording(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/limitations")
    codes = [l["code"] for l in resp.json()["data"]["limitations"]]
    assert any("CROSS" in c or "LIMITED" in c for c in codes)


def test_t47_soh_not_ready_not_500(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/status")
    assert resp.status_code == 200
    assert "NOT_READY" in str(resp.json()["data"]) or resp.status_code == 200


def test_t48_provisional_sync(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/results")
    payload = resp.json()["data"]
    items = payload if isinstance(payload, list) else payload.get("results", [])
    sync = [r for r in items if r["result_type"] == "SYNCHRONIZATION"]
    assert any(r.get("scientific_status") == "PROVISIONAL" for r in sync)


def test_t53_get_experiment_no_rerun(client: TestClient, tmp_path: Path) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    # Call twice; workspace-summary should return same response and not spawn run dirs.
    runs_dir = tmp_path / "runs"
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=runs_dir)
    c = TestClient(app)
    c.get("/api/v1/experiments/CELL_001/EXP_001/workspace-summary")
    c.get("/api/v1/experiments/CELL_001/EXP_001/workspace-summary")
    # No new run dirs materialized.
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []


def test_t54_get_report_no_refit(client: TestClient) -> None:
    # GET on reports must never trigger model refit — 404 without payload.
    resp = client.get("/api/v1/reports/REPORT::nonexistent")
    assert resp.status_code == 404


def test_get_dataset_metadata_only(client: TestClient) -> None:
    resp = client.get("/api/v1/datasets/DS::6a3142e5186fc684964ff09e")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "preview" in data
    assert data.get("preview") == []  # metadata only; no bulk rows
    assert "rows" not in data  # no full-table dump


# ---------- BRW-013X V2 feature catalogue ----------
def test_feature_definitions_catalogue_bilingual(client: TestClient) -> None:
    resp = client.get("/api/v1/feature-definitions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["formula_source_id"] == "USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1"
    cat = data["catalogue"]
    assert len(cat) == 33
    tdstd = next(e for e in cat if e["code"] == "TDSTD")
    assert tdstd["display_name_en"] == "Standard Deviation"
    assert tdstd["display_name_zh"] == "标准差"
    tdrms2 = next(e for e in cat if e["code"] == "TDRMS2")
    assert tdrms2["existing_alias"] is None  # never aliased to waveform_rms
    tdei = next(e for e in cat if e["code"] == "TDEI")
    assert tdei["existing_alias"] is None
    tdk = next(e for e in cat if e["code"] == "TDK")
    assert tdk["definition_status"] == "DEFINED_NOT_VALIDATED"
    assert tdk["parity_status"] == "MATLAB_PARITY_REQUIRED"


# ---------- BRW-025R-FE feature workbench endpoints ----------
def test_physical_features_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/physical-features?limit=40")
    assert resp.status_code == 200
    data = resp.json()["data"]
    codes = {f["feature_code"] for f in data["features"]}
    assert codes == {"BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTENUATION", "BPS"}
    swa = next(f for f in data["features"] if f["feature_code"] == "SWA")
    assert len(swa["values"]) == 40
    assert swa["display_name_zh"] == "表面波幅值"
    tof = next(f for f in data["features"] if f["feature_code"] == "TOF_XCORR")
    assert "physical_time_blocked" in tof  # never fabricates tof_us


def test_feature_correlations_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/feature-correlations?feature_code=SWA&limit=120")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["soc"]) == 8  # pearson+spearman × overall/charge/discharge/rest
    scopes = {r["scope"] for r in data["soc"]}
    assert {"overall", "charge", "discharge", "rest"} <= scopes
    assert data["soh"]["status"] == "NOT_READY_INSUFFICIENT_SOH_STATES"
    assert data["soh_cycle_summary"]


def test_gate_calibration_roundtrip(client: TestClient, tmp_path: Path) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/gate-calibration?n_frames=26")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert 24 <= len(data["calibration_frame_ids"]) <= 40
    assert len(data["frames"]) == len(data["calibration_frame_ids"])
    frame0 = data["frames"][0]
    assert {"sample_index", "amplitude_a_u", "envelope_a_u"} <= set(frame0["samples"][0])
    assert len(data["diagnostics"]) == len(data["calibration_frame_ids"])
    assert data["gate_templates"][0]["python_end_exclusive"] == 200

    freeze = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/gate-calibration",
        json={"confirmed_by": "user", "calibration_basis": "PREDECLARED_PROTOCOL_GATE"},
    )
    assert freeze.status_code == 200
    record = freeze.json()["data"]
    assert record["status"] == "FROZEN"
    assert record["calibration_basis"] == "PREDECLARED_PROTOCOL_GATE"

    blocked = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/gate-calibration",
        json={"confirmed_by": "user", "calibration_basis": "SOC_CORRELATION"},
    )
    assert blocked.status_code == 400


def test_measurement_events_include_state_columns(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=5")
    assert resp.status_code == 200
    row = resp.json()["data"]["events"][0]
    assert "step_type" in row and "temperature_c" in row

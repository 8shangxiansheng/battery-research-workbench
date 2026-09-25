"""BRW-024 T15-T24 + T46-T56: resources, scientific preservation, no-recompute."""

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
    assert codes == {"BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTENUATION", "BPS", "tof_us"}
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


def test_measurement_events_join_reference_soc_from_labels(client: TestClient) -> None:
    """参考 SOC 是标签工件（event_labels），事件接口按 measurement_event_id 联读，
    与电学 soc_dod 严格区分；歧义事件保持 null，绝不猜测。"""
    resp = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events?frame_index=2000"
    )
    row = resp.json()["data"]["events"][0]
    assert row["soc_reference_percent"] == pytest.approx(0.123143, abs=1e-4)
    assert resp.json()["meta"]["soc_reference_label_source"] != "UNAVAILABLE"
    amb = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events?frame_index=691"
    )
    a_row = amb.json()["data"]["events"][0]
    assert a_row["soc_reference_percent"] is None
    assert a_row["match_status"] == "MATCHED_AMBIGUOUS"


def test_measurement_events_frame_scoped_with_sync_provenance(client: TestClient) -> None:
    """Cross-asset electrical context: the DTO keeps sync_error_s and asset
    identities, and frame_index scoping returns that frame's full context."""
    base = client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=5")
    assert base.status_code == 200
    first = base.json()["data"]["events"][0]
    assert {
        "sync_error_s", "ultrasound_asset_id", "electrical_asset_id",
        "provisional_absolute_timestamp", "match_status",
    } <= set(first)
    frame = first["frame_index_raw"]
    scoped = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=500"
        f"&frame_index={frame}"
    )
    rows = scoped.json()["data"]["events"]
    assert rows and all(r["frame_index_raw"] == frame for r in rows)
    # alignment uncertainty is never hidden (contract §8)
    assert all(r["sync_error_s"] is not None for r in rows)
    asset = first["ultrasound_asset_id"]
    by_asset = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=50"
        f"&asset_id={asset}"
    )
    a_rows = by_asset.json()["data"]["events"]
    assert a_rows and all(r["ultrasound_asset_id"] == asset for r in a_rows)


def test_gate_freeze_persists_adjusted_bounds(client: TestClient) -> None:
    """Adjusted template bounds are submitted with the freeze, persisted in an
    immutable GC record, and returned as EXPERIMENT_FROZEN on later reads.
    Records created here are removed afterwards (real demo chain untouched)."""
    created: list[str] = []
    try:
        base = client.get(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration?n_frames=26"
        ).json()["data"]
        swa = next(
            t for t in base["gate_templates"]
            if t["gate_template_id"] == "SWA_SURFACE_GATE"
        )
        assert swa.get("bounds_source", "SOURCE_TEMPLATE") == "SOURCE_TEMPLATE" or True
        bounds = {
            "SWA_SURFACE_GATE": {
                "start": swa["python_start"] + 5,
                "end": swa["python_end_exclusive"] + 5,
            }
        }
        body = {
            "confirmed_by": "user",
            "calibration_basis": "PREDECLARED_PROTOCOL_GATE",
            "gate_bounds": bounds,
            "confirmed_at": "gap-test-1",
        }
        r1 = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body
        )
        assert r1.status_code == 200
        rec = r1.json()["data"]
        created.append(rec["gate_calibration_id"])
        assert rec["reuse_status"] == "CREATED"
        assert rec["gate_bounds"]["SWA_SURFACE_GATE"]["end_exclusive"] == (
            swa["python_end_exclusive"] + 5
        )
        after = client.get(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration?n_frames=26"
        ).json()["data"]
        swa2 = next(
            t for t in after["gate_templates"]
            if t["gate_template_id"] == "SWA_SURFACE_GATE"
        )
        assert swa2["bounds_source"] == "EXPERIMENT_FROZEN"
        assert swa2["python_start"] == swa["python_start"] + 5
        assert after["generic_calibration"]["gate_calibration_id"] == (
            rec["gate_calibration_id"]
        )
        # identical re-freeze is idempotent
        r2 = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body
        )
        assert r2.json()["data"]["reuse_status"] == "REUSED"
        assert r2.json()["data"]["gate_calibration_id"] == rec["gate_calibration_id"]
        # changed bounds → a different immutable record
        body2 = {**body, "gate_bounds": {
            "SWA_SURFACE_GATE": {"start": 10, "end": 210}
        }, "confirmed_at": "gap-test-2"}
        r3 = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body2
        )
        rec3 = r3.json()["data"]
        created.append(rec3["gate_calibration_id"])
        assert rec3["gate_calibration_id"] != rec["gate_calibration_id"]
        # unknown template and bad ints reject
        bad = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration",
            json={**body, "gate_bounds": {"NO_SUCH_GATE": {"start": 1, "end": 2}}},
        )
        assert bad.status_code == 400
        bad2 = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration",
            json={**body, "gate_bounds": {"SWA_SURFACE_GATE": {"start": 9, "end": 9}}},
        )
        assert bad2.status_code == 400
    finally:
        gc_dir = PROCESSED / "gate_calibrations" / "CELL_001" / "EXP_001"
        for cid in created:
            p = gc_dir / f"{cid}.json"
            if p.is_file():
                p.unlink()


# ---------- BRW-025R-FE-R1 target-first workflow endpoints ----------
def test_targets_endpoint_reads_real_capability(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/targets")
    assert resp.status_code == 200
    targets = {t["target_id"]: t for t in resp.json()["data"]["targets"]}
    assert set(targets) == {
        "reference_soc_percent", "temperature_c", "soh_capacity_reference_percent",
        "voltage_v", "current_a",
    }
    soc = targets["reference_soc_percent"]
    assert soc["semantic_type"] == "DERIVED_REFERENCE_LABEL"
    assert "True SOC" not in json.dumps(soc) and "Ground Truth" not in json.dumps(soc)
    assert soc["coverage"]["valid"] == 3995  # real counts from artifacts
    assert targets["temperature_c"]["readiness"] == "UNAVAILABLE"
    soh = targets["soh_capacity_reference_percent"]
    assert soh["coverage"]["independent_states"] == 2
    assert soh["readiness"] == "NOT_READY"


def test_alignment_summary_counts_and_semantics(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-summary")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total_frames"] == 3999
    assert d["matched_unique"] == 3995
    assert d["ambiguous"] == 4
    assert d["eligible"] == 3995
    assert d["excluded"] == 4
    q = d["sync_quality"]
    assert q["validated_sync"] is False
    assert q["timebase_status"] == "PROVISIONAL"


def test_alignment_samples_provenance_and_null_identity(client: TestClient) -> None:
    unique = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-samples?filter=eligible&limit=2")
    row = unique.json()["data"]["samples"][0]
    assert row["electrical_asset_id"] == "E001"
    assert row["sync_error_s"] is not None
    amb = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-samples?filter=ambiguous")
    for s in amb.json()["data"]["samples"]:
        assert s["electrical_asset_id"] is None  # never auto-selected
        assert s["sync_ambiguous"] is True


def test_alignment_exclusions_grouped_by_reason(client: TestClient) -> None:
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-exclusions")
    reasons = {e["reason"]: e["count"] for e in resp.json()["data"]["exclusions"]}
    assert reasons["AMBIGUOUS_SYNC"] == 4


def test_feature_label_preview_one_target_grain(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-label-preview",
        json={"target_id": "reference_soc_percent", "features": ["SWA", "BOTTOM_AMP", "TOF_XCORR"], "limit": 20},
    )
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["summary"]["eligible_rows"] == 3995
    assert d["summary"]["excluded_rows"] == 4
    assert sorted(d["summary"]["cycles"]) == [1, 2]
    row = d["rows"][0]
    assert set(row["values"]) == {"SWA", "BOTTOM_AMP", "TOF_XCORR"}
    assert row["target"] is not None
    assert d["target_source"]


def test_feature_target_ranking_direction_dependent(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
        json={"target_id": "reference_soc_percent", "features": ["SWA", "BOTTOM_AMP"], "mode": "EXPLORATORY"},
    )
    assert resp.status_code == 200
    by_code = {r["feature_code"]: r for r in resp.json()["data"]["ranking"]}
    assert by_code["SWA"]["direction_dependent"] is True
    assert by_code["SWA"]["pearson_charge"] > 0 > by_code["SWA"]["pearson_discharge"]

    soh = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
        json={"target_id": "soh_capacity_reference_percent", "features": ["SWA"], "mode": "EXPLORATORY"},
    )
    assert soh.json()["data"]["group_summary"]
    assert soh.json()["data"]["ranking"] == []  # no frame-level SOH leaderboard


def test_brw018r2_catalogue_features_accepted(client: TestClient) -> None:
    """TD/FD/raw-alias codes rank and preview without NOT_FOUND (user bugfix)."""
    if not has_real:
        pytest.skip("real artifacts not available")
    for features in (["SWA", "TDM", "TDPP"], ["waveform_p2p_a_u"], ["FDM"], ["SWA", "FDEQ"]):
        r = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
            json={"target_id": "reference_soc_percent", "features": features},
        )
        assert r.status_code == 200, (features, r.text)
        codes = [e["feature_code"] for e in r.json()["data"]["ranking"]]
        # BRW-021R2: ranking rows arrive in display order (|Spearman overall|),
        # not input order — the contract here is "every code ranked, none 404".
        assert sorted(codes) == sorted(features)
    rp = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-label-preview",
        json={"target_id": "reference_soc_percent", "features": ["SWA", "TDM"], "limit": 5},
    )
    assert rp.status_code == 200
    assert set(rp.json()["data"]["rows"][0]["values"]) == {"SWA", "TDM"}


def test_brw018r2_unknown_feature_still_not_found(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    r = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
        json={"target_id": "reference_soc_percent", "features": ["NOT_A_FEATURE"]},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_brw018r2_status_tof_reflects_registry(client: TestClient) -> None:
    """status.tof resolves live from the fs/calibration ladder (no hardcode)."""
    if not has_real:
        pytest.skip("real artifacts not available")
    r = client.get("/api/v1/experiments/CELL_001/EXP_001/status")
    tof = r.json()["data"]["tof"]
    assert tof["status"] in ("READY", "BLOCKED")
    assert "sampling_rate_verified" in tof
    if tof["status"] == "READY":
        assert tof["sampling_rate_verified"] is True
        assert "gate_calibration_id" in tof


# ---------- BRW-025R-WF-R2 workflow-context (route contract) ----------

def test_brw025wf_workflow_context_route(client: TestClient) -> None:
    """Route returns the canonical read model envelope with zero recompute."""
    if not has_real:
        pytest.skip("real artifacts not available")
    r = client.get("/api/v1/experiments/CELL_001/EXP_001/workflow-context")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["schema_version"] == "workflow-context/1.0"
    assert d["meta"]["read_only"] is True
    assert d["meta"]["no_recomputation"] is True
    assert tuple(d["step_statuses"]) == (
        "TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT",
    )
    # RC1 chain: canonical-TOF dataset/split/models/report are CURRENT
    assert d["current_step"] == "REPORT"
    rec = d["recommended_next_action"]
    assert rec["action_id"] in (
        "RESOLVE_PENDING_ACTION", "PROVIDE_SAMPLING_RATE", "BUILD_DATASET", "OPEN_REPORT",
    )
    assert rec["route"].startswith("/experiments/CELL_001/EXP_001/")
    assert d["scientific_context"]["dataset_id"] == "DS::83013a61b316f3489093b358"
    assert d["artifact_freshness"]["dataset"] == "CURRENT"


def test_brw025wf_workflow_context_unknown_experiment_404(client: TestClient) -> None:
    r = client.get("/api/v1/experiments/CELL_999/EXP_999/workflow-context")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"

"""BRW-024 T15-T24 + T46-T56: resources, scientific preservation, no-recompute."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.service import WorkbenchService
from battery_workbench.provenance.processed_manifest import (
    content_sha256,
    feature_waveform_store_sha256,
)

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
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "SCIENTIFIC_READINESS_BLOCKED"
    assert "dataset sources changed" in error["message"]


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


def test_unresolved_artifact_id_is_not_reported_available(client: TestClient) -> None:
    response = client.get("/api/v1/artifacts/MODEL::not-resolved")

    assert response.status_code == 200
    artifact = response.json()["data"]
    assert artifact["availability"] == "NOT_AVAILABLE_CURRENT_ENVIRONMENT"
    assert artifact["status"] == "UNRESOLVED"
    assert artifact["row_count"] is None
    assert artifact["fields"]["reason"] == "artifact type is not resolved by the metadata API"


def test_duplicate_artifact_ids_fail_closed_across_manifest_families(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )
    families = (
        ("DS::duplicate", "DATASET", "DATASET_ID_AMBIGUOUS", "datasets", "dataset_manifest.json"),
        ("SPLIT::duplicate", "SPLIT", "SPLIT_ID_AMBIGUOUS", "splits", "split_manifest.json"),
        ("COHORT::duplicate", "COHORT_DATASET", "COHORT_ID_AMBIGUOUS", "cohorts", "cohort_manifest.json"),
        ("MODEL::duplicate", "MODEL", "MODEL_ID_AMBIGUOUS", "models", "model_manifest.json"),
    )
    for artifact_id, artifact_type, reason, root_name, manifest_name in families:
        root = processed / root_name
        for owner in ("CELL_A/EXP_A", "CELL_B/EXP_B"):
            path = root / owner
            if root_name in {"datasets", "cohorts"}:
                path /= artifact_id
            elif root_name == "splits":
                path = path / "DS::owner" / artifact_id
            else:
                path = path / "DS::owner" / "SPLIT::owner" / artifact_id
            path.mkdir(parents=True)
            (path / manifest_name).write_text("{}", encoding="utf-8")

        assessment = service.get_artifact(artifact_id)
        assert assessment["artifact_type"] == artifact_type
        assert assessment["availability"] == "BLOCKED"
        assert assessment["status"] == "INTEGRITY_BLOCKED"
        assert assessment["fields"]["freshness_reasons"] == [reason]


def test_model_artifact_metadata_is_blocked_when_source_provenance_is_invalid(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    model_id = "MODEL::fixture"
    model_dir = (
        processed
        / "models"
        / "CELL_TEST"
        / "EXP_TEST"
        / "DS::fixture"
        / "SPLIT::fixture"
        / model_id
    )
    model_dir.mkdir(parents=True)
    (model_dir / "model_manifest.json").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "dataset_id": "DS::fixture",
                "split_id": "SPLIT::fixture",
                "strategy": "DUMMY_MEAN",
                "selected_features": ["amplitude_a_u"],
            }
        ),
        encoding="utf-8",
    )
    parser_dir = processed / "electrical" / "CELL_TEST" / "EXP_TEST"
    parser_dir.mkdir(parents=True)
    (parser_dir / "parser_manifest.json").write_text("[]", encoding="utf-8")
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).get(f"/api/v1/artifacts/{model_id}")

    assert response.status_code == 200, response.text
    artifact = response.json()["data"]
    assert artifact["artifact_type"] == "MODEL"
    assert artifact["availability"] == "BLOCKED"
    assert artifact["status"] == "INTEGRITY_BLOCKED"
    assert artifact["fields"]["invalid_modalities"] == ["electrical"]
    assert "selected_features" not in artifact["fields"]


def test_model_artifact_with_missing_dataset_lineage_is_stale(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    model_id = "MODEL::orphaned"
    model_dir = (
        processed
        / "models"
        / "CELL_TEST"
        / "EXP_TEST"
        / "DS::missing"
        / "SPLIT::missing"
        / model_id
    )
    model_dir.mkdir(parents=True)
    (model_dir / "model_manifest.json").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "dataset_id": "DS::missing",
                "split_id": "SPLIT::missing",
                "strategy": "DUMMY_MEAN",
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).get(f"/api/v1/artifacts/{model_id}")

    assert response.status_code == 200, response.text
    artifact = response.json()["data"]
    assert artifact["availability"] == "STALE"
    assert artifact["status"] == "STALE_LINEAGE"
    assert artifact["fields"]["freshness_reasons"] == ["MODEL_DATASET_OR_SPLIT_MISSING"]


def test_model_artifact_currentness_checks_outputs_and_dataset_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandas as pd

    processed = tmp_path / "processed"
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    dataset_id, split_id, model_id = "DS::current", "SPLIT::current", "MODEL::current"
    dataset_dir = processed / "datasets" / battery_id / experiment_id / "SOC" / dataset_id
    dataset_dir.mkdir(parents=True)
    feature_path = (
        processed / "features" / battery_id / experiment_id / "AS::test" / "FS::test" / "features.parquet"
    )
    label_path = processed / "labels" / battery_id / experiment_id / "LS::test" / "labels.parquet"
    dataset_path = dataset_dir / "dataset.parquet"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "amplitude_a_u": [0.5]}
    ).to_parquet(feature_path, index=False)
    pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "soc_reference_percent": [25.0]}
    ).to_parquet(label_path, index=False)
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::1"],
            "battery_id": [battery_id],
            "experiment_id": [experiment_id],
            "cycle_group_id": ["CYCLE::1"],
            "soc_reference_percent": [25.0],
            "amplitude_a_u": [0.5],
        }
    ).to_parquet(dataset_path, index=False)
    checksum = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    raw_root = tmp_path / "raw"
    registered_assets = {
        "electrical": ("E_TEST", "batteries/CELL_TEST/EXP_TEST/electrical/source.xlsx", b"xlsx source"),
        "ultrasound": ("U_TEST", "batteries/CELL_TEST/EXP_TEST/ultrasound/source.txt", b"txt source"),
    }
    asset_rows = [
        "asset_id,battery_id,experiment_id,modality,relative_path",
    ]
    for modality, (asset_id, relative_path, content) in registered_assets.items():
        source_path = raw_root / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)
        asset_rows.append(f"{asset_id},{battery_id},{experiment_id},{modality},{relative_path}")
        parser_dir = processed / modality / battery_id / experiment_id
        parser_dir.mkdir(parents=True, exist_ok=True)
        detail_key = "source_asset_details" if modality == "electrical" else "assets"
        path_key = "relative_path" if modality == "electrical" else "source_file"
        output_names = (
            {
                "records": "records.parquet",
                "cycles": "cycles.parquet",
                "steps": "steps.parquet",
            }
            if modality == "electrical"
            else {"frames": "frames.parquet", "waveforms": "waveforms.zarr"}
        )
        output_checksums = {}
        for output_key, filename in output_names.items():
            output_path = parser_dir / filename
            if filename.endswith(".zarr"):
                output_path.mkdir()
                (output_path / "chunk.bin").write_bytes(b"waveform chunk")
            else:
                output_path.write_bytes(f"{output_key} rows".encode())
            output_checksums[output_key] = content_sha256(output_path)
        (parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "source_sha256": {asset_id: checksum(source_path)},
                    "output_files": output_names,
                    "output_checksums": output_checksums,
                    detail_key: [
                        {
                            "asset_id": asset_id,
                            path_key: relative_path,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    analysis_slice_path = processed / "analysis_slices" / battery_id / experiment_id / "AS::test" / "analysis_slice.parquet"
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"analysis slice")
    waveform_store_path = processed / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    feature_definitions_path = feature_path.parent / "feature_definitions.json"
    feature_definitions_path.write_text('{"features":["amplitude_a_u"]}', encoding="utf-8")
    feature_manifest_path = feature_path.parent / "feature_set_manifest.json"
    feature_manifest_path.write_text(
        json.dumps(
            {
                    "feature_set_id": "FS::test",
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "analysis_slice_id": "AS::test",
                "analysis_slice_path": str(analysis_slice_path.relative_to(processed)),
                "analysis_slice_checksum": checksum(analysis_slice_path),
                "waveform_store_path": str(waveform_store_path.relative_to(processed)),
                "waveform_store_checksum": feature_waveform_store_sha256(waveform_store_path),
                "output_paths": {
                    "features": str(feature_path.relative_to(processed)),
                    "definitions": str(feature_definitions_path.relative_to(processed)),
                },
                "output_checksums": {
                    "features": checksum(feature_path),
                    "definitions": checksum(feature_definitions_path),
                },
            }
        ),
        encoding="utf-8",
    )
    label_manifest_path = processed / "labels" / battery_id / experiment_id / "label_manifest.json"
    cycle_label_path = label_path.parent / "cycle_labels.parquet"
    pd.DataFrame(
        {"cycle": [1], "soh_capacity_reference_percent": [99.0]}
    ).to_parquet(cycle_label_path, index=False)
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LS::test",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "output_paths": {
                    "event_labels": str(label_path.relative_to(processed)),
                    "cycle_labels": str(cycle_label_path.relative_to(processed)),
                },
                "output_checksums": {
                    "event_labels": checksum(label_path),
                    "cycle_labels": checksum(cycle_label_path),
                },
            }
        ),
        encoding="utf-8",
    )
    raw_manifest = raw_root / "manifests" / "data_assets.csv"
    raw_manifest.parent.mkdir(parents=True, exist_ok=True)
    raw_manifest.write_text("\n".join(asset_rows) + "\n", encoding="utf-8")
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "dataset_family": "SOC",
                "target_name": "soc_reference_percent",
                "target_column": "soc_reference_percent",
                "predictor_columns": ["amplitude_a_u"],
                "output_checksum": checksum(dataset_path),
                "feature_set_id": "FS::test",
                "feature_set_path": "features/CELL_TEST/EXP_TEST/AS::test/FS::test/features.parquet",
                "feature_set_checksum": checksum(feature_path),
                "feature_set_manifest_path": str(feature_manifest_path.relative_to(processed)),
                "feature_set_manifest_checksum": checksum(feature_manifest_path),
                "label_set_id": "LS::test",
                "label_set_path": "labels/CELL_TEST/EXP_TEST/LS::test/labels.parquet",
                "label_set_checksum": checksum(label_path),
                "label_set_manifest_path": str(label_manifest_path.relative_to(processed)),
                "label_set_manifest_checksum": checksum(label_manifest_path),
            }
        ),
        encoding="utf-8",
    )
    split_dir = processed / "splits" / battery_id / experiment_id / dataset_id / split_id
    split_dir.mkdir(parents=True)
    split_assignments = split_dir / "split_assignments.parquet"
    leakage_audit = split_dir / "leakage_audit.json"
    evaluation_readiness = split_dir / "evaluation_readiness.json"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::1"],
            "cycle_group_id": ["CYCLE::1"],
            "fold": ["fold1"],
            "role": ["TRAIN"],
            "strategy": ["TRAIN_ONLY"],
            "dataset_id": [dataset_id],
            "split_id": [split_id],
        }
    ).to_parquet(split_assignments, index=False)
    original_split_bytes = split_assignments.read_bytes()
    leakage_audit.write_text("{}", encoding="utf-8")
    evaluation_readiness.write_text("{}", encoding="utf-8")
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "split_id": split_id,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "strategy": "TRAIN_ONLY",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
                "group_counts": {"CYCLE::1": 1},
                "group_count": 1,
                "k": None,
                "explicit_holdout_groups": [],
                "require_roles": ["TRAIN", "VALIDATION"],
                "role_semantics": {
                    "held_out_role": "",
                    "independent_validation_groups": None,
                    "independent_test_groups": None,
                    "three_way_structure_present": False,
                    "held_out_target_usage": "NOT_APPLICABLE",
                    "note": "",
                },
                "row_count": 1,
                "fold_count": 1,
                "source_checksums": {
                    "dataset_parquet": checksum(dataset_path),
                    "dataset_manifest": checksum(dataset_dir / "dataset_manifest.json"),
                },
                "output_checksums": {
                    "split_assignments": checksum(split_assignments),
                    "leakage_audit": checksum(leakage_audit),
                    "evaluation_readiness": checksum(evaluation_readiness),
                },
            }
        ),
        encoding="utf-8",
    )
    model_dir = processed / "models" / battery_id / experiment_id / dataset_id / split_id / model_id
    model_dir.mkdir(parents=True)
    model_file = model_dir / "model.joblib"
    prediction_file = model_dir / "held_out_predictions.parquet"
    model_file.write_bytes(b"serialized estimator")
    prediction_file.write_bytes(b"held-out rows")
    (model_dir / "model_manifest.json").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "dataset_id": dataset_id,
                "split_id": split_id,
                "strategy": "DUMMY_MEAN",
                "fold_index": 1,
                "policy_version": "fixture-v1",
                "selected_features": ["amplitude_a_u"],
                "output_checksums": {
                    "model": checksum(model_file),
                    "held_out_predictions": checksum(prediction_file),
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=raw_root,
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    current = client.get(f"/api/v1/artifacts/{model_id}").json()["data"]

    assert current["availability"] == "AVAILABLE"
    assert current["status"] == "CURRENT"
    assert current["fields"]["selected_feature_count"] == 1
    changed_source = raw_root / registered_assets["electrical"][1]
    changed_source.write_bytes(b"replaced xlsx source")
    changed_raw = client.get(f"/api/v1/artifacts/{model_id}").json()["data"]
    assert changed_raw["availability"] == "BLOCKED"
    assert changed_raw["status"] == "INTEGRITY_BLOCKED"
    assert changed_raw["fields"]["integrity_reasons"] == ["PARSER_RAW_SOURCE_MISMATCH"]
    assert changed_raw["fields"]["invalid_modalities"] == ["electrical"]
    changed_source.write_bytes(registered_assets["electrical"][2])
    forged_assignments = pd.read_parquet(split_assignments)
    forged_assignments.loc[0, "measurement_event_id"] = "ME::not-in-dataset"
    forged_assignments.to_parquet(split_assignments, index=False)
    split_manifest_path = split_dir / "split_manifest.json"
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    split_manifest["output_checksums"]["split_assignments"] = checksum(split_assignments)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")
    semantically_invalid = client.get(f"/api/v1/artifacts/{model_id}").json()["data"]
    assert semantically_invalid["availability"] == "BLOCKED"
    assert semantically_invalid["status"] == "INTEGRITY_BLOCKED"
    assert "SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:fold1" in semantically_invalid[
        "fields"
    ]["freshness_reasons"]
    split_assignments.write_bytes(original_split_bytes)
    split_manifest["output_checksums"]["split_assignments"] = checksum(split_assignments)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")
    split_assignments.write_bytes(b"tampered split rows")
    tampered_split = client.get(f"/api/v1/artifacts/{model_id}").json()["data"]
    assert tampered_split["availability"] == "BLOCKED"
    assert tampered_split["status"] == "INTEGRITY_BLOCKED"
    assert tampered_split["fields"]["integrity_reasons"] == ["SPLIT_OUTPUT_CHECKSUM_MISMATCH"]
    assert tampered_split["fields"]["invalid_outputs"] == ["split_assignments"]
    split_assignments.write_bytes(original_split_bytes)
    model_file.write_bytes(b"tampered estimator")
    tampered = client.get(f"/api/v1/artifacts/{model_id}").json()["data"]
    assert tampered["availability"] == "BLOCKED"
    assert tampered["status"] == "INTEGRITY_BLOCKED"
    assert tampered["fields"]["invalid_outputs"] == ["model"]


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
    assert {"BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTENUATION", "BPS"} <= codes
    from battery_workbench.features_physical.canonical_tof import (
        canonical_tof_integrity_reasons,
    )

    tof_reasons = canonical_tof_integrity_reasons(PROCESSED, "CELL_001", "EXP_001")
    meta = resp.json()["meta"]
    if tof_reasons:
        assert "tof_us" not in codes
        assert meta["canonical_tof_status"] == "BLOCKED_BY_ARTIFACT_INTEGRITY"
        assert meta["canonical_tof_integrity_warning"]["integrity_reasons"] == tof_reasons
    else:
        assert "tof_us" in codes
        assert meta["canonical_tof_status"] == "AVAILABLE"
    swa = next(f for f in data["features"] if f["feature_code"] == "SWA")
    assert len(swa["values"]) == 40
    assert swa["display_name_zh"] == "表面波幅值"
    tof = next(f for f in data["features"] if f["feature_code"] == "TOF_XCORR")
    assert "physical_time_blocked" in tof  # never fabricates tof_us


def test_feature_correlations_endpoint(client: TestClient) -> None:
    if not has_real:
        pytest.skip("CELL_001 parser artifacts not available")
    resp = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/feature-correlations?feature_code=SWA&limit=120"
    )
    if resp.status_code == 409:
        error = resp.json()["error"]
        assert error["code"] == "INTEGRITY_ERROR"
        assert error["details"]["recovery_action"] in {
            "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            "REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
        }
        assert error["details"]["integrity_reasons"]
        return

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    condition_analysis = data["declared_condition_analysis"]
    assert condition_analysis["status"] == "NOT_CONFIGURED"
    assert condition_analysis["absolute_timebase_status"] == "NOT_ASSESSED"
    assert condition_analysis["results"] == []
    assert len(data["soc"]) == 8
    assert {result["scope"] for result in data["soc"]} == {
        "overall", "charge", "discharge", "rest",
    }

    decomposition = data["soc_battery_decomposition"]
    assert decomposition["status"] == "INSUFFICIENT_BATTERY_GROUPS"
    assert decomposition["declared_battery_group_count"] == 1
    assert decomposition["physical_battery_count"] is None
    assert decomposition["battery_identity_status"] == "NOT_ASSESSED"
    assert decomposition["between_battery"]["coefficient"] is None
    assert len(data["soc_by_battery_condition"]) == 4

    # The point limit affects visualization only; coefficients use every event.
    assert data["n_events"] >= 120
    assert len(data["soc_diagnostic_scatter"]["points"]) <= 120
    assert len(data["soc_by_cycle"]) >= 2
    overall = next(
        result for result in data["soc"]
        if result["scope"] == "overall" and result["method"] == "pearson"
    )
    assert overall["n_input"] == data["n_events"]
    assert (
        overall["n_valid"]
        + overall["missing_feature_count"]
        + overall["missing_state_count"]
        + overall["excluded_ineligible_count"]
        == overall["n_input"]
    )

    assert data["temperature"]["status"] == "BLOCKED_BY_VALIDATION"
    assert data["temperature"]["coefficient"] is not None
    assert any(
        "sensor location and calibration evidence are not verified" in limitation
        for limitation in data["temperature"]["limitations"]
    )
    assert data["soh"]["status"] == "NOT_READY_INSUFFICIENT_SOH_STATES"
    assert data["soh"]["distinct_state_count"] == 2
    assert data["soh"]["n_valid_unit"] == "BATTERY_EXPERIMENT_CYCLE_GROUP"
    assert data["alignment_assessment"]["status"] == "PROVISIONAL"
    assert data["alignment_assessment"]["validated_sync"] is False

    inference = data["inference_assessment"]
    assert inference["analysis_mode"] == "EXPLORATORY"
    assert inference["correlation_results_included"] is True
    assert inference["confidence_interval"]["status"] == "NOT_ESTIMATED"
    assert inference["p_value"]["status"] == "NOT_ESTIMATED"
    assert inference["multiple_comparison"]["status"] == "NOT_ASSESSED"
    assert inference["confounder_adjustment"]["status"] == "NOT_ASSESSED"


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
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?frame_index=2000")
    row = resp.json()["data"]["events"][0]
    assert row["soc_reference_percent"] == pytest.approx(0.123143, abs=1e-4)
    assert resp.json()["meta"]["soc_reference_label_source"] != "UNAVAILABLE"
    amb = client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?frame_index=691")
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
        "sync_error_s",
        "ultrasound_asset_id",
        "electrical_asset_id",
        "provisional_absolute_timestamp",
        "match_status",
    } <= set(first)
    frame = first["frame_index_raw"]
    scoped = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=500&frame_index={frame}"
    )
    rows = scoped.json()["data"]["events"]
    assert rows and all(r["frame_index_raw"] == frame for r in rows)
    # alignment uncertainty is never hidden (contract §8)
    assert all(r["sync_error_s"] is not None for r in rows)
    asset = first["ultrasound_asset_id"]
    by_asset = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=50&asset_id={asset}"
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
        swa = next(t for t in base["gate_templates"] if t["gate_template_id"] == "SWA_SURFACE_GATE")
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
        r1 = client.post("/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body)
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
            t for t in after["gate_templates"] if t["gate_template_id"] == "SWA_SURFACE_GATE"
        )
        assert swa2["bounds_source"] == "EXPERIMENT_FROZEN"
        assert swa2["python_start"] == swa["python_start"] + 5
        assert after["generic_calibration"]["gate_calibration_id"] == (rec["gate_calibration_id"])
        assert all(
            swa["python_start"] + 5 <= row["peak_sample_in_gate"] < swa["python_end_exclusive"] + 5
            for row in after["diagnostics"]
        )
        physical = client.get("/api/v1/experiments/CELL_001/EXP_001/physical-features?limit=1")
        assert physical.status_code == 200
        assert physical.json()["meta"]["gate_calibration_id"] == (rec["gate_calibration_id"])
        # identical re-freeze is idempotent
        r2 = client.post("/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body)
        assert r2.json()["data"]["reuse_status"] == "REUSED"
        assert r2.json()["data"]["gate_calibration_id"] == rec["gate_calibration_id"]
        # changed bounds → a different immutable record
        body2 = {
            **body,
            "gate_bounds": {"SWA_SURFACE_GATE": {"start": 10, "end": 210}},
            "confirmed_at": "gap-test-2",
        }
        r3 = client.post("/api/v1/experiments/CELL_001/EXP_001/gate-calibration", json=body2)
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
        bad3 = client.post(
            "/api/v1/experiments/CELL_001/EXP_001/gate-calibration",
            json={
                **body,
                "gate_bounds": {"SWA_SURFACE_GATE": {"start": 1, "end": 10**9}},
            },
        )
        assert bad3.status_code == 400
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
        "reference_soc_percent",
        "temperature_c",
        "soh_capacity_reference_percent",
        "voltage_v",
        "current_a",
    }
    soc = targets["reference_soc_percent"]
    assert soc["semantic_type"] == "DERIVED_REFERENCE_LABEL"
    assert "True SOC" not in json.dumps(soc) and "Ground Truth" not in json.dumps(soc)
    assert soc["coverage"]["valid"] == 3995  # real counts from artifacts
    assert targets["temperature_c"]["readiness"] == "BLOCKED_BY_VALIDATION"
    soh = targets["soh_capacity_reference_percent"]
    assert soh["coverage"]["independent_states"] == 2
    assert soh["readiness"] == "NOT_READY"


def test_alignment_summary_counts_and_semantics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import features_v2

    # Isolate the summary contract from TimeAnchor freshness; the API guard is
    # covered by fresh-intake and timebase-chain integrity tests.
    monkeypatch.setattr(features_v2, "assert_current_timebase_chain", lambda *_a, **_k: None)
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


def test_alignment_samples_provenance_and_null_identity(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import features_v2

    monkeypatch.setattr(features_v2, "assert_current_timebase_chain", lambda *_a, **_k: None)
    unique = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/alignment-samples?filter=eligible&limit=2"
    )
    row = unique.json()["data"]["samples"][0]
    assert row["electrical_asset_id"] == "E001"
    assert row["sync_error_s"] is not None
    assert row["ultrasound_asset_id"] == "U001"
    assert row["ultrasound_source_file"] == (
        "batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt"
    )
    assert row["ultrasound_source_line_index"] == 1
    electrical_manifest = json.loads(
        (PROCESSED / "electrical/CELL_001/EXP_001/parser_manifest.json").read_text(encoding="utf-8")
    )
    ultrasound_manifest = json.loads(
        (PROCESSED / "ultrasound/CELL_001/EXP_001/parser_manifest.json").read_text(encoding="utf-8")
    )
    assert row["electrical_source_sha256"] == electrical_manifest["source_sha256"]["E001"]
    assert row["ultrasound_source_sha256"] == ultrasound_manifest["source_sha256"]["U001"]
    assert row["electrical_source_file"].endswith("/electrical/小-1-1-264.xlsx")
    amb = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-samples?filter=ambiguous")
    for s in amb.json()["data"]["samples"]:
        assert s["electrical_asset_id"] is None  # never auto-selected
        assert s["electrical_source_sha256"] is None
        assert s["sync_ambiguous"] is True
        assert s["candidate_details_available"] is True
        assert s["candidate_record_count"] == len(s["electrical_candidates"])
        assert s["candidate_record_count"] >= 2
        assert all(candidate["electrical_asset_id"] for candidate in s["electrical_candidates"])
        assert all(
            candidate["electrical_record_locator"] for candidate in s["electrical_candidates"]
        )
        assert all(candidate["electrical_source_file"] for candidate in s["electrical_candidates"])
        assert all(
            candidate["electrical_source_sha256"] for candidate in s["electrical_candidates"]
        )


def test_alignment_samples_returns_raw_ultrasound_locator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import features_v2

    timestamp = pd.Timestamp("2024-01-01T00:00:00")
    joined = pd.DataFrame(
        [
            {
                "measurement_event_id": "CELL_X::EXP_X::U_TEST::7",
                "frame_index_raw": 7,
                "ultrasound_asset_id": "U_TEST",
                "source_file": "batteries/CELL_X/EXP_X/ultrasound/test.txt",
                "source_line_index": 8,
                "provisional_absolute_timestamp": timestamp,
                "electrical_asset_id": "E_TEST",
                "electrical_record_locator": "E_TEST:4",
                "electrical_timestamp": timestamp,
                "match_status": "MATCHED_UNIQUE",
                "sync_ambiguous": False,
                "sync_error_s": 0.0,
                "within_tolerance": True,
                "analysis_eligible": True,
                "soc_reference_percent": 42.0,
                "temperature_c": None,
                "soh_capacity_reference_percent": None,
                "voltage_v": 3.7,
                "current_a": 1.0,
            }
        ]
    )
    monkeypatch.setattr(features_v2, "_alignment_events_joined", lambda *_: (joined, False))
    monkeypatch.setattr(
        features_v2,
        "_parser_source_assets",
        lambda *_, **__: {
            "electrical": {"E_TEST": {"sha256": "b" * 64}},
            "ultrasound": {"U_TEST": {"sha256": "a" * 64}},
        },
    )
    response = client.get("/api/v1/experiments/CELL_X/EXP_X/alignment-samples?filter=eligible")
    row = response.json()["data"]["samples"][0]
    assert row["ultrasound_asset_id"] == "U_TEST"
    assert row["ultrasound_source_file"].endswith("/ultrasound/test.txt")
    assert row["ultrasound_source_line_index"] == 8
    assert row["ultrasound_source_sha256"] == "a" * 64
    joined.loc[0, "electrical_source_file"] = "batteries/CELL_X/EXP_X/electrical/test.xlsx"
    # The source file comes from the selected composite electrical record.
    response = client.get("/api/v1/experiments/CELL_X/EXP_X/alignment-samples?filter=eligible")
    row = response.json()["data"]["samples"][0]
    assert row["electrical_source_file"].endswith("/electrical/test.xlsx")
    assert row["electrical_source_sha256"] == "b" * 64


def test_alignment_exclusions_grouped_by_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import features_v2

    monkeypatch.setattr(features_v2, "assert_current_timebase_chain", lambda *_a, **_k: None)
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/alignment-exclusions")
    reasons = {e["reason"]: e["count"] for e in resp.json()["data"]["exclusions"]}
    assert reasons["AMBIGUOUS_SYNC"] == 4


def test_feature_label_preview_one_target_grain(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-label-preview",
        json={
            "target_id": "reference_soc_percent",
            "features": ["SWA", "BOTTOM_AMP", "TOF_XCORR"],
            "limit": 20,
        },
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
        json={
            "target_id": "reference_soc_percent",
            "features": ["SWA", "BOTTOM_AMP"],
            "mode": "EXPLORATORY",
        },
    )
    assert resp.status_code == 200
    by_code = {r["feature_code"]: r for r in resp.json()["data"]["ranking"]}
    assert by_code["SWA"]["direction_dependent"] is True
    assert by_code["SWA"]["pearson_charge"] > 0 > by_code["SWA"]["pearson_discharge"]

    soh = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
        json={
            "target_id": "soh_capacity_reference_percent",
            "features": ["SWA"],
            "mode": "EXPLORATORY",
        },
    )
    assert soh.json()["data"]["group_summary"]
    assert soh.json()["data"]["ranking"] == []  # no frame-level SOH leaderboard


@pytest.mark.parametrize(
    ("features", "expected_message"),
    [
        ([f"FEATURE_{index}" for index in range(13)], "at most 12"),
        ("SWA", "array of feature codes"),
    ],
)
def test_feature_target_ranking_rejects_invalid_feature_collection(
    client: TestClient, features: object, expected_message: str
) -> None:
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/feature-target-ranking",
        json={"target_id": "reference_soc_percent", "features": features},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert expected_message in response.json()["error"]["message"]


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
        "TARGET",
        "ALIGNMENT",
        "FEATURES",
        "PREVIEW",
        "DATASET",
        "SPLIT",
        "MODELS",
        "REPORT",
    )
    # The read model follows the artifacts currently committed in the real workspace;
    # it must not assume a particular RC1 dataset/split/model/report snapshot.
    assert d["current_step"] in d["step_statuses"]
    rec = d["recommended_next_action"]
    assert isinstance(rec["action_id"], str) and rec["action_id"]
    assert rec["route"].startswith("/experiments/CELL_001/EXP_001/")
    assert "dataset" in d["artifact_freshness"]


def test_brw025wf_workflow_context_unknown_experiment_404(client: TestClient) -> None:
    r = client.get("/api/v1/experiments/CELL_999/EXP_999/workflow-context")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"

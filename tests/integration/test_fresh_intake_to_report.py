"""Fresh real-data acceptance: public APIs from intake through formal report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
ELECTRICAL = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
ULTRASOUND = (
    REPO / "data/raw/batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not ELECTRICAL.is_file() or not ULTRASOUND.is_file(), reason="real inputs absent"
)
def test_fresh_intake_feature_dataset_model_report_chain(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    manifests = raw / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "batteries.csv").write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\n", encoding="utf-8"
    )
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version\n",
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw, processed_root=processed, runs_root=tmp_path / "runs")
    )
    battery_id, experiment_id = "CELL_FRESH", "EXP_FRESH"

    created = client.post(
        "/api/v1/experiments",
        json={"battery_id": battery_id, "experiment_id": experiment_id, "name": "fresh E2E"},
    )
    assert created.status_code == 200, created.text
    session = client.post(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/intake-sessions"
    ).json()["data"]
    for role, path, name in (
        ("ELECTRICAL", ELECTRICAL, "electrical.xlsx"),
        ("ULTRASOUND", ULTRASOUND, "ultrasound.txt"),
    ):
        response = client.post(
            f"/api/v1/intake-sessions/{session['session_id']}/assets",
            files={"file": (name, path.read_bytes(), "application/octet-stream")},
            data={
                "role": role,
                **({"file_start_time": "2024-01-06 09:52:31"} if role == "ULTRASOUND" else {}),
            },
        )
        assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/intake-sessions/{session['session_id']}/detect").status_code == 200
    validation = client.post(f"/api/v1/intake-sessions/{session['session_id']}/validate")
    assert validation.status_code == 200 and validation.json()["data"]["overall_passed"]
    assert client.post(f"/api/v1/intake-sessions/{session['session_id']}/commit").status_code == 200

    ingest = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": battery_id,
            "experiment_id": experiment_id,
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["data"]["status"] == "SUCCEEDED"

    # Provenance added to the synchronization contract must survive the real
    # intake → parser → synchronization → MeasurementEvent → public API path.
    aligned_path = (
        processed
        / "synchronization"
        / battery_id
        / experiment_id
        / "aligned_ultrasound_frames.parquet"
    )
    aligned = pd.read_parquet(aligned_path)
    assert {"source_file", "source_line_index"}.issubset(aligned.columns)
    assert aligned["source_file"].notna().any()
    assert aligned["source_line_index"].notna().any()
    alignment = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-summary"
    )
    assert alignment.status_code == 200, alignment.text
    assert alignment.json()["data"]["target_labels_available"] is False
    assert alignment.json()["data"]["target_valid"]["soc_reference_percent"] == 0
    samples = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples?filter=all&limit=1"
    )
    assert samples.status_code == 200, samples.text
    sample = samples.json()["data"]["samples"][0]
    assert sample["ultrasound_asset_id"]
    assert sample["ultrasound_source_file"].endswith("/ultrasound.txt")
    assert sample["ultrasound_source_line_index"] is not None
    assert sample["electrical_source_file"].endswith("/electrical.xlsx")
    # Same instrument source as the existing verified CELL_001 record; the
    # value is explicitly user-supplied here and never inferred from cadence/filename.
    sampling = client.post(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/sampling-parameter-submission",
        json={
            "values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}},
            "source": "integration-test:verified-instrument-record",
            "verified": True,
            "submission_id": "fresh-e2e-fs",
        },
    )
    assert sampling.status_code == 200, sampling.text
    assert sampling.json()["data"]["save_status"] in {"SAVED", "REPLAYED"}

    gate = client.post(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/gate-calibration",
        json={
            "confirmed_by": "integration-test",
            "calibration_basis": "PREDECLARED_PROTOCOL_GATE",
            "gate_bounds": {"SWA_SURFACE_GATE": {"start": 80, "end": 230}},
            "confirmed_at": "fresh-e2e-gate-v1",
        },
    )
    assert gate.status_code == 200, gate.text
    gate_calibration_id = gate.json()["data"]["gate_calibration_id"]

    dataset = client.post(
        "/api/v1/runs",
        json={
            "profile": "BUILD_DATASET",
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "target": "soc_reference_percent",
            "features": {"selected_features": ["SWA"]},
        },
    )
    assert dataset.status_code == 200, dataset.text
    dataset_data = dataset.json()["data"]
    assert dataset_data["status"] == "SUCCEEDED", json.dumps(dataset_data, default=str)
    alignment_after_labels = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-summary"
    )
    assert alignment_after_labels.json()["data"]["target_labels_available"] is True
    dataset_manifests = list(
        (processed / "datasets" / battery_id / experiment_id).rglob("dataset_manifest.json")
    )
    assert dataset_manifests
    assert any(
        json.loads(path.read_text(encoding="utf-8")).get("gate_calibration_id")
        == gate_calibration_id
        for path in dataset_manifests
    )

    model_request = {
        "profile": "FULL_PRE_MODEL",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "stages": ["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING", "SCIENTIFIC_REPORT"],
        "target": "soc_reference_percent",
        "features": {"selected_features": ["SWA"]},
        "fold_index": 1,
        "split": {
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
        "feature_analysis": {
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "target": "soc_reference_percent",
            "candidate_features": ["SWA"],
            "fold_index": 1,
            "methods": ["descriptive", "spearman"],
            "selection": {
                "requested": True,
                "mode": "TRAIN_ONLY_RULE_BASED",
                "policy": {"min_abs_spearman": 0.0, "max_missing_fraction": 1.0},
            },
        },
    }
    started = client.post("/api/v1/runs", json=model_request)
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    assert run["status"] == "WAITING_FOR_USER"
    actions = client.get(f"/api/v1/runs/{run['run_id']}/user-actions").json()["data"][
        "user_actions"
    ]
    confirmation = next(a for a in actions if a["action_type"] == "CONFIRM_FEATURE_SELECTION")
    selection_id = confirmation["required_fields"][0]["value"]
    resumed = client.post(
        f"/api/v1/runs/{run['run_id']}/user-actions/{confirmation['action_id']}",
        json={"values": {"selection_id": selection_id}},
    )
    assert resumed.status_code == 200, resumed.text
    final_run = client.get(f"/api/v1/runs/{run['run_id']}").json()["data"]
    assert final_run["status"] == "SUCCEEDED"

    report = client.post(
        "/api/v1/reports",
        json={"battery_id": battery_id, "experiment_id": experiment_id},
    )
    assert report.status_code == 200, report.text
    payload = report.json()["data"]
    assert payload["report_id"].startswith("REPORT::")
    assert payload["experiment_record"]["battery_id"] == battery_id
    assert payload["reproducibility_manifest"]["dataset_id"].startswith("DS::")
    assert payload["scientific_findings"]

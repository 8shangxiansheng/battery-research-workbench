from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app


def _write_source(
    processed_root: Path, dataset_id: str, battery_id: str, experiment_id: str
) -> None:
    folder = processed_root / "datasets" / battery_id / experiment_id / "SOC" / dataset_id
    folder.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "measurement_event_id": [f"{battery_id}::ME::1", f"{battery_id}::ME::2"],
            "battery_id": [battery_id, battery_id],
            "experiment_id": [experiment_id, experiment_id],
            "soc_reference_percent": [20.0, 40.0],
            "peak_to_peak_v": [0.2, 0.4],
        }
    )
    parquet = folder / "dataset.parquet"
    frame.to_parquet(parquet, index=False)
    checksum = hashlib.sha256(parquet.read_bytes()).hexdigest()
    (folder / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "dataset_family": "SOC",
                "dataset_status": "READY_FOR_SPLIT",
                "target_column": "soc_reference_percent",
                "predictor_columns": ["peak_to_peak_v"],
                "target_method_version": "soc-formula/1.0",
                "soc_label_temporality": "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE",
                "output_checksum": checksum,
            }
        ),
        encoding="utf-8",
    )
    feature_dir = processed_root / "features" / battery_id / experiment_id / "SLICE::1" / "FS::1"
    feature_dir.mkdir(parents=True)
    (feature_dir / "feature_definitions.json").write_text(
        json.dumps({"features": [{"name": "peak_to_peak_v", "version": "0.1.0", "unit": "V"}]}),
        encoding="utf-8",
    )
    manifest_path = folder / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["feature_set_id"] = "FS::1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _request() -> dict:
    return {
        "cohort_id": "COHORT::fixture",
        "source_datasets": [
            {"source_dataset_id": "DS::A", "battery_id": "CELL_A", "experiment_id": "EXP_A"},
            {"source_dataset_id": "DS::B", "battery_id": "CELL_B", "experiment_id": "EXP_B"},
        ],
        "target_mapping": {
            "canonical_target_id": "reference_soc_percent",
            "source_target_ids": {
                "DS::A": "soc_reference_percent",
                "DS::B": "soc_reference_percent",
            },
            "unit": "percent",
            "method_version": "soc-formula/1.0",
        },
        "feature_mappings": [
            {
                "canonical_feature_id": "ultrasound_peak_to_peak",
                "source_feature_ids": {"DS::A": "peak_to_peak_v", "DS::B": "peak_to_peak_v"},
                "method_version": "0.1.0",
            }
        ],
        "unit_mapping": {
            "ultrasound_peak_to_peak": {
                "source_units": {"DS::A": "V", "DS::B": "V"},
                "canonical_unit": "V",
            }
        },
        "harmonization_method_version": "cohort-harmonization/1.0",
        "harmonization_policy_id": "POLICY::fixture",
        "evidence_refs": ["EVIDENCE::fixture"],
    }


def test_cohort_api_materializes_immutable_provenance_and_is_idempotent(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    source_catalogue = client.get("/api/v1/datasets").json()["data"]
    assert {item["dataset_id"] for item in source_catalogue} == {"DS::A", "DS::B"}
    assert all(
        "output_path" not in item and "feature_set_path" not in item for item in source_catalogue
    )

    first = client.post("/api/v1/cohort-datasets", json=_request())
    reordered = _request()
    reordered["source_datasets"].reverse()
    second = client.post("/api/v1/cohort-datasets", json=reordered)

    assert first.status_code == 200, first.text
    result = first.json()["data"]
    assert result["status"] == "READY_FOR_BATTERY_SPLIT"
    assert result["battery_count"] == 2
    assert result["row_count"] == 4
    cohort_frame = pd.read_parquet(processed / result["output_path"])
    assert cohort_frame["measurement_event_id"].is_unique
    assert cohort_frame["source_measurement_event_id"].tolist() == [
        "CELL_A::ME::1",
        "CELL_A::ME::2",
        "CELL_B::ME::1",
        "CELL_B::ME::2",
    ]
    assert result["cohort_dataset_id"] == second.json()["data"]["cohort_dataset_id"]
    assert Path(processed / result["output_path"]).is_file()

    detail = client.get(f"/api/v1/cohort-datasets/{result['cohort_dataset_id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["artifact_type"] == "COHORT_DATASET"
    assert "output_path" not in detail.json()["data"]["fields"]


def test_cohort_api_rejects_path_and_unready_source(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    request = _request()
    request["source_datasets"][0]["path"] = "/tmp/attacker.parquet"
    response = client.post("/api/v1/cohort-datasets", json=request)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    request = _request()
    manifest_path = next(
        path
        for path in (processed / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == "DS::B"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_status"] = "NOT_READY_FOR_MODEL_EVALUATION"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    response = client.post("/api/v1/cohort-datasets", json=request)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


def test_cohort_lobo_api_persists_battery_metrics_predictions_and_audit(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    _write_source(processed, "DS::C", "CELL_C", "EXP_C")
    payload = _request()
    payload["source_datasets"].append(
        {"source_dataset_id": "DS::C", "battery_id": "CELL_C", "experiment_id": "EXP_C"}
    )
    for key in ("source_target_ids",):
        payload["target_mapping"][key]["DS::C"] = "soc_reference_percent"
    payload["feature_mappings"][0]["source_feature_ids"]["DS::C"] = "peak_to_peak_v"
    payload["unit_mapping"]["ultrasound_peak_to_peak"]["source_units"]["DS::C"] = "V"
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    created = client.post("/api/v1/cohort-datasets", json=payload)
    cohort_id = created.json()["data"]["cohort_dataset_id"]
    evaluated = client.post(
        f"/api/v1/cohort-datasets/{cohort_id}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert evaluated.status_code == 200
    result = evaluated.json()["data"]
    assert result["evaluation_scope"] == "CROSS_BATTERY_LOBO_LIMITED_EVALUATION"
    assert result["battery_count"] == 3
    assert result["macro_by_strategy"]["DUMMY_MEAN"]["battery_count"] == 3
    assert result["leakage_audit"]["group_column"] == "battery_id"
    assert result["provenance"]["harmonization_policy_id"] == "POLICY::fixture"
    assert result["battery_results"][0]["cohort_id"] == "COHORT::fixture"
    assert Path(processed / result["artifacts"]["held_out_predictions"]).is_file()
    assert Path(processed / result["artifacts"]["split_assignments"]).is_file()
    assert Path(processed / result["artifacts"]["cohort_report_json"]).is_file()
    assert Path(processed / result["artifacts"]["cohort_report_html"]).is_file()
    predictions = pd.read_parquet(processed / result["artifacts"]["held_out_predictions"])
    assignments = pd.read_parquet(processed / result["artifacts"]["split_assignments"])
    assert {"cohort_id", "fold", "battery_id", "source_dataset_id"}.issubset(predictions.columns)
    assert {"cohort_id", "fold", "battery_id", "source_dataset_id"}.issubset(assignments.columns)
    fetched = client.get(f"/api/v1/cohort-lobo-evaluations/{result['evaluation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["artifact_checksums"] == result["artifact_checksums"]


def test_source_change_marks_cohort_stale_and_blocks_new_evaluation(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    manifest_path = next(
        path
        for path in (processed / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == "DS::A"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_status"] = "NOT_READY_FOR_MODEL_EVALUATION"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    detail = client.get(f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}").json()["data"]
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )
    assert listed[0]["status"] == "STALE_SOURCE"
    assert detail["status"] == "STALE_SOURCE"
    assert detail["availability"] == "STALE"
    assert evaluation.status_code == 409
    assert evaluation.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_cached_cohort_lobo_rejects_missing_or_corrupt_artifacts(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    cohort = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    response = client.post(
        f"/api/v1/cohort-datasets/{cohort['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )
    assert response.status_code == 200
    result = response.json()["data"]
    predictions_path = processed / result["artifacts"]["held_out_predictions"]
    predictions_path.write_bytes(predictions_path.read_bytes() + b"corrupt")

    repeated = client.post(
        f"/api/v1/cohort-datasets/{cohort['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )
    fetched = client.get(f"/api/v1/cohort-lobo-evaluations/{result['evaluation_id']}")
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert fetched.status_code == 409
    assert fetched.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_same_request_after_source_definition_change_creates_new_version(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    first = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]

    definitions_path = next((processed / "features").rglob("feature_definitions.json"))
    definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
    definitions["features"][0]["description"] = "Updated validated source definition"
    for path in (processed / "features").rglob("feature_definitions.json"):
        path.write_text(json.dumps(definitions), encoding="utf-8")

    second_response = client.post("/api/v1/cohort-datasets", json=_request())
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()["data"]
    assert second["cohort_dataset_id"] != first["cohort_dataset_id"]

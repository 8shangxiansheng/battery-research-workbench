from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.datasets.cohort import eligible_cohort_for_experiment


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
                "target_name": "soc_reference_percent",
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
    definitions_path = feature_dir / "feature_definitions.json"
    feature_path = feature_dir / "ultrasound_features.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": [f"{battery_id}::ME::1", f"{battery_id}::ME::2"],
            "peak_to_peak_v": [0.2, 0.4],
        }
    ).to_parquet(feature_path, index=False)
    analysis_slice_path = (
        processed_root / "analysis_slices" / battery_id / experiment_id / "SLICE::1.parquet"
    )
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"analysis slice")
    waveform_store_path = processed_root / "waveform_inputs" / battery_id / experiment_id / "waveforms.zarr"
    waveform_store_path.mkdir(parents=True)
    (waveform_store_path / "chunk.bin").write_bytes(b"waveform")
    feature_manifest_path = feature_dir / "feature_set_manifest.json"
    feature_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS::1",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "analysis_slice_id": "SLICE::1",
                "analysis_slice_path": str(analysis_slice_path.relative_to(processed_root)),
                "analysis_slice_checksum": hashlib.sha256(analysis_slice_path.read_bytes()).hexdigest(),
                "waveform_store_path": str(waveform_store_path.relative_to(processed_root)),
                "waveform_store_checksum": _tree_sha256(waveform_store_path),
                "output_paths": {
                    "features": str(feature_path.relative_to(processed_root)),
                    "definitions": str(definitions_path.relative_to(processed_root)),
                },
                "output_checksums": {
                    "features": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
                    "definitions": hashlib.sha256(definitions_path.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    label_dir = processed_root / "labels" / battery_id / experiment_id
    label_dir.mkdir(parents=True)
    label_path = label_dir / "event_labels.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": [f"{battery_id}::ME::1", f"{battery_id}::ME::2"],
            "soc_reference_percent": [20.0, 40.0],
        }
    ).to_parquet(label_path, index=False)
    cycle_label_path = label_dir / "cycle_labels.parquet"
    pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [99.0]}).to_parquet(
        cycle_label_path, index=False
    )
    label_manifest_path = label_dir / "label_manifest.json"
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LB::1",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "output_paths": {
                    "event_labels": str(label_path.relative_to(processed_root)),
                    "cycle_labels": str(cycle_label_path.relative_to(processed_root)),
                },
                "output_checksums": {
                    "event_labels": hashlib.sha256(label_path.read_bytes()).hexdigest(),
                    "cycle_labels": hashlib.sha256(cycle_label_path.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    manifest_path = folder / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["feature_set_id"] = "FS::1"
    manifest["feature_set_path"] = str(feature_path.relative_to(processed_root))
    manifest["feature_set_checksum"] = hashlib.sha256(feature_path.read_bytes()).hexdigest()
    manifest["feature_set_manifest_path"] = str(
        feature_manifest_path.relative_to(processed_root)
    )
    manifest["feature_set_manifest_checksum"] = hashlib.sha256(
        feature_manifest_path.read_bytes()
    ).hexdigest()
    manifest["label_set_id"] = "LB::1"
    manifest["label_set_path"] = str(label_path.relative_to(processed_root))
    manifest["label_set_checksum"] = hashlib.sha256(label_path.read_bytes()).hexdigest()
    manifest["label_set_manifest_path"] = str(
        label_manifest_path.relative_to(processed_root)
    )
    manifest["label_set_manifest_checksum"] = hashlib.sha256(
        label_manifest_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


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
    assert result["identity_verification_status"] == "NOT_ASSESSED"
    assert eligible_cohort_for_experiment(processed, "CELL_A", "EXP_A") is None
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


def test_raw_source_change_blocks_cohort_catalogue_reuse_and_lobo(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    sources = {
        "CELL_A": ("EXP_A", "E_A", "batteries/CELL_A/EXP_A/electrical/source.xlsx"),
        "CELL_B": ("EXP_B", "E_B", "batteries/CELL_B/EXP_B/electrical/source.xlsx"),
    }
    manifest_rows = ["asset_id,battery_id,experiment_id,modality,relative_path"]
    for battery_id, (experiment_id, asset_id, relative_path) in sources.items():
        _write_source(processed, f"DS::{battery_id[-1]}", battery_id, experiment_id)
        source_path = raw / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(f"source {battery_id}".encode())
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        manifest_rows.append(
            f"{asset_id},{battery_id},{experiment_id},electrical,{relative_path}"
        )
        parser_dir = processed / "electrical" / battery_id / experiment_id
        parser_dir.mkdir(parents=True)
        output_files = {
            "records": "records.parquet",
            "cycles": "cycles.parquet",
            "steps": "steps.parquet",
        }
        output_checksums = {}
        for key, filename in output_files.items():
            output_path = parser_dir / filename
            output_path.write_bytes(key.encode())
            output_checksums[key] = hashlib.sha256(output_path.read_bytes()).hexdigest()
        (parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "source_sha256": {asset_id: digest},
                    "source_asset_details": [
                        {"asset_id": asset_id, "relative_path": relative_path}
                    ],
                    "output_files": output_files,
                    "output_checksums": output_checksums,
                }
            ),
            encoding="utf-8",
        )
    assets_manifest = raw / "manifests" / "data_assets.csv"
    assets_manifest.parent.mkdir(parents=True)
    assets_manifest.write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")
    client = TestClient(create_app(processed_root=processed, raw_root=raw))
    response = client.post("/api/v1/cohort-datasets", json=_request())
    assert response.status_code == 200, response.text
    cohort_id = response.json()["data"]["cohort_dataset_id"]

    changed_source = raw / sources["CELL_A"][2]
    changed_source.write_bytes(b"replaced source bytes")

    catalogue = client.get("/api/v1/datasets").json()["data"]
    changed_dataset = next(item for item in catalogue if item["dataset_id"] == "DS::A")
    assert changed_dataset["source_integrity_status"] == "INTEGRITY_BLOCKED"
    assert changed_dataset["eligible_rows"] is None
    cohorts = client.get("/api/v1/cohort-datasets").json()["data"]
    cohort = next(item for item in cohorts if item["cohort_dataset_id"] == cohort_id)
    assert cohort["status"] == "INTEGRITY_BLOCKED"
    assert cohort["row_count"] is None
    detail = client.get(f"/api/v1/cohort-datasets/{cohort_id}").json()["data"]
    assert detail["status"] == "INTEGRITY_BLOCKED"
    assert detail["row_count"] is None
    lobo = client.post(
        f"/api/v1/cohort-datasets/{cohort_id}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )
    assert lobo.status_code == 409
    assert lobo.json()["error"]["code"] == "INTEGRITY_ERROR"


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


@pytest.mark.parametrize("checksum_state", ["missing", "malformed", "mismatch"])
def test_cohort_api_rejects_unverified_source_checksum(tmp_path: Path, checksum_state: str) -> None:
    processed = tmp_path / checksum_state / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    manifest_path = next(
        path
        for path in (processed / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == "DS::A"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if checksum_state == "missing":
        manifest.pop("output_checksum")
    elif checksum_state == "malformed":
        manifest["output_checksum"] = "not-a-sha256"
    else:
        manifest["output_checksum"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    response = client.post("/api/v1/cohort-datasets", json=_request())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


@pytest.mark.parametrize(
    "definition_payload",
    ["{ truncated", json.dumps({"features": "not-an-array"})],
    ids=["invalid-json", "invalid-structure"],
)
def test_cohort_api_rejects_corrupt_feature_definition_manifest(
    tmp_path: Path, definition_payload: str
) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    for path in (processed / "features").rglob("feature_definitions.json"):
        path.write_text(definition_payload, encoding="utf-8")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    response = client.post("/api/v1/cohort-datasets", json=_request())

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
    # Held-out y values are kept only in the integrity-checked local prediction
    # artifact, never in the API metadata/report payload consumed by clients.
    assert "predictions" not in result
    assert '"y_true"' not in json.dumps(result)
    assert result["evaluation_scope"] == "DECLARED_GROUP_LOBO_TECHNICAL_EVALUATION"
    assert result["identity_verification_status"] == "NOT_ASSESSED"
    assert result["scientific_generalization_eligible"] is False
    assert result["battery_count"] is None
    assert result["declared_group_count"] == 3
    assert result["split_unit"] == "DECLARED_BATTERY_ID"
    assert result["group_identity_status"] == "NOT_ASSESSED"
    assert result["held_out_prediction_coverage"]["independent_unit"] == "DECLARED_BATTERY_ID"
    assert result["uncertainty_assessment"]["independent_group_count"] is None
    assert result["uncertainty_assessment"]["declared_group_count"] == 3
    assert any("operator-declared" in item for item in result["limitations"])
    assert result["declared_group_count"] == 3
    assert result["macro_by_strategy"]["DUMMY_MEAN"]["declared_group_count"] == 3
    assert "battery_count" not in result["macro_by_strategy"]["DUMMY_MEAN"]
    assert result["held_out_prediction_coverage"]["status"] == "COMPLETE"
    assert result["held_out_prediction_coverage"]["expected_declared_group_count"] == 3
    assert "expected_battery_count" not in result["held_out_prediction_coverage"]
    assert result["held_out_prediction_coverage"]["observed_declared_group_count_per_strategy"] == {
        "DUMMY_MEAN": 3
    }
    assert "observed_battery_count_per_strategy" not in result["held_out_prediction_coverage"]
    assert result["held_out_prediction_coverage"]["observed_prediction_rows"] == 6
    assert result["uncertainty_assessment"]["independent_unit"] == "DECLARED_BATTERY_ID"
    assert result["uncertainty_assessment"]["independent_group_count"] is None
    assert result["uncertainty_assessment"]["declared_group_count"] == 3
    assert result["uncertainty_assessment"]["confidence_interval"]["status"] == "NOT_ESTIMATED"
    assert result["leakage_audit"]["group_column"] == "battery_id"
    assert result["provenance"]["harmonization_policy_id"] == "POLICY::fixture"
    assert result["declared_group_results"][0]["cohort_id"] == "COHORT::fixture"
    assert result["declared_group_results"][0]["declared_group_id"]
    assert "battery_id" not in result["declared_group_results"][0]
    assert "battery_results" not in result
    assert Path(processed / result["artifacts"]["held_out_predictions"]).is_file()
    assert Path(processed / result["artifacts"]["split_assignments"]).is_file()
    assert Path(processed / result["artifacts"]["cohort_report_json"]).is_file()
    assert Path(processed / result["artifacts"]["cohort_report_html"]).is_file()
    report = json.loads(Path(processed / result["artifacts"]["cohort_report_json"]).read_text())
    html_report = Path(processed / result["artifacts"]["cohort_report_html"]).read_text()
    assert "predictions" not in report
    assert '"y_true"' not in json.dumps(report)
    assert '"y_true"' not in html_report
    assert report["uncertainty_assessment"] == result["uncertainty_assessment"]
    assert report["held_out_prediction_coverage"] == result["held_out_prediction_coverage"]
    predictions = pd.read_parquet(processed / result["artifacts"]["held_out_predictions"])
    assignments = pd.read_parquet(processed / result["artifacts"]["split_assignments"])
    assert {"cohort_id", "fold", "battery_id", "source_dataset_id"}.issubset(predictions.columns)
    assert {"y_true", "y_pred"}.issubset(predictions.columns)
    assert {"cohort_id", "fold", "battery_id", "source_dataset_id"}.issubset(assignments.columns)
    fetched = client.get(f"/api/v1/cohort-lobo-evaluations/{result['evaluation_id']}")
    assert fetched.status_code == 200
    assert "predictions" not in fetched.json()["data"]
    assert '"y_true"' not in json.dumps(fetched.json()["data"])
    assert fetched.json()["data"]["artifact_checksums"] == result["artifact_checksums"]


def test_cohort_api_keeps_multiple_experiments_together_in_battery_lobo(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A1", "CELL_A", "EXP_A1")
    _write_source(processed, "DS::A2", "CELL_A", "EXP_A2")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    payload = _request()
    payload["source_datasets"] = [
        {"source_dataset_id": "DS::A1", "battery_id": "CELL_A", "experiment_id": "EXP_A1"},
        {"source_dataset_id": "DS::A2", "battery_id": "CELL_A", "experiment_id": "EXP_A2"},
        {"source_dataset_id": "DS::B", "battery_id": "CELL_B", "experiment_id": "EXP_B"},
    ]
    payload["target_mapping"]["source_target_ids"] = {
        source_id: "soc_reference_percent" for source_id in ("DS::A1", "DS::A2", "DS::B")
    }
    payload["feature_mappings"][0]["source_feature_ids"] = {
        source_id: "peak_to_peak_v" for source_id in ("DS::A1", "DS::A2", "DS::B")
    }
    payload["unit_mapping"]["ultrasound_peak_to_peak"]["source_units"] = {
        source_id: "V" for source_id in ("DS::A1", "DS::A2", "DS::B")
    }
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))

    created = client.post("/api/v1/cohort-datasets", json=payload)

    assert created.status_code == 200, created.text
    cohort = created.json()["data"]
    assert cohort["battery_count"] == 2
    assert cohort["row_count"] == 6
    cohort_frame = pd.read_parquet(processed / cohort["output_path"])
    assert cohort_frame["measurement_event_id"].is_unique
    assert set(cohort_frame.loc[cohort_frame["battery_id"] == "CELL_A", "experiment_id"]) == {
        "EXP_A1",
        "EXP_A2",
    }
    assert cohort_frame.loc[cohort_frame["battery_id"] == "CELL_A", "source_dataset_id"].nunique() == 2

    evaluated = client.post(
        f"/api/v1/cohort-datasets/{cohort['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert evaluated.status_code == 200, evaluated.text
    result = evaluated.json()["data"]
    assert result["declared_group_count"] == 2
    assert result["held_out_prediction_coverage"]["expected_declared_group_count"] == 2
    assignments = pd.read_parquet(processed / result["artifacts"]["split_assignments"])
    cell_a_roles = assignments[assignments["battery_id"] == "CELL_A"].groupby("fold")["role"].unique()
    assert all(len(roles) == 1 for roles in cell_a_roles)
    assert assignments.loc[
        assignments["battery_id"] == "CELL_A", "source_dataset_id"
    ].nunique() == 2


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


def test_parser_provenance_failure_blocks_cohort_metadata_and_evaluation(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    parser_manifest = processed / "electrical/CELL_A/EXP_A/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")

    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    detail = client.get(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}"
    ).json()["data"]
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert listed[0]["status"] == "INTEGRITY_BLOCKED"
    assert listed[0]["row_count"] is None
    assert listed[0]["freshness_reasons"] == [
        "DS::A:SOURCE_PROVENANCE_INVALID:ELECTRICAL",
        "DS::A:SOURCE_RAW_MISMATCH:ELECTRICAL",
    ]
    assert detail["availability"] == "BLOCKED"
    assert detail["status"] == "INTEGRITY_BLOCKED"
    assert detail["row_count"] is None
    assert detail["fields"] == {
        "source_integrity_status": "INTEGRITY_BLOCKED",
        "freshness_reasons": [
            "DS::A:SOURCE_PROVENANCE_INVALID:ELECTRICAL",
            "DS::A:SOURCE_RAW_MISMATCH:ELECTRICAL",
        ],
    }
    assert evaluation.status_code == 409
    assert evaluation.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_upstream_label_change_marks_cohort_stale_and_blocks_reuse(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]

    label_path = processed / "labels" / "CELL_A" / "EXP_A" / "event_labels.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_A::ME::1", "CELL_A::ME::2"],
            "soc_reference_percent": [70.0, 90.0],
        }
    ).to_parquet(label_path, index=False)

    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    detail = client.get(f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}").json()["data"]
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )
    rematerialized = client.post("/api/v1/cohort-datasets", json=_request())

    assert listed[0]["status"] == "STALE_SOURCE"
    assert detail["availability"] == "STALE"
    assert detail["status"] == "STALE_SOURCE"
    assert evaluation.status_code == 409
    assert evaluation.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert rematerialized.status_code == 409
    assert rematerialized.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


def test_cohort_manifest_missing_a_source_fingerprint_is_stale(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    assert (
        client.get("/api/v1/cohort-datasets").json()["data"][0]["status"]
        == "READY_FOR_BATTERY_SPLIT"
    )
    manifest_path = processed / Path(created["output_path"]).with_name("cohort_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_artifacts"].pop("DS::A")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    detail = client.get(f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}").json()["data"]
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert listed[0]["status"] == "STALE_SOURCE"
    assert detail["status"] == "STALE_SOURCE"
    assert evaluation.status_code == 409
    assert evaluation.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_cohort_manifest_malformed_source_fingerprint_fails_closed(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    manifest_path = processed / Path(created["output_path"]).with_name("cohort_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_artifacts"]["DS::A"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = client.get("/api/v1/cohort-datasets")
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert listed.status_code == 200
    assert listed.json()["data"][0]["status"] == "STALE_SOURCE"
    assert evaluation.status_code == 409
    assert evaluation.json()["error"]["code"] == "INTEGRITY_ERROR"


@pytest.mark.parametrize(
    "tampered_field",
    [
        "cohort_dataset_id",
        "harmonization_policy_id",
        "identity_verification_status",
        "legacy_identity_status",
    ],
)
def test_cohort_manifest_identity_or_mapping_tampering_is_stale(
    tmp_path: Path, tampered_field: str
) -> None:
    processed = tmp_path / tampered_field / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    created = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    manifest_path = processed / Path(created["output_path"]).with_name("cohort_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tampered_field == "cohort_dataset_id":
        manifest[tampered_field] = "COHORT::tampered"
    elif tampered_field == "identity_verification_status":
        manifest[tampered_field] = "VERIFIED"
    elif tampered_field == "legacy_identity_status":
        manifest.pop("identity_verification_status")
    else:
        manifest[tampered_field] = "POLICY::tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    evaluation = client.post(
        f"/api/v1/cohort-datasets/{created['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    )

    assert listed[0]["status"] == "STALE_SOURCE"
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


def test_cached_cohort_lobo_is_blocked_when_source_parser_provenance_breaks(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    _write_source(processed, "DS::A", "CELL_A", "EXP_A")
    _write_source(processed, "DS::B", "CELL_B", "EXP_B")
    client = TestClient(create_app(processed_root=processed, raw_root=tmp_path / "raw"))
    cohort = client.post("/api/v1/cohort-datasets", json=_request()).json()["data"]
    result = client.post(
        f"/api/v1/cohort-datasets/{cohort['cohort_dataset_id']}/lobo-evaluations",
        json={"strategies": ["DUMMY_MEAN"]},
    ).json()["data"]

    invalid_manifest = processed / "electrical" / "CELL_A" / "EXP_A" / "parser_manifest.json"
    invalid_manifest.parent.mkdir(parents=True)
    invalid_manifest.write_text("[]", encoding="utf-8")
    response = client.get(
        f"/api/v1/cohort-lobo-evaluations/{result['evaluation_id']}"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert response.json()["error"]["details"]["source_integrity_status"] == (
        "INTEGRITY_BLOCKED"
    )
    assert "held_out_predictions" not in response.text


def test_source_definition_change_blocks_stale_dataset_from_cohort(tmp_path: Path) -> None:
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
    assert second_response.status_code == 409, second_response.text
    assert second_response.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"
    assert second_response.json()["error"]["details"]["reason"] == (
        "source dataset 'DS::A' is stale: FEATURE_SET_MANIFEST_OUTPUT_MISMATCH"
    )
    listed = client.get("/api/v1/cohort-datasets").json()["data"]
    assert [item["cohort_dataset_id"] for item in listed] == [
        first["cohort_dataset_id"]
    ]

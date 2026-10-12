from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_dataset(processed_root: Path, dataset_id: str) -> tuple[Path, Path, Path]:
    dataset_dir = processed_root / "datasets" / "CELL_TEST" / "EXP_TEST" / "SOC" / dataset_id
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_TEST::ME::1"],
            "battery_id": ["CELL_TEST"],
            "experiment_id": ["EXP_TEST"],
            "cycle_group_id": ["CYCLE::1"],
            "soc_reference_percent": [25.0],
            "peak_to_peak_v": [0.25],
        }
    ).to_parquet(dataset_path, index=False)

    feature_dir = processed_root / "features" / "CELL_TEST" / "EXP_TEST" / "FS::test"
    feature_dir.mkdir(parents=True)
    feature_path = feature_dir / "ultrasound_features.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["CELL_TEST::ME::1"], "peak_to_peak_v": [0.25]}
    ).to_parquet(feature_path, index=False)
    (feature_dir / "feature_definitions.json").write_text(
        json.dumps({"features": [{"name": "peak_to_peak_v", "version": "1.0.0", "unit": "V"}]}),
        encoding="utf-8",
    )
    definitions_path = feature_dir / "feature_definitions.json"
    analysis_slice_path = processed_root / "analysis_slices/CELL_TEST/EXP_TEST/AS::test.parquet"
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"analysis slice")
    waveform_store_path = processed_root / "waveform_inputs/CELL_TEST/EXP_TEST/waveforms.zarr"
    waveform_store_path.mkdir(parents=True)
    (waveform_store_path / "chunk.bin").write_bytes(b"waveform")
    feature_manifest_path = feature_dir / "feature_set_manifest.json"
    feature_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS::test",
                "battery_id": "CELL_TEST",
                "experiment_id": "EXP_TEST",
                "analysis_slice_id": "AS::test",
                "analysis_slice_path": str(analysis_slice_path.relative_to(processed_root)),
                "analysis_slice_checksum": _sha256(analysis_slice_path),
                "waveform_store_path": str(waveform_store_path.relative_to(processed_root)),
                "waveform_store_checksum": _tree_sha256(waveform_store_path),
                "output_paths": {
                    "features": str(feature_path.relative_to(processed_root)),
                    "definitions": str(definitions_path.relative_to(processed_root)),
                },
                "output_checksums": {
                    "features": _sha256(feature_path),
                    "definitions": _sha256(definitions_path),
                },
            }
        ),
        encoding="utf-8",
    )

    label_dir = processed_root / "labels" / "CELL_TEST" / "EXP_TEST"
    label_dir.mkdir(parents=True)
    label_path = label_dir / "event_labels.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["CELL_TEST::ME::1"], "soc_reference_percent": [25.0]}
    ).to_parquet(label_path, index=False)
    cycle_label_path = label_dir / "cycle_labels.parquet"
    pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [99.0]}).to_parquet(
        cycle_label_path, index=False
    )
    label_manifest_path = label_dir / "label_manifest.json"
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LB::test",
                "battery_id": "CELL_TEST",
                "experiment_id": "EXP_TEST",
                "output_paths": {
                    "event_labels": str(label_path.relative_to(processed_root)),
                    "cycle_labels": str(cycle_label_path.relative_to(processed_root)),
                },
                "output_checksums": {
                    "event_labels": _sha256(label_path),
                    "cycle_labels": _sha256(cycle_label_path),
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = {
        "dataset_id": dataset_id,
        "dataset_family": "SOC",
        "dataset_status": "READY_WITH_LIMITATIONS",
        "battery_id": "CELL_TEST",
        "experiment_id": "EXP_TEST",
        "target_name": "soc_reference_percent",
        "feature_set_id": "FS::test",
        "feature_set_path": str(feature_path.relative_to(processed_root)),
        "feature_set_checksum": _sha256(feature_path),
        "feature_set_manifest_path": str(feature_manifest_path.relative_to(processed_root)),
        "feature_set_manifest_checksum": _sha256(feature_manifest_path),
        "label_set_id": "LB::test",
        "label_set_path": str(label_path.relative_to(processed_root)),
        "label_set_checksum": _sha256(label_path),
        "label_set_manifest_path": str(label_manifest_path.relative_to(processed_root)),
        "label_set_manifest_checksum": _sha256(label_manifest_path),
        "output_checksum": _sha256(dataset_path),
        "predictor_columns": ["peak_to_peak_v"],
        "target_column": "soc_reference_percent",
        "eligible_rows": 1,
    }
    (dataset_dir / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dataset_path, feature_path, label_path


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize(
    "stale_source",
    [
        "changed_label",
        "missing_label",
        "changed_feature",
        "missing_feature",
        "missing_label_checksum",
        "missing_feature_checksum",
        "missing_upstream_provenance",
        "changed_label_manifest_id",
        "tampered_label_manifest_output",
        "changed_cycle_label",
        "missing_cycle_label",
        "missing_cycle_label_checksum",
        "tampered_cycle_label_manifest_output",
        "changed_dataset_battery_identity",
        "changed_dataset_target_identity",
        "changed_dataset_predictor_identity",
        "changed_dataset_row_identity",
        "malformed_dataset_family",
        "missing_label_manifest",
        "path_escape",
    ],
)
def test_dataset_api_fails_closed_when_label_source_is_stale(
    tmp_path: Path, stale_source: str
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::freshness-test"
    dataset_path, feature_path, label_path = _write_dataset(processed_root, dataset_id)
    manifest_path = next(
        path
        for path in (processed_root / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == dataset_id
    )

    if stale_source in {
        "changed_dataset_battery_identity",
        "changed_dataset_target_identity",
        "changed_dataset_predictor_identity",
        "changed_dataset_row_identity",
        "malformed_dataset_family",
    }:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if stale_source == "changed_dataset_battery_identity":
            manifest["battery_id"] = "CELL_OTHER"
        elif stale_source == "changed_dataset_target_identity":
            manifest["target_column"] = "peak_to_peak_v"
        elif stale_source == "changed_dataset_predictor_identity":
            manifest["predictor_columns"] = ["not_in_dataset.parquet"]
        elif stale_source == "malformed_dataset_family":
            manifest["dataset_family"] = ["SOC"]
        else:
            frame = pd.read_parquet(dataset_path)
            frame["battery_id"] = "CELL_OTHER"
            frame.to_parquet(dataset_path, index=False)
            manifest["output_checksum"] = _sha256(dataset_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif stale_source == "changed_label":
        pd.DataFrame(
            {"measurement_event_id": ["CELL_TEST::ME::1"], "soc_reference_percent": [75.0]}
        ).to_parquet(label_path, index=False)
    elif stale_source == "missing_label":
        label_path.unlink()
    elif stale_source == "changed_cycle_label":
        cycle_label_path = label_path.parent / "cycle_labels.parquet"
        pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [85.0]}).to_parquet(
            cycle_label_path, index=False
        )
    elif stale_source == "missing_cycle_label":
        (label_path.parent / "cycle_labels.parquet").unlink()
    elif stale_source == "changed_feature":
        pd.DataFrame(
            {"measurement_event_id": ["CELL_TEST::ME::1"], "peak_to_peak_v": [0.75]}
        ).to_parquet(feature_path, index=False)
    elif stale_source == "missing_feature":
        feature_path.unlink()
    elif stale_source in {"missing_label_checksum", "missing_feature_checksum"}:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checksum_key = (
            "label_set_checksum"
            if stale_source == "missing_label_checksum"
            else "feature_set_checksum"
        )
        manifest.pop(checksum_key)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif stale_source == "missing_upstream_provenance":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in (
            "feature_set_id",
            "feature_set_path",
            "feature_set_checksum",
            "label_set_id",
            "label_set_path",
            "label_set_checksum",
            "label_set_manifest_path",
            "label_set_manifest_checksum",
        ):
            manifest.pop(key)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif stale_source in {
        "changed_label_manifest_id",
        "tampered_label_manifest_output",
        "missing_cycle_label_checksum",
        "tampered_cycle_label_manifest_output",
        "missing_label_manifest",
    }:
        label_manifest_path = label_path.parent / "label_manifest.json"
        if stale_source == "missing_label_manifest":
            label_manifest_path.unlink()
        else:
            label_manifest = json.loads(label_manifest_path.read_text(encoding="utf-8"))
            if stale_source == "changed_label_manifest_id":
                label_manifest["label_set_id"] = "LB::different"
            elif stale_source == "tampered_label_manifest_output":
                label_manifest["output_checksums"]["event_labels"] = "0" * 64
            elif stale_source == "missing_cycle_label_checksum":
                label_manifest["output_checksums"].pop("cycle_labels")
            else:
                label_manifest["output_checksums"]["cycle_labels"] = "0" * 64
            label_manifest_path.write_text(json.dumps(label_manifest), encoding="utf-8")
    else:
        outside_path = tmp_path / "outside-labels.parquet"
        pd.DataFrame(
            {"measurement_event_id": ["CELL_TEST::ME::1"], "soc_reference_percent": [25.0]}
        ).to_parquet(outside_path, index=False)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["label_set_path"] = "../../outside-labels.parquet"
        manifest["label_set_checksum"] = _sha256(outside_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    catalogue = client.get("/api/v1/datasets").json()["data"]
    listed = next(item for item in catalogue if item["dataset_id"] == dataset_id)
    detail = client.get(f"/api/v1/datasets/{dataset_id}").json()["data"]

    assert listed["dataset_status"] == "STALE_SOURCE"
    assert detail["availability"] == "STALE"
    assert detail["status"] == "STALE_SOURCE"
    if stale_source == "changed_label_manifest_id":
        assert "LABEL_SET_MANIFEST_CHECKSUM_MISMATCH" in detail["fields"]["freshness_reasons"]
        assert "LABEL_SET_MANIFEST_IDENTITY_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "tampered_label_manifest_output":
        assert "LABEL_SET_MANIFEST_CHECKSUM_MISMATCH" in detail["fields"]["freshness_reasons"]
        assert "LABEL_SET_MANIFEST_OUTPUT_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source in {
        "changed_cycle_label",
        "missing_cycle_label",
        "missing_cycle_label_checksum",
        "tampered_cycle_label_manifest_output",
    }:
        assert "LABEL_SET_MANIFEST_OUTPUT_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "missing_label_manifest":
        assert "LABEL_SET_MANIFEST_MISSING" in detail["fields"]["freshness_reasons"]
    elif stale_source == "changed_dataset_battery_identity":
        assert "DATASET_IDENTITY_PATH_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "changed_dataset_target_identity":
        assert "DATASET_TARGET_IDENTITY_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "changed_dataset_predictor_identity":
        assert "DATASET_COLUMN_CONTRACT_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "changed_dataset_row_identity":
        assert "DATASET_ROW_IDENTITY_MISMATCH" in detail["fields"]["freshness_reasons"]
    elif stale_source == "malformed_dataset_family":
        assert "DATASET_IDENTITY_FIELDS_INVALID" in detail["fields"]["freshness_reasons"]
        assert "DATASET_TARGET_IDENTITY_MISMATCH" in detail["fields"]["freshness_reasons"]
    assert dataset_path.is_file()
    split_response = client.post(
        "/api/v1/splits",
        json={
            "battery_id": "CELL_TEST",
            "experiment_id": "EXP_TEST",
            "dataset_id": dataset_id,
        },
    )
    assert split_response.status_code == 409
    assert split_response.json()["error"]["code"] == (
        "INTEGRITY_ERROR"
        if stale_source == "changed_dataset_battery_identity"
        else "SCIENTIFIC_READINESS_BLOCKED"
    )
    baseline_response = client.post(
        "/api/v1/models/baseline-runs",
        json={
            "battery_id": "CELL_TEST",
            "experiment_id": "EXP_TEST",
            "strategy": "RIDGE",
            "dataset_id": dataset_id,
            "split_id": "SPLIT::stale",
            "fold_index": 0,
            "selection_id": "SEL::stale",
            "selected_features": ["peak_to_peak_v"],
        },
    )
    assert baseline_response.status_code == 409
    assert baseline_response.json()["error"]["code"] == (
        "INTEGRITY_ERROR"
        if stale_source == "changed_dataset_battery_identity"
        else "SCIENTIFIC_READINESS_BLOCKED"
    )


def test_dataset_api_rejects_legacy_reference_label_schema_version(tmp_path: Path) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::legacy-label-schema-test"
    _dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    dataset_manifest_path = next(
        path
        for path in (processed_root / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == dataset_id
    )
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    label_manifest_path = processed_root / "labels/CELL_TEST/EXP_TEST/label_manifest.json"
    label_manifest = json.loads(label_manifest_path.read_text(encoding="utf-8"))
    label_manifest.update(
        {
            "label_engine_name": "reference_label_engine",
            "label_engine_version": "0.2.0",
            "label_definition_version": "0.2.0",
        }
    )
    label_manifest_path.write_text(json.dumps(label_manifest), encoding="utf-8")
    dataset_manifest["label_set_manifest_checksum"] = _sha256(label_manifest_path)
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))
    detail = client.get(f"/api/v1/datasets/{dataset_id}").json()["data"]

    assert detail["availability"] == "STALE"
    assert "LABEL_SET_ENGINE_VERSION_UNSUPPORTED" in detail["fields"]["freshness_reasons"]
    assert "LABEL_SET_DEFINITION_VERSION_UNSUPPORTED" in detail["fields"]["freshness_reasons"]


def test_dataset_api_marks_output_checksum_mismatch_stale(tmp_path: Path) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::output-checksum-test"
    dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_TEST::ME::1"],
            "battery_id": ["CELL_TEST"],
            "experiment_id": ["EXP_TEST"],
            "soc_reference_percent": [90.0],
            "peak_to_peak_v": [0.9],
        }
    ).to_parquet(dataset_path, index=False)
    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    detail = client.get(f"/api/v1/datasets/{dataset_id}").json()["data"]

    assert detail["availability"] == "STALE"
    assert detail["status"] == "STALE_SOURCE"


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("manifest_identity", "FEATURE_SET_MANIFEST_IDENTITY_MISMATCH"),
        ("manifest_output", "FEATURE_SET_MANIFEST_OUTPUT_MISMATCH"),
        ("changed_definitions", "FEATURE_SET_MANIFEST_OUTPUT_MISMATCH"),
        ("changed_slice", "FEATURE_SET_ANALYSIS_SLICE_CHECKSUM_MISMATCH"),
        ("changed_waveforms", "FEATURE_SET_WAVEFORM_STORE_CHECKSUM_MISMATCH"),
        ("missing_manifest", "FEATURE_SET_MANIFEST_MISSING"),
        ("missing_pin", "FEATURE_SET_MANIFEST_PROVENANCE_MISSING"),
    ],
)
def test_dataset_api_fails_closed_when_feature_set_manifest_or_inputs_change(
    tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::feature-manifest-test"
    _dataset_path, feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    feature_manifest_path = feature_path.parent / "feature_set_manifest.json"
    manifest_path = next(
        path
        for path in (processed_root / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == dataset_id
    )
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "manifest_identity":
        payload = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
        payload["feature_set_id"] = "FS::replacement"
        feature_manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "manifest_output":
        payload = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
        payload["output_checksums"]["features"] = "0" * 64
        feature_manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "changed_definitions":
        (feature_path.parent / "feature_definitions.json").write_text(
            '{"features":["substituted"]}', encoding="utf-8"
        )
    elif mutation == "changed_slice":
        (processed_root / "analysis_slices/CELL_TEST/EXP_TEST/AS::test.parquet").write_bytes(
            b"replaced analysis slice"
        )
    elif mutation == "changed_waveforms":
        (
            processed_root
            / "waveform_inputs/CELL_TEST/EXP_TEST/waveforms.zarr/chunk.bin"
        ).write_bytes(b"replaced waveform")
    elif mutation == "missing_manifest":
        feature_manifest_path.unlink()
    else:
        dataset_manifest.pop("feature_set_manifest_path")
        manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))
    detail = client.get(f"/api/v1/datasets/{dataset_id}").json()["data"]

    assert detail["availability"] == "STALE"
    assert expected_reason in detail["fields"]["freshness_reasons"]


def test_dataset_artifact_hides_scientific_metadata_when_parser_source_invalid(
    tmp_path: Path,
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::parser-integrity-test"
    _dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    parser_manifest = processed_root / "electrical/CELL_TEST/EXP_TEST/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    catalogue = client.get("/api/v1/datasets").json()["data"]
    listed = next(item for item in catalogue if item["dataset_id"] == dataset_id)
    detail_response = client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]

    assert listed["dataset_status"] == "STALE_SOURCE"
    assert listed["eligible_rows"] is None
    assert "SOURCE_PROVENANCE_INVALID:ELECTRICAL" in listed["freshness_reasons"]
    assert detail["status"] == "INTEGRITY_BLOCKED"
    assert detail["availability"] == "BLOCKED"
    assert detail["row_count"] is None
    assert detail["fields"] == {
        "source_integrity_status": "INTEGRITY_BLOCKED",
        "freshness_reasons": [
            "SOURCE_PROVENANCE_INVALID:ELECTRICAL",
            "SOURCE_RAW_MISMATCH:ELECTRICAL",
        ],
    }


def test_split_artifact_is_blocked_when_its_dataset_parser_source_is_invalid(
    tmp_path: Path,
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::split-parser-integrity-test"
    _write_dataset(processed_root, dataset_id)
    parser_manifest = processed_root / "electrical/CELL_TEST/EXP_TEST/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    split_id = "SPLIT::split-parser-integrity-test"
    split_dir = processed_root / "splits/CELL_TEST/EXP_TEST" / split_id
    split_dir.mkdir(parents=True)
    (split_dir / "split_manifest.json").write_text(
        json.dumps({"split_id": split_id, "dataset_id": dataset_id, "readiness_status": "READY"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    response = client.get(f"/api/v1/artifacts/{split_id}")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "artifact_id": split_id,
        "artifact_type": "SPLIT",
        "availability": "BLOCKED",
        "status": "INTEGRITY_BLOCKED",
        "row_count": None,
        "preview": [],
        "fields": {
            "source_integrity_status": "INTEGRITY_BLOCKED",
            "dataset_id": dataset_id,
            "freshness_reasons": [
                "SOURCE_PROVENANCE_INVALID:ELECTRICAL",
                "SOURCE_RAW_MISMATCH:ELECTRICAL",
            ],
            "invalid_modalities": ["electrical"],
            "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
        },
    }


def test_split_detail_and_fold_inventory_follow_dataset_and_split_freshness(
    tmp_path: Path,
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::split-freshness-test"
    dataset_path, _feature_path, label_path = _write_dataset(processed_root, dataset_id)
    dataset_manifest_path = dataset_path.parent / "dataset_manifest.json"
    split_id = "SPLIT::split-freshness-test"
    split_dir = processed_root / "splits/CELL_TEST/EXP_TEST" / dataset_id / split_id
    split_dir.mkdir(parents=True)
    assignments_path = split_dir / "split_assignments.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_TEST::ME::1"],
            "cycle_group_id": ["CYCLE::1"],
            "fold": ["fold1"],
            "role": ["TRAIN"],
            "strategy": ["TRAIN_ONLY"],
            "dataset_id": [dataset_id],
            "split_id": [split_id],
        }
    ).to_parquet(assignments_path, index=False)
    audit_path = split_dir / "leakage_audit.json"
    audit_path.write_text("{}", encoding="utf-8")
    readiness_path = split_dir / "evaluation_readiness.json"
    readiness_path.write_text("{}", encoding="utf-8")
    output_checksums = {
        "split_assignments": _sha256(assignments_path),
        "leakage_audit": _sha256(audit_path),
        "evaluation_readiness": _sha256(readiness_path),
    }
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "split_id": split_id,
                "dataset_id": dataset_id,
                "battery_id": "CELL_TEST",
                "experiment_id": "EXP_TEST",
                "group_column": "cycle_group_id",
                "split_unit": "CYCLE",
                "strategy": "TRAIN_ONLY",
                "group_counts": {"CYCLE::1": 1},
                "group_count": 1,
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
                    "dataset_parquet": _sha256(dataset_path),
                    "dataset_manifest": _sha256(dataset_manifest_path),
                },
                "readiness_status": "READY_FOR_LIMITED_EVALUATION",
                "output_checksums": output_checksums,
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    current_detail = client.get(f"/api/v1/splits/{split_id}").json()["data"]
    current_folds = client.get(
        f"/api/v1/experiments/CELL_TEST/EXP_TEST/splits/{split_id}/folds"
    )
    assert current_detail["availability"] == "AVAILABLE"
    assert current_detail["fields"]["output_checksums_verified"] is True
    assert current_folds.status_code == 200

    original_assignments = pd.read_parquet(assignments_path)
    forged_assignments = original_assignments.copy()
    forged_assignments.loc[0, "measurement_event_id"] = "CELL_TEST::ME::forged"
    forged_assignments.to_parquet(assignments_path, index=False)
    split_manifest_path = split_dir / "split_manifest.json"
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    split_manifest["output_checksums"]["split_assignments"] = _sha256(assignments_path)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")

    invalid_detail = client.get(f"/api/v1/splits/{split_id}").json()["data"]
    invalid_folds = client.get(
        f"/api/v1/experiments/CELL_TEST/EXP_TEST/splits/{split_id}/folds"
    )
    assert invalid_detail["availability"] == "BLOCKED"
    assert invalid_detail["status"] == "INTEGRITY_BLOCKED"
    assert "SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:fold1" in invalid_detail["fields"][
        "freshness_reasons"
    ]
    assert invalid_folds.status_code == 409

    original_assignments.to_parquet(assignments_path, index=False)
    split_manifest["output_checksums"]["split_assignments"] = _sha256(assignments_path)
    split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")

    pd.DataFrame(
        {"measurement_event_id": ["CELL_TEST::ME::1"], "soc_reference_percent": [75.0]}
    ).to_parquet(label_path, index=False)
    stale_detail = client.get(f"/api/v1/splits/{split_id}").json()["data"]
    stale_folds = client.get(
        f"/api/v1/experiments/CELL_TEST/EXP_TEST/splits/{split_id}/folds"
    )
    listed = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/splits").json()["data"]["splits"]
    stale_listing = next(item for item in listed if item["split_id"] == split_id)

    assert stale_detail["availability"] == "STALE"
    assert stale_detail["status"] == "STALE_SOURCE"
    assert "LABEL_SOURCE_CHECKSUM_MISMATCH" in stale_detail["fields"]["freshness_reasons"]
    assert stale_folds.status_code == 409
    assert stale_folds.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"
    assert stale_listing["availability"] == "STALE"
    assert stale_listing["status"] == "STALE_SOURCE"


def test_split_artifact_blocks_tampered_split_outputs(tmp_path: Path) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::split-output-integrity-test"
    dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    dataset_manifest_path = dataset_path.parent / "dataset_manifest.json"
    split_id = "SPLIT::split-output-integrity-test"
    split_dir = processed_root / "splits/CELL_TEST/EXP_TEST" / dataset_id / split_id
    split_dir.mkdir(parents=True)
    outputs = {
        "split_assignments": split_dir / "split_assignments.parquet",
        "leakage_audit": split_dir / "leakage_audit.json",
        "evaluation_readiness": split_dir / "evaluation_readiness.json",
    }
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_TEST::ME::1"],
            "cycle_group_id": ["CYCLE::1"],
            "fold": ["fold1"],
            "role": ["TRAIN"],
            "strategy": ["TRAIN_ONLY"],
        }
    ).to_parquet(outputs["split_assignments"], index=False)
    outputs["leakage_audit"].write_text("{}", encoding="utf-8")
    outputs["evaluation_readiness"].write_text("{}", encoding="utf-8")
    manifest = {
        "split_id": split_id,
        "dataset_id": dataset_id,
        "battery_id": "CELL_TEST",
        "experiment_id": "EXP_TEST",
        "source_checksums": {
            "dataset_parquet": _sha256(dataset_path),
            "dataset_manifest": _sha256(dataset_manifest_path),
        },
        "readiness_status": "READY_FOR_LIMITED_EVALUATION",
        "output_checksums": {name: _sha256(path) for name, path in outputs.items()},
    }
    (split_dir / "split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    outputs["leakage_audit"].write_text('{"tampered": true}', encoding="utf-8")
    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))

    detail = client.get(f"/api/v1/splits/{split_id}").json()["data"]
    folds = client.get(
        f"/api/v1/experiments/CELL_TEST/EXP_TEST/splits/{split_id}/folds"
    )

    assert detail["availability"] == "BLOCKED"
    assert detail["status"] == "INTEGRITY_BLOCKED"
    assert "SPLIT_OUTPUT_CHECKSUM_MISMATCH:leakage_audit" in detail["fields"][
        "freshness_reasons"
    ]
    assert folds.status_code == 409
    assert folds.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_split_artifact_is_stale_when_dataset_bytes_change_under_same_id(
    tmp_path: Path,
) -> None:
    processed_root = tmp_path / "processed"
    dataset_id = "DS::same-id-content-change"
    dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    dataset_manifest_path = dataset_path.parent / "dataset_manifest.json"
    split_id = "SPLIT::same-id-content-change"
    split_dir = processed_root / "splits/CELL_TEST/EXP_TEST" / dataset_id / split_id
    split_dir.mkdir(parents=True)
    outputs = {
        "split_assignments": split_dir / "split_assignments.parquet",
        "leakage_audit": split_dir / "leakage_audit.json",
        "evaluation_readiness": split_dir / "evaluation_readiness.json",
    }
    pd.DataFrame(
        {"measurement_event_id": ["CELL_TEST::ME::1"], "fold": ["0"], "role": ["TRAIN"]}
    ).to_parquet(outputs["split_assignments"], index=False)
    outputs["leakage_audit"].write_text("{}", encoding="utf-8")
    outputs["evaluation_readiness"].write_text("{}", encoding="utf-8")
    split_manifest = {
        "split_id": split_id,
        "dataset_id": dataset_id,
        "battery_id": "CELL_TEST",
        "experiment_id": "EXP_TEST",
        "readiness_status": "READY_FOR_LIMITED_EVALUATION",
        "source_checksums": {
            "dataset_parquet": _sha256(dataset_path),
            "dataset_manifest": _sha256(dataset_manifest_path),
        },
        "output_checksums": {name: _sha256(path) for name, path in outputs.items()},
    }
    (split_dir / "split_manifest.json").write_text(json.dumps(split_manifest), encoding="utf-8")

    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_TEST::ME::1"],
            "battery_id": ["CELL_TEST"],
            "experiment_id": ["EXP_TEST"],
            "soc_reference_percent": [25.0],
            "peak_to_peak_v": [0.75],
        }
    ).to_parquet(dataset_path, index=False)
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    dataset_manifest["output_checksum"] = _sha256(dataset_path)
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    client = TestClient(create_app(processed_root=processed_root, raw_root=tmp_path / "raw"))
    detail = client.get(f"/api/v1/splits/{split_id}").json()["data"]

    assert detail["availability"] == "STALE"
    assert detail["status"] == "STALE_SOURCE"
    assert "SPLIT_SOURCE_DATASET_CHANGED:dataset_parquet" in detail["fields"]["freshness_reasons"]
    assert "SPLIT_SOURCE_DATASET_CHANGED:dataset_manifest" in detail["fields"]["freshness_reasons"]


def test_workflow_freshness_requires_tof_provenance_only_when_tof_is_selected(
    tmp_path: Path,
) -> None:
    from battery_workbench.api.workflow_context import _freshness_of_dataset

    processed_root = tmp_path / "processed"
    dataset_id = "DS::tof-provenance-test"
    _dataset_path, _feature_path, _label_path = _write_dataset(processed_root, dataset_id)
    manifest_path = next(
        path
        for path in (processed_root / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == dataset_id
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selected_features"] = ["peak_to_peak_v"]
    assert _freshness_of_dataset(processed_root, manifest, manifest_path)["status"] == "CURRENT"

    manifest["selected_features"] = ["tof_us"]
    assert _freshness_of_dataset(processed_root, manifest, manifest_path) == {
        "status": "LEGACY",
        "reasons": ["CANONICAL_TOF_PROVENANCE_MISSING"],
    }

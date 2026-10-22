import csv
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"


def test_targets_api_keeps_events_visible_when_label_artifact_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    import pandas as pd

    processed_root = tmp_path / "processed"
    events_dir = processed_root / "multimodal" / "CELL_NO_LABELS" / "EXP_001"
    events_dir.mkdir(parents=True)
    events_path = events_dir / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::U001::0", "ME::U001::1"],
            "analysis_eligible": [True, True],
        }
    ).to_parquet(events_path, index=False)
    sync_dir = processed_root / "synchronization" / "CELL_NO_LABELS" / "EXP_001"
    sync_dir.mkdir(parents=True)
    inputs = {
        "aligned": sync_dir / "aligned.parquet",
        "sync_candidates": sync_dir / "candidates.parquet",
        "electrical_records": processed_root
        / "electrical/CELL_NO_LABELS/EXP_001/records.parquet",
    }
    for path in inputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    event_candidates = events_dir / "measurement_event_candidates.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(event_candidates, index=False)
    (events_dir / "measurement_event_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_NO_LABELS",
                "experiment_id": "EXP_001",
                "input_paths": {key: str(path) for key, path in inputs.items()},
                "input_checksums": {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in inputs.items()
                },
                "output_paths": {
                    "events": str(events_path),
                    "candidates": str(event_candidates),
                },
                "output_checksums": {
                    "events": hashlib.sha256(events_path.read_bytes()).hexdigest(),
                    "candidates": hashlib.sha256(event_candidates.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    # This test isolates target/label availability semantics. Parser-source and
    # timebase-chain freshness have dedicated tests and are not synthesized here.
    from battery_workbench.api.routes import features_v2

    monkeypatch.setattr(features_v2, "assert_current_timebase_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(features_v2, "_assert_source_provenance", lambda *_args, **_kwargs: None)

    response = TestClient(app).get(
        "/api/v1/experiments/CELL_NO_LABELS/EXP_001/targets"
    )

    assert response.status_code == 200
    targets = {item["target_id"]: item for item in response.json()["data"]["targets"]}
    soc = targets["reference_soc_percent"]
    assert soc["readiness"] == "UNAVAILABLE"
    assert soc["coverage"] == {"valid": 0, "total": 2}
    assert "no reference SOC labels" in soc["limitation"]
    assert "标签生成流程" in soc["limitation_zh"]

    labels_dir = processed_root / "labels" / "CELL_NO_LABELS" / "EXP_001"
    labels_dir.mkdir(parents=True)
    input_paths = {
        "measurement_events": events_path,
        "records": processed_root / "electrical/CELL_NO_LABELS/EXP_001/records.parquet",
        "cycles": processed_root / "electrical/CELL_NO_LABELS/EXP_001/cycles.parquet",
        "steps": processed_root / "electrical/CELL_NO_LABELS/EXP_001/steps.parquet",
    }
    for path in input_paths.values():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    event_labels = labels_dir / "event_labels.parquet"
    cycle_labels = labels_dir / "cycle_labels.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": pd.Series(dtype="str"),
            "soc_reference_percent": pd.Series(dtype="float64"),
        }
    ).to_parquet(event_labels, index=False)
    pd.DataFrame({"cycle_index_raw": pd.Series(dtype="int64")}).to_parquet(
        cycle_labels, index=False
    )
    (labels_dir / "label_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_NO_LABELS",
                "experiment_id": "EXP_001",
                "label_set_id": "LS::fixture",
                "input_paths": {key: str(path) for key, path in input_paths.items()},
                "input_checksums": {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in input_paths.items()
                },
                "output_paths": {"event_labels": str(event_labels)},
                "output_checksums": {
                    "event_labels": hashlib.sha256(event_labels.read_bytes()).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    event_labels.write_bytes(b"tampered")
    tampered_response = TestClient(app).get(
        "/api/v1/experiments/CELL_NO_LABELS/EXP_001/targets"
    )
    assert tampered_response.status_code == 409
    assert tampered_response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:event_labels" in tampered_response.text


def test_real_cell001_targets_expose_grain_method_sources_and_unknown_uncertainty(
    tmp_path: Path,
) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).get("/api/v1/experiments/CELL_001/EXP_001/targets")
    assert response.status_code == 200
    targets = {item["target_id"]: item for item in response.json()["data"]["targets"]}

    soc = targets["reference_soc_percent"]["provenance"]
    assert soc["target_grain"] == "MEASUREMENT_EVENT"
    assert soc["independent_unit"] == "BATTERY"
    assert soc["method_id"] == "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED"
    assert soc["method_version"] == "0.2.0"
    assert "Q_charged_since_empty" in soc["definition"]
    assert soc["source_assets"] == [
        {
            "asset_id": "E001",
            "source_reference": "batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
            "sha256": "8536d3959db6efc73cdbc30903b33f8c6a429385663597832e4d918459dbc608",
        }
    ]
    assert soc["uncertainty"]["status"] == "UNKNOWN"
    assert soc["uncertainty"]["reason"]

    temperature = targets["temperature_c"]
    assert temperature["provenance"]["target_grain"] == "MEASUREMENT_EVENT"
    assert temperature["provenance"]["method_id"] == "AUX_TEMP_RECORD_INDEX_JOIN"
    event_manifest = json.loads(
        (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_event_manifest.json").read_text()
    )
    assert temperature["provenance"]["method_version"] == event_manifest["builder_version"]
    assert "record_index_raw" in temperature["provenance"]["definition"]
    assert temperature["provenance"]["observed_channels"] == ["T1"]
    assert temperature["provenance"]["uncertainty"]["status"] == "UNKNOWN"
    assert temperature["readiness"] == "BLOCKED_BY_VALIDATION"

    soh = targets["soh_capacity_reference_percent"]
    assert soh["provenance"]["target_grain"] == "CYCLE"
    assert soh["provenance"]["method_id"] == "CAPACITY_BASELINE_RATIO"
    assert soh["provenance"]["method_version"] == "0.1.0"
    assert "Q_discharge_measured(cycle) / Q_ref" in soh["provenance"]["definition"]
    assert soh["provenance"]["uncertainty"]["status"] == "UNKNOWN"
    assert soh["coverage"]["independent_states"] == 2
    assert soh["readiness"] == "NOT_READY"


def _source_validation_request(
    *,
    sha256: str,
    source_reference: str,
    target_id: str = "reference_soc_percent",
    minimum_independent_states: int | None = None,
) -> dict:
    body = {
        "battery_ids": ["CELL_001"],
        "experiment_ids": ["EXP_001"],
        "target_id": target_id,
        "target_grain": "MEASUREMENT_EVENT"
        if target_id == "reference_soc_percent"
        else "CYCLE"
        if target_id == "soh_capacity_reference_percent"
        else "MEASUREMENT_EVENT",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL"
            if target_id == "reference_soc_percent"
            else "DERIVED_HEALTH_STATE"
            if target_id == "soh_capacity_reference_percent"
            else "DIRECT_MEASUREMENT",
            "method_id": "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED"
            if target_id == "reference_soc_percent"
            else "CAPACITY_BASELINE_RATIO"
            if target_id == "soh_capacity_reference_percent"
            else "AUX_TEMP_RECORD_INDEX_JOIN",
            "method_version": "0.2.0"
            if target_id != "soh_capacity_reference_percent"
            else "0.1.0",
            "definition": "Reference SOC is segment-normalized from charge throughput."
            if target_id == "reference_soc_percent"
            else "SOH is the measured discharge capacity divided by the reference capacity."
            if target_id == "soh_capacity_reference_percent"
            else "Temperature is the selected auxiliary channel record.",
            "unit": "percent"
            if target_id != "temperature_c"
            else "celsius",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": source_reference,
                    "sha256": sha256,
                }
            ],
            "uncertainty": {
                "status": "UNKNOWN",
                "reason": "The source protocol does not report a validated uncertainty estimate.",
            },
        },
    }
    if minimum_independent_states is not None:
        body["minimum_independent_states"] = minimum_independent_states
    return body


def test_target_source_evidence_preflight_matches_manifest_and_raw_checksum(tmp_path: Path) -> None:
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json=_source_validation_request(
            sha256=checksum,
            source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
        ),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "SOURCE_EVIDENCE_VERIFIED"
    assert payload["materialization_enabled"] is False
    assert payload["source_integrity"] == "VERIFIED"
    assert payload["label_source_semantics"] == "NOT_ASSESSED"
    assert payload["target_readiness"] == "NOT_ASSESSED"
    assert payload["verified_sources"] == [
        {
            "asset_id": "E001",
            "verified": True,
            "sha256": checksum,
            "parser_provenance": "NOT_AVAILABLE",
        }
    ]
    assert not (tmp_path / "processed" / "target-datasets").exists()


@pytest.mark.parametrize(
    "target_id",
    ["reference_soc_percent", "temperature_c", "soh_capacity_reference_percent"],
)
def test_target_source_evidence_rejects_ultrasound_asset_as_label_source(
    target_id: str, tmp_path: Path
) -> None:
    source = REPO / (
        "data/raw/batteries/CELL_001/EXP_001/ultrasound/"
        "export - 2024.01.06 - 21.03.01.txt"
    )
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    body = _source_validation_request(
        sha256=checksum,
        source_reference=(
            "batteries/CELL_001/EXP_001/ultrasound/"
            "export - 2024.01.06 - 21.03.01.txt"
        ),
    )
    body["target_id"] = target_id
    if target_id == "temperature_c":
        body["label_provenance"]["semantic_type"] = "DIRECT_MEASUREMENT"
        body["label_provenance"]["unit"] = "celsius"
    elif target_id == "soh_capacity_reference_percent":
        body["target_grain"] = "CYCLE"
        body["minimum_independent_states"] = 3
        body["label_provenance"]["semantic_type"] = "DERIVED_HEALTH_STATE"
    else:
        body["minimum_independent_states"] = None
    body["label_provenance"]["source_references"][0]["asset_id"] = "U001"
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence", json=body
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "electrical DataAsset" in response.json()["error"]["message"]


def test_target_source_evidence_preflight_openapi_types_every_readiness_boundary(
    tmp_path: Path,
) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    operation = app.openapi()["paths"][
        "/api/v1/target-datasets/validate-source-evidence"
    ]["post"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("TargetSourceEvidenceValidationEnvelope")
    components = app.openapi()["components"]["schemas"]
    data_ref = components["TargetSourceEvidenceValidationEnvelope"]["properties"]["data"][
        "$ref"
    ]
    data_schema = components[data_ref.rsplit("/", 1)[-1]]
    assert data_schema["properties"]["label_source_semantics"]["const"] == "NOT_ASSESSED"
    assert data_schema["properties"]["target_readiness"]["const"] == "NOT_ASSESSED"
    assert data_schema["properties"]["materialization_enabled"]["const"] is False


def test_target_source_evidence_disambiguates_reused_asset_ids_by_registered_path(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    manifest = raw_root / "manifests" / "data_assets.csv"
    entries = [
        ("CELL_A", "batteries/CELL_A/EXP_001/electrical/source.xlsx", b"cell A source"),
        ("CELL_B", "batteries/CELL_B/EXP_001/electrical/source.xlsx", b"cell B source"),
    ]
    for _battery_id, relative_path, content in entries:
        path = raw_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        for battery_id, relative_path, _content in entries:
            writer.writerow(["E001", battery_id, "EXP_001", "electrical", relative_path])
    body = _source_validation_request(
        sha256=hashlib.sha256(entries[0][2]).hexdigest(),
        source_reference=entries[0][1],
    )
    body["battery_ids"] = ["CELL_A", "CELL_B"]
    body["experiment_ids"] = ["EXP_001", "EXP_001"]
    second = dict(body["label_provenance"]["source_references"][0])
    second["source_reference"] = entries[1][1]
    second["sha256"] = hashlib.sha256(entries[1][2]).hexdigest()
    body["label_provenance"]["source_references"].append(second)
    app = create_app(
        raw_root=raw_root,
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence", json=body
    )

    assert response.status_code == 200, response.text
    sources = response.json()["data"]["verified_sources"]
    assert [source["asset_id"] for source in sources] == ["E001", "E001"]
    assert [source["sha256"] for source in sources] == [
        hashlib.sha256(entry[2]).hexdigest() for entry in entries
    ]


def test_target_source_evidence_preflight_crosschecks_real_parser_manifest() -> None:
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=REPO / "data/processed",
        runs_root=REPO / "data/artifacts/runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json=_source_validation_request(
            sha256=checksum,
            source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
        ),
    )
    assert response.status_code == 200
    source_result = response.json()["data"]["verified_sources"][0]
    assert source_result["parser_provenance"] == "VERIFIED"


def test_target_source_evidence_preflight_rejects_stale_parser_manifest(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"current raw payload")
    manifest_path = raw_root / "manifests" / "data_assets.csv"
    manifest_path.parent.mkdir(parents=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    processed_root = tmp_path / "processed"
    parser_manifest = processed_root / "electrical/CELL_A/EXP_A/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "source_sha256": {"E001": "0" * 64},
                "source_asset_details": [
                    {"asset_id": "E001", "relative_path": source_rel}
                ],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source_reference=source_rel,
            ),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "parser manifest checksum" in response.json()["error"]["message"]


def test_target_source_evidence_preflight_rejects_parser_path_mismatch(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"current raw payload")
    manifest_path = raw_root / "manifests" / "data_assets.csv"
    manifest_path.parent.mkdir(parents=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
    processed_root = tmp_path / "processed"
    parser_manifest = processed_root / "electrical/CELL_A/EXP_A/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "source_sha256": {"E001": checksum},
                "source_asset_details": [
                    {"asset_id": "E001", "relative_path": "other/source.xlsx"}
                ],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(sha256=checksum, source_reference=source_rel),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "parser manifest source path" in response.json()["error"]["message"]


@pytest.mark.parametrize("payload", ["[]", "null", '"not-an-object"'])
def test_target_source_evidence_rejects_non_object_parser_manifest(
    payload: str, tmp_path: Path
) -> None:
    raw_root = tmp_path / "raw"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"current raw payload")
    manifest_path = raw_root / "manifests" / "data_assets.csv"
    manifest_path.parent.mkdir(parents=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    processed_root = tmp_path / "processed"
    parser_manifest = processed_root / "electrical/CELL_A/EXP_A/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text(payload, encoding="utf-8")
    app = create_app(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source_reference=source_rel,
            ),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "JSON object" in response.json()["error"]["message"]


def test_target_source_evidence_rejects_parser_manifest_symlink_escape(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"current raw payload")
    manifest_path = raw_root / "manifests" / "data_assets.csv"
    manifest_path.parent.mkdir(parents=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    external_manifest = tmp_path / "outside-parser-manifest.json"
    external_manifest.write_text("{}", encoding="utf-8")
    parser_manifest = (
        tmp_path / "processed" / "electrical/CELL_A/EXP_A/parser_manifest.json"
    )
    parser_manifest.parent.mkdir(parents=True)
    try:
        parser_manifest.symlink_to(external_manifest)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    app = create_app(
        raw_root=raw_root,
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )

    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source_reference=source_rel,
            ),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "outside processed data" in response.json()["error"]["message"]


def test_target_source_evidence_preflight_rejects_checksum_or_manifest_mismatch(
    tmp_path: Path,
) -> None:
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    wrong_checksum = client.post(
        "/api/v1/target-datasets/validate-source-evidence",
        json=_source_validation_request(
            sha256="0" * 64,
            source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
        ),
    )
    wrong_path = client.post(
        "/api/v1/target-datasets/validate-source-evidence",
        json=_source_validation_request(
            sha256="0" * 64,
            source_reference="batteries/CELL_001/EXP_001/electrical/other.xlsx",
        ),
    )
    unregistered_identity = client.post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256="0" * 64,
                source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
            ),
            "battery_ids": ["CELL_999"],
        },
    )
    assert wrong_checksum.status_code == 409
    assert wrong_checksum.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "checksum" in wrong_checksum.json()["error"]["message"].lower()
    assert wrong_path.status_code == 400
    assert wrong_path.json()["error"]["code"] == "VALIDATION_ERROR"
    assert unregistered_identity.status_code == 400
    assert "not registered" in unregistered_identity.json()["error"]["message"]


def test_target_source_evidence_preflight_rejects_duplicate_manifest_asset_ids(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    manifest = raw_root / "manifests" / "data_assets.csv"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"test source payload")
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    app = create_app(
        raw_root=raw_root,
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                source_reference=source_rel,
            ),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "duplicate DataAsset IDs" in response.json()["error"]["message"]


def test_target_source_evidence_preflight_rejects_symlink_escape(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = raw_root / "manifests" / "data_assets.csv"
    source_rel = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / source_rel
    source_path.parent.mkdir(parents=True)
    external_source = tmp_path / "outside.xlsx"
    external_source.write_bytes(b"outside raw root")
    source_path.symlink_to(external_source)
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["asset_id", "battery_id", "experiment_id", "modality", "relative_path"]
        )
        writer.writerow(["E001", "CELL_A", "EXP_A", "electrical", source_rel])
    app = create_app(
        raw_root=raw_root,
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence",
        json={
            **_source_validation_request(
                sha256=hashlib.sha256(external_source.read_bytes()).hexdigest(),
                source_reference=source_rel,
            ),
            "battery_ids": ["CELL_A"],
            "experiment_ids": ["EXP_A"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "outside data/raw" in response.json()["error"]["message"]


def test_target_source_preflight_blocks_tampered_parser_outputs(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    battery_id, experiment_id, asset_id = "CELL_A", "EXP_A", "E001"
    relative_path = "batteries/CELL_A/EXP_A/electrical/source.xlsx"
    source_path = raw_root / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"electrical workbook")
    (raw_root / "manifests").mkdir(parents=True)
    with (raw_root / "manifests" / "data_assets.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["asset_id", "battery_id", "experiment_id", "modality", "relative_path"])
        writer.writerow([asset_id, battery_id, experiment_id, "electrical", relative_path])

    parser_dir = processed_root / "electrical" / battery_id / experiment_id
    parser_dir.mkdir(parents=True)
    outputs = {
        "records": "records.parquet",
        "cycles": "cycles.parquet",
        "steps": "steps.parquet",
    }
    output_hashes = {}
    for key, filename in outputs.items():
        output_path = parser_dir / filename
        output_path.write_bytes(f"{key}-output".encode())
        output_hashes[key] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    (parser_dir / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "source_sha256": {asset_id: hashlib.sha256(source_path.read_bytes()).hexdigest()},
            "source_asset_details": [{"asset_id": asset_id, "relative_path": relative_path}],
            "output_files": outputs,
            "output_checksums": output_hashes,
        }),
        encoding="utf-8",
    )
    (parser_dir / outputs["records"]).write_bytes(b"tampered parsed records")
    body = _source_validation_request(
        sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        source_reference=relative_path,
    )
    body["battery_ids"] = [battery_id]
    body["experiment_ids"] = [experiment_id]
    body["label_provenance"]["source_references"][0]["asset_id"] = asset_id
    app = create_app(raw_root=raw_root, processed_root=processed_root, runs_root=tmp_path / "runs")

    response = TestClient(app).post(
        "/api/v1/target-datasets/validate-source-evidence", json=body
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "parser output" in response.json()["error"]["message"].lower()


# ---------- target-dataset materialization (P3) ----------


def _materialization_request(
    *,
    sha256: str,
    source_reference: str,
    target_id: str = "reference_soc_percent",
    battery_ids: list[str] | None = None,
    experiment_ids: list[str] | None = None,
    minimum_independent_states: int | None = None,
) -> dict:
    body = _source_validation_request(
        sha256=sha256,
        source_reference=source_reference,
        target_id=target_id,
        minimum_independent_states=minimum_independent_states,
    )
    if battery_ids is not None:
        body["battery_ids"] = battery_ids
    if experiment_ids is not None:
        body["experiment_ids"] = experiment_ids
    return body


def test_target_dataset_materialization_writes_immutable_manifest(tmp_path: Path) -> None:
    """Verified sources produce a deterministic, reusable artifact."""
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    processed_root = tmp_path / "processed"
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    body = _materialization_request(
        sha256=checksum,
        source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
    )

    first = TestClient(app).post("/api/v1/target-datasets", json=body)
    assert first.status_code == 200, first.text
    payload = first.json()["data"]
    assert payload["source_integrity"] == "VERIFIED"
    assert payload["reuse_status"] == "CREATED"
    # materialization proves source integrity only, never scientific usability
    assert payload["target_readiness"] == "NOT_ASSESSED"
    assert payload["scientific_validity"] == "NOT_ASSESSED"

    manifest_path = Path(payload["manifest_path"])
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["target_dataset_id"] == payload["target_dataset_id"]
    assert manifest["materialization_status"] == "VERIFIED_SOURCE_EVIDENCE_ONLY"
    assert manifest["target_id"] == "reference_soc_percent"
    assert manifest["independent_unit"] == "BATTERY"
    assert manifest["label_provenance"]["uncertainty"]["status"] == "UNKNOWN"
    # the frozen definition is referenced, not restated by the caller
    assert "soc_reference_percent_charge" in manifest["label_definitions"]
    assert manifest["label_definitions"]["soc_reference_percent_charge"]["formula"]

    # a byte-identical repeat reuses the same artifact and never rewrites it
    before = manifest_path.read_bytes()
    second = TestClient(app).post("/api/v1/target-datasets", json=body)
    assert second.status_code == 200
    assert second.json()["data"]["reuse_status"] == "REUSED"
    assert second.json()["data"]["target_dataset_id"] == payload["target_dataset_id"]
    assert manifest_path.read_bytes() == before


def test_target_dataset_id_is_deterministic_across_identical_requests(tmp_path: Path) -> None:
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    body = _materialization_request(
        sha256=checksum,
        source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
    )
    ids = []
    for index in range(2):
        app = create_app(
            raw_root=REPO / "data/raw",
            processed_root=tmp_path / f"processed{index}",
            runs_root=tmp_path / f"runs{index}",
        )
        response = TestClient(app).post("/api/v1/target-datasets", json=body)
        assert response.status_code == 200, response.text
        ids.append(response.json()["data"]["target_dataset_id"])
    assert ids[0] == ids[1]
    assert ids[0].startswith("TDS::")


def test_target_dataset_materialization_rejects_bad_source_checksum(tmp_path: Path) -> None:
    """The write path cannot inherit a weaker check than the read-only preflight."""
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    body = _materialization_request(
        sha256="0" * 64,
        source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
    )

    response = TestClient(app).post("/api/v1/target-datasets", json=body)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert not (tmp_path / "processed" / "target_datasets").exists()


def test_target_dataset_soh_requires_independent_state_threshold(tmp_path: Path) -> None:
    """SOH without minimum_independent_states is rejected by the contract."""
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    body = _materialization_request(
        sha256=checksum,
        source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
        target_id="soh_capacity_reference_percent",
    )
    body["target_grain"] = "CYCLE"
    body["label_provenance"]["semantic_type"] = "DERIVED_HEALTH_STATE"

    response = TestClient(app).post("/api/v1/target-datasets", json=body)

    assert response.status_code == 400
    assert "minimum_independent_states" in response.text


def test_target_dataset_grain_and_unit_must_match_target_semantics(tmp_path: Path) -> None:
    """A target's grain, semantic type and unit cannot be declared freely."""
    source = REPO / "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    app = create_app(
        raw_root=REPO / "data/raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    body = _materialization_request(
        sha256=checksum,
        source_reference="batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
    )
    # reference SOC is an event-grain derived reference label in percent
    body["target_grain"] = "CYCLE"

    response = TestClient(app).post("/api/v1/target-datasets", json=body)

    assert response.status_code == 400
    assert "target_grain" in response.text

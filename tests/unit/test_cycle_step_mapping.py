from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.datasets.joins import exact_cycle_join, exact_event_join
from battery_workbench.labels.builder import build_reference_labels
from battery_workbench.orchestrator.nodes import ReferenceLabelsNode, WorkflowNode
from battery_workbench.provenance.cycle_step_mapping import (
    CYCLE_STEP_MAPPING_FIELDS,
    CycleStepMappingError,
    project_canonical_cycle_step,
    validate_cycle_step_mapping,
)
from battery_workbench.provenance.cycle_step_mapping_store import (
    CycleStepMappingStoreError,
    save_cycle_step_mapping,
)


def _content_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def mapping_case(tmp_path: Path) -> dict[str, Path | list[dict[str, str]]]:
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    electrical_dir = processed_root / "electrical" / "CELL_A" / "EXP_A"
    electrical_dir.mkdir(parents=True)
    (raw_root / "evidence").mkdir(parents=True)
    (raw_root / "manifests").mkdir(parents=True)
    (raw_root / "assets").mkdir(parents=True)
    evidence_path = raw_root / "evidence" / "cycle-review.txt"
    evidence_path.write_text("operator reviewed source cycle boundary", encoding="utf-8")
    assets = ["E001", "E002"]
    asset_paths = {asset: f"assets/{asset}.xlsx" for asset in assets}
    asset_hashes = {}
    for asset, relative_path in asset_paths.items():
        source_path = raw_root / relative_path
        source_path.write_bytes(f"raw workbook {asset}".encode())
        asset_hashes[asset] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    with (raw_root / "manifests" / "data_assets.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "asset_id",
                "battery_id",
                "experiment_id",
                "modality",
                "relative_path",
                "file_start_time",
                "file_end_time",
                "parser_name",
                "parser_version",
            ]
        )
        for asset, relative_path in asset_paths.items():
            writer.writerow([asset, "CELL_A", "EXP_A", "electrical", relative_path, "", "", "", ""])
    cycles = pd.DataFrame(
        [
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "electrical_asset_id": asset,
                "cycle_index_raw": 1,
            }
            for asset in assets
        ]
    )
    steps = pd.DataFrame(
        [
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "electrical_asset_id": asset,
                "cycle_index_raw": 1,
                "step_index_raw": 1,
            }
            for asset in assets
        ]
    )
    cycles_path = electrical_dir / "cycles.parquet"
    steps_path = electrical_dir / "steps.parquet"
    records_path = electrical_dir / "records.parquet"
    cycles.to_parquet(cycles_path, index=False)
    steps.to_parquet(steps_path, index=False)
    pd.DataFrame({"record_index_raw": [1]}).to_parquet(records_path, index=False)
    manifest_path = electrical_dir / "parser_manifest.json"
    manifest = {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "output_files": {
            "records": "records.parquet",
            "cycles": "cycles.parquet",
            "steps": "steps.parquet",
        },
        "output_checksums": {
            "records": _content_sha256(records_path),
            "cycles": _content_sha256(cycles_path),
            "steps": _content_sha256(steps_path),
        },
        "source_sha256": asset_hashes,
        "source_asset_details": [
            {"asset_id": asset, "relative_path": asset_paths[asset]} for asset in assets
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    common = {
        "contract_version": "cycle-step-mapping/1.0",
        "mapping_id": "CSM::REVIEW_001",
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "parser_manifest_sha256": manifest_sha256,
        "evidence_relative_path": "evidence/cycle-review.txt",
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "review_status": "ACCEPTED",
        "reviewer": "operator-1",
        "reviewed_at": "2026-10-08T10:00:00+08:00",
        "rationale": "Reviewed acquisition notes for declared segment identity.",
    }
    rows = [
        {
            **common,
            "electrical_asset_id": "E001",
            "cycle_index_raw": "1",
            "step_index_raw": "1",
            "canonical_cycle_index": "1",
            "canonical_step_index": "1",
        },
        {
            **common,
            "electrical_asset_id": "E002",
            "cycle_index_raw": "1",
            "step_index_raw": "1",
            "canonical_cycle_index": "2",
            "canonical_step_index": "1",
        },
    ]
    return {
        "raw_root": raw_root,
        "processed_root": processed_root,
        "mapping_csv": tmp_path / "cycle-step-mapping.csv",
        "rows": rows,
    }


def _write_mapping(
    case: dict[str, Path | list[dict[str, str]]], rows: list[dict[str, str]]
) -> None:
    mapping_path = case["mapping_csv"]
    assert isinstance(mapping_path, Path)
    with mapping_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CYCLE_STEP_MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _validate(case: dict[str, Path | list[dict[str, str]]]) -> dict[str, object]:
    return validate_cycle_step_mapping(
        case["mapping_csv"],
        raw_root=case["raw_root"],
        processed_root=case["processed_root"],
        battery_id="CELL_A",
        experiment_id="EXP_A",
    )


def test_valid_explicit_cross_asset_mapping_does_not_authorize_labels(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])

    result = _validate(mapping_case)

    assert result["status"] == "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED"
    assert result["source_cycle_count"] == 2
    assert result["source_step_count"] == 2
    assert result["canonical_cycle_count"] == 2
    assert result["mapping_application_status"] == "LABEL_BUILDER_CONSUMER_AVAILABLE"
    assert result["label_generation_authorized"] is False
    assert result["scientific_cycle_continuity"] == "NOT_ASSESSED"


def test_projection_adds_canonical_keys_and_preserves_source_identity(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])
    source = pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A", "EXP_A"],
            "electrical_asset_id": ["E001", "E001", "E002"],
            "cycle_index_raw": [1, 1, 1],
            "step_index_raw": [1, 1, 1],
            "source_row_index": [10, 11, 20],
            "value": [0.1, 0.2, 0.3],
        }
    )

    projected = project_canonical_cycle_step(
        source,
        mapping_case["mapping_csv"],
        raw_root=mapping_case["raw_root"],
        processed_root=mapping_case["processed_root"],
        battery_id="CELL_A",
        experiment_id="EXP_A",
    )

    assert projected["canonical_cycle_index"].tolist() == [1, 1, 2]
    assert projected["canonical_step_index"].tolist() == [1, 1, 1]
    assert projected["cycle_index_raw"].tolist() == [1, 1, 1]
    assert projected["electrical_asset_id"].tolist() == ["E001", "E001", "E002"]
    assert projected["source_row_index"].tolist() == [10, 11, 20]
    assert projected["cycle_step_mapping_id"].eq("CSM::REVIEW_001").all()
    assert projected["cycle_step_mapping_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert (
        projected["cycle_step_mapping_parser_manifest_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    )
    assert projected["cycle_step_mapping_evidence_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert (
        projected["cycle_step_mapping_review_status"]
        .eq("OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED")
        .all()
    )
    assert "canonical_cycle_index" not in source.columns


def test_projection_rejects_source_identity_outside_reviewed_mapping(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])
    source = pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "electrical_asset_id": ["E003"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
        }
    )

    with pytest.raises(CycleStepMappingError, match="not in reviewed mapping"):
        project_canonical_cycle_step(
            source,
            mapping_case["mapping_csv"],
            raw_root=mapping_case["raw_root"],
            processed_root=mapping_case["processed_root"],
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )


def _prepare_label_inputs(mapping_case, tmp_path: Path, *, combine_cycles: bool = False):
    processed_root = mapping_case["processed_root"]
    raw_root = mapping_case["raw_root"]
    electrical_dir = processed_root / "electrical" / "CELL_A" / "EXP_A"
    cycles = []
    steps = []
    events = []
    mapping_rows = []
    common = mapping_case["rows"][0]
    for asset, capacity, default_canonical in (("E001", 10.0, 1), ("E002", 9.0, 2)):
        canonical = 1 if combine_cycles else default_canonical
        cycles.append(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "electrical_asset_id": asset,
                "cycle_index_raw": 1,
                "charge_capacity_ah": capacity,
                "discharge_capacity_ah": capacity,
            }
        )
        for step, step_type in ((1, "恒流充电"), (2, "恒流放电")):
            steps.append(
                {
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_A",
                    "electrical_asset_id": asset,
                    "cycle_index_raw": 1,
                    "step_index_raw": step,
                    "step_type_raw": step_type,
                    "charge_capacity_ah": capacity if step == 1 else 0.0,
                    "discharge_capacity_ah": capacity if step == 2 else 0.0,
                }
            )
            mapped_step = step + (2 if combine_cycles and asset == "E002" else 0)
            mapping_rows.append(
                {
                    **common,
                    "electrical_asset_id": asset,
                    "cycle_index_raw": "1",
                    "step_index_raw": str(step),
                    "canonical_cycle_index": str(canonical),
                    "canonical_step_index": str(mapped_step),
                }
            )
            event_index = len(events) + 1
            events.append(
                {
                    "measurement_event_id": f"ME::CELL_A::EXP_A::U001::{event_index}",
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_A",
                    "electrical_asset_id": asset,
                    "cycle_index_raw": 1,
                    "step_index_raw": step,
                    "step_type": step_type,
                    "event_order_index": event_index,
                    "charge_capacity_ah": capacity if step == 1 else 0.0,
                    "discharge_capacity_ah": capacity if step == 2 else 0.0,
                    "soc_dod_percent": None,
                }
            )
    cycles_path = electrical_dir / "cycles.parquet"
    steps_path = electrical_dir / "steps.parquet"
    records_path = electrical_dir / "records.parquet"
    cycles_frame = pd.DataFrame(cycles)
    steps_frame = pd.DataFrame(steps)
    cycles_frame.to_parquet(cycles_path, index=False)
    steps_frame.to_parquet(steps_path, index=False)
    parser_manifest_path = electrical_dir / "parser_manifest.json"
    parser_manifest = json.loads(parser_manifest_path.read_text(encoding="utf-8"))
    parser_manifest["output_checksums"].update(
        {
            "cycles": _content_sha256(cycles_path),
            "steps": _content_sha256(steps_path),
        }
    )
    parser_manifest_path.write_text(json.dumps(parser_manifest), encoding="utf-8")
    mapping_path = mapping_case["mapping_csv"]
    common = dict(common)
    common["parser_manifest_sha256"] = hashlib.sha256(parser_manifest_path.read_bytes()).hexdigest()
    for row in mapping_rows:
        row["parser_manifest_sha256"] = common["parser_manifest_sha256"]
    _write_mapping(mapping_case, mapping_rows)
    events_path = processed_root / "multimodal" / "CELL_A" / "EXP_A" / "measurement_events.parquet"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(events).to_parquet(events_path, index=False)
    ultrasound_manifest_path = (
        processed_root / "ultrasound" / "CELL_A" / "EXP_A" / "parser_manifest.json"
    )
    ultrasound_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ultrasound_manifest_path.write_text('{"assets": []}', encoding="utf-8")
    return {
        "raw_root": raw_root,
        "processed_root": processed_root,
        "events_path": events_path,
        "records_path": records_path,
        "cycles_path": cycles_path,
        "steps_path": steps_path,
        "ultrasound_manifest_path": ultrasound_manifest_path,
        "mapping_path": mapping_path,
        "output_root": tmp_path / "label-output",
        "events": pd.DataFrame(events),
    }


def _build_mapped_labels(inputs):
    return build_reference_labels(
        measurement_events_path=inputs["events_path"],
        records_path=inputs["records_path"],
        cycles_path=inputs["cycles_path"],
        steps_path=inputs["steps_path"],
        ultrasound_manifest_path=inputs["ultrasound_manifest_path"],
        output_root=inputs["output_root"],
        cycle_step_mapping_path=inputs["mapping_path"],
        raw_root=inputs["raw_root"],
    )


def test_reviewed_mapping_reaches_labels_and_exact_cycle_dataset_join(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)

    report = _build_mapped_labels(inputs)

    label_dir = inputs["output_root"] / "labels" / "CELL_A" / "EXP_A"
    event_labels = pd.read_parquet(label_dir / "event_labels.parquet")
    cycle_labels = pd.read_parquet(label_dir / "cycle_labels.parquet")
    manifest = json.loads((label_dir / "label_manifest.json").read_text(encoding="utf-8"))
    assert report.event_label_count == 4
    assert event_labels["cycle_index_raw"].tolist() == [1, 1, 1, 1]
    assert event_labels["canonical_cycle_index"].tolist() == [1, 1, 2, 2]
    assert event_labels["electrical_asset_id"].tolist() == ["E001", "E001", "E002", "E002"]
    assert event_labels["cycle_group_id"].nunique() == 2
    assert cycle_labels["cycle_index_raw"].tolist() == [1, 1]
    assert cycle_labels["canonical_cycle_index"].tolist() == [1, 2]
    assert cycle_labels["electrical_asset_id"].tolist() == ["E001", "E002"]
    assert (
        manifest["input_checksums"]["cycle_step_mapping"]
        == hashlib.sha256(inputs["mapping_path"].read_bytes()).hexdigest()
    )
    assert set(event_labels["cycle_step_mapping_review_status"]) == {
        "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED"
    }

    features = inputs["events"][["measurement_event_id", "battery_id", "experiment_id"]].copy()
    features["analysis_eligible"] = True
    joined = exact_event_join(features, event_labels)
    joined = exact_cycle_join(joined, cycle_labels)
    assert joined["soh_capacity_reference_percent"].tolist() == pytest.approx(
        [100.0, 100.0, 90.0, 90.0]
    )


def test_mapping_refuses_cross_asset_cycle_aggregation_until_capacity_contract_exists(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path, combine_cycles=True)

    with pytest.raises(CycleStepMappingError, match="cross-asset or multi-source Cycle"):
        _build_mapped_labels(inputs)


def test_label_builder_rejects_duplicate_raw_cycle_without_reviewed_mapping(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)

    with pytest.raises(ValueError, match="explicit reviewed mapping is required"):
        build_reference_labels(
            measurement_events_path=inputs["events_path"],
            records_path=inputs["records_path"],
            cycles_path=inputs["cycles_path"],
            steps_path=inputs["steps_path"],
            ultrasound_manifest_path=inputs["ultrasound_manifest_path"],
            output_root=inputs["output_root"],
        )


def test_label_builder_requires_mapping_for_multiple_assets_even_without_raw_id_collision(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    cycles = pd.read_parquet(inputs["cycles_path"])
    steps = pd.read_parquet(inputs["steps_path"])
    events = pd.read_parquet(inputs["events_path"])
    cycles.loc[cycles["electrical_asset_id"] == "E002", "cycle_index_raw"] = 2
    steps.loc[steps["electrical_asset_id"] == "E002", "cycle_index_raw"] = 2
    events.loc[events["electrical_asset_id"] == "E002", "cycle_index_raw"] = 2
    cycles.to_parquet(inputs["cycles_path"], index=False)
    steps.to_parquet(inputs["steps_path"], index=False)
    events.to_parquet(inputs["events_path"], index=False)

    with pytest.raises(ValueError, match="explicit reviewed mapping is required"):
        build_reference_labels(
            measurement_events_path=inputs["events_path"],
            records_path=inputs["records_path"],
            cycles_path=inputs["cycles_path"],
            steps_path=inputs["steps_path"],
            ultrasound_manifest_path=inputs["ultrasound_manifest_path"],
            output_root=inputs["output_root"],
        )


@pytest.mark.parametrize(
    ("mapping_exists", "declared_checksum", "expected_reusable"),
    [
        (True, "current", True),
        (True, "stale", False),
        (True, None, False),
        (False, "current", False),
    ],
)
def test_label_node_reuses_only_when_mapping_checksum_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mapping_exists: bool,
    declared_checksum: str | None,
    expected_reusable: bool,
) -> None:
    processed_root = tmp_path / "data" / "processed"
    annotation_dir = tmp_path / "data" / "annotations" / "CELL_A" / "EXP_A"
    annotation_dir.mkdir(parents=True)
    mapping_path = annotation_dir / "cycle-step-mapping.csv"
    if mapping_exists:
        mapping_path.write_text("mapping version\n", encoding="utf-8")
    actual_checksum = _content_sha256(mapping_path) if mapping_exists else "a" * 64
    manifest_path = tmp_path / "label_manifest.json"
    checksums = {
        "cycle_step_mapping": actual_checksum if declared_checksum == "current" else "0" * 64
    }
    if declared_checksum is None:
        checksums = {}
    manifest_path.write_text(json.dumps({"input_checksums": checksums}), encoding="utf-8")
    artifact = SimpleNamespace(manifest_path=manifest_path)
    monkeypatch.setattr(
        WorkflowNode,
        "resolve_existing_output",
        lambda self, plan, inputs, root: (artifact, "reusable"),
    )
    plan = SimpleNamespace(project=SimpleNamespace(battery_id="CELL_A", experiment_id="EXP_A"))

    resolved, reason = ReferenceLabelsNode().resolve_existing_output(plan, {}, processed_root)

    assert (resolved is not None) is expected_reusable
    if not expected_reusable:
        assert "mapping" in reason.lower()


def test_cycle_step_mapping_preflight_api_is_read_only(mapping_case, tmp_path: Path) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    app = create_app(
        raw_root=inputs["raw_root"],
        processed_root=inputs["processed_root"],
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    annotations = Path(inputs["raw_root"]).parent / "annotations"
    parser_manifest = (
        Path(inputs["processed_root"]) / "electrical" / "CELL_A" / "EXP_A" / "parser_manifest.json"
    )
    manifest_before = _content_sha256(parser_manifest)
    cycles_before = _content_sha256(Path(inputs["cycles_path"]))

    response = client.post(
        "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping/preflight",
        json={"mapping_csv": Path(inputs["mapping_path"]).read_text(encoding="utf-8")},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED"
    assert payload["label_generation_authorized"] is False
    assert payload["review_status"] == "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED"
    assert not annotations.exists()
    assert _content_sha256(parser_manifest) == manifest_before
    assert _content_sha256(Path(inputs["cycles_path"])) == cycles_before


def test_cycle_step_mapping_preflight_api_returns_typed_invalid_response(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    client = TestClient(
        create_app(
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            runs_root=tmp_path / "runs",
        )
    )

    response = client.post(
        "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping/preflight",
        json={"mapping_csv": "not,a,valid,cycle-step,mapping\n"},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["status"] == "INVALID_MAPPING"


def test_cycle_step_mapping_save_is_versioned_and_uses_optimistic_concurrency(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    client = TestClient(
        create_app(
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            runs_root=tmp_path / "runs",
        )
    )
    endpoint = "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping"
    content = Path(inputs["mapping_path"]).read_text(encoding="utf-8")
    sidecar = Path(inputs["raw_root"]).parent / "annotations" / "CELL_A" / "EXP_A"
    annotations_root = Path(inputs["raw_root"]).parent / "annotations"
    initial_status = client.get(endpoint)
    assert initial_status.status_code == 200
    assert initial_status.json()["data"]["status"] == "MISSING"
    assert not annotations_root.exists()

    first = client.put(
        endpoint,
        json={
            "mapping_csv": content,
            "confirm_reviewed": True,
            "expected_active_sha256": None,
        },
    )

    assert first.status_code == 200, first.text
    first_data = first.json()["data"]
    active = sidecar / "cycle-step-mapping.csv"
    revisions = sidecar / "cycle-step-mapping.revisions"
    assert active.read_text(encoding="utf-8") == content
    assert (revisions / f"{first_data['mapping_sha256']}.csv").read_text(
        encoding="utf-8"
    ) == content
    assert not (Path(inputs["raw_root"]) / "annotations").exists()
    saved_status = client.get(endpoint).json()["data"]
    assert saved_status["status"] == "VALIDATED"
    assert saved_status["active_mapping_sha256"] == first_data["mapping_sha256"]
    assert saved_status["revision_count"] == 1

    unchanged = client.put(
        endpoint,
        json={
            "mapping_csv": content,
            "confirm_reviewed": True,
            "expected_active_sha256": first_data["mapping_sha256"],
        },
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["save_status"] == "ALREADY_CURRENT"
    assert unchanged.json()["data"]["revision_count"] == 1

    changed = content.replace("CSM::REVIEW_001", "CSM::REVIEW_002")
    second = client.put(
        endpoint,
        json={
            "mapping_csv": changed,
            "confirm_reviewed": True,
            "expected_active_sha256": first_data["mapping_sha256"],
        },
    )

    assert second.status_code == 200
    second_data = second.json()["data"]
    assert second_data["previous_mapping_sha256"] == first_data["mapping_sha256"]
    assert active.read_text(encoding="utf-8") == changed
    assert (revisions / f"{first_data['mapping_sha256']}.csv").exists()
    assert (revisions / f"{second_data['mapping_sha256']}.csv").read_text(
        encoding="utf-8"
    ) == changed

    stale = client.put(
        endpoint,
        json={
            "mapping_csv": content,
            "confirm_reviewed": True,
            "expected_active_sha256": first_data["mapping_sha256"],
        },
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"
    assert active.read_text(encoding="utf-8") == changed


def test_saved_mapping_sidecar_is_consumed_by_reference_labels_workflow_node(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    mapping_csv = Path(inputs["mapping_path"]).read_text(encoding="utf-8")
    saved = save_cycle_step_mapping(
        mapping_csv,
        confirm_reviewed=True,
        expected_active_sha256=None,
        raw_root=inputs["raw_root"],
        processed_root=inputs["processed_root"],
        battery_id="CELL_A",
        experiment_id="EXP_A",
    )
    plan = SimpleNamespace(project=SimpleNamespace(battery_id="CELL_A", experiment_id="EXP_A"))
    context = SimpleNamespace(
        raw_root=inputs["raw_root"], processed_root=inputs["processed_root"]
    )

    result = ReferenceLabelsNode().run(plan, {}, context)

    label_dir = Path(inputs["processed_root"]) / "labels" / "CELL_A" / "EXP_A"
    event_labels = pd.read_parquet(label_dir / "event_labels.parquet")
    manifest = json.loads((label_dir / "label_manifest.json").read_text(encoding="utf-8"))
    assert result["artifact_id"] == manifest["label_set_id"]
    assert event_labels["canonical_cycle_index"].tolist() == [1, 1, 2, 2]
    assert (
        manifest["input_checksums"]["cycle_step_mapping"] == saved["mapping_sha256"]
    )


def test_cycle_step_mapping_save_requires_explicit_review_confirmation(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    client = TestClient(
        create_app(
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            runs_root=tmp_path / "runs",
        )
    )
    response = client.put(
        "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping",
        json={
            "mapping_csv": Path(inputs["mapping_path"]).read_text(encoding="utf-8"),
            "confirm_reviewed": False,
            "expected_active_sha256": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not (Path(inputs["raw_root"]).parent / "annotations").exists()


def test_saved_mapping_is_reported_invalid_after_parser_manifest_changes(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    client = TestClient(
        create_app(
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            runs_root=tmp_path / "runs",
        )
    )
    endpoint = "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping"
    content = Path(inputs["mapping_path"]).read_text(encoding="utf-8")
    saved = client.put(
        endpoint,
        json={
            "mapping_csv": content,
            "confirm_reviewed": True,
            "expected_active_sha256": None,
        },
    )
    assert saved.status_code == 200

    parser_manifest = (
        Path(inputs["processed_root"])
        / "electrical"
        / "CELL_A"
        / "EXP_A"
        / "parser_manifest.json"
    )
    parser_manifest.write_text(
        parser_manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    status = client.get(endpoint)

    assert status.status_code == 200
    assert status.json()["data"]["status"] == "INVALID"
    assert status.json()["data"]["active_mapping_sha256"] == saved.json()["data"]["mapping_sha256"]
    assert "parser manifest changed" in status.json()["data"]["reason"]


def test_cycle_step_mapping_save_rejects_symlinked_battery_directory_without_escape(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    annotations = Path(inputs["raw_root"]).parent / "annotations"
    annotations.mkdir()
    outside = tmp_path / "outside-annotations"
    outside.mkdir()
    battery_link = annotations / "CELL_A"
    try:
        battery_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(CycleStepMappingStoreError, match="must not be symlinks"):
        save_cycle_step_mapping(
            Path(inputs["mapping_path"]).read_text(encoding="utf-8"),
            confirm_reviewed=True,
            expected_active_sha256=None,
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )

    assert not (outside / "EXP_A").exists()
    assert not (Path(inputs["raw_root"]) / "annotations").exists()


def test_invalid_mapping_does_not_create_annotation_directories(mapping_case) -> None:
    raw_root = mapping_case["raw_root"]
    processed_root = mapping_case["processed_root"]
    assert isinstance(raw_root, Path)
    assert isinstance(processed_root, Path)
    with pytest.raises(CycleStepMappingError):
        save_cycle_step_mapping(
            "invalid,csv\n",
            confirm_reviewed=True,
            expected_active_sha256=None,
            raw_root=raw_root,
            processed_root=processed_root,
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )
    assert not (raw_root.parent / "annotations").exists()


def test_damaged_revision_history_blocks_replacement_without_changing_active_mapping(
    mapping_case, tmp_path: Path
) -> None:
    inputs = _prepare_label_inputs(mapping_case, tmp_path)
    content = Path(inputs["mapping_path"]).read_text(encoding="utf-8")
    first = save_cycle_step_mapping(
        content,
        confirm_reviewed=True,
        expected_active_sha256=None,
        raw_root=inputs["raw_root"],
        processed_root=inputs["processed_root"],
        battery_id="CELL_A",
        experiment_id="EXP_A",
    )
    sidecar = Path(inputs["raw_root"]).parent / "annotations" / "CELL_A" / "EXP_A"
    active = sidecar / "cycle-step-mapping.csv"
    active_before = active.read_bytes()
    revision = sidecar / "cycle-step-mapping.revisions" / f"{first['mapping_sha256']}.csv"
    revision.write_text("damaged history", encoding="utf-8")

    with pytest.raises(CycleStepMappingStoreError, match="inconsistent"):
        save_cycle_step_mapping(
            content.replace("CSM::REVIEW_001", "CSM::REVIEW_002"),
            confirm_reviewed=True,
            expected_active_sha256=first["mapping_sha256"],
            raw_root=inputs["raw_root"],
            processed_root=inputs["processed_root"],
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )

    assert active.read_bytes() == active_before


def test_explicit_segment_continuation_can_share_cycle_but_not_step(mapping_case) -> None:
    rows = mapping_case["rows"]
    rows[1]["canonical_cycle_index"] = "1"
    rows[1]["canonical_step_index"] = "2"
    _write_mapping(mapping_case, rows)

    result = _validate(mapping_case)

    assert result["canonical_cycle_count"] == 1
    assert result["source_step_count"] == 2
    assert result["label_generation_authorized"] is False


def test_rejects_missing_source_step_mapping(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"][:1])

    with pytest.raises(CycleStepMappingError, match="cover every parsed source step"):
        _validate(mapping_case)


def test_rejects_many_to_one_canonical_step_mapping(mapping_case) -> None:
    rows = mapping_case["rows"]
    rows[1]["canonical_cycle_index"] = "1"
    rows[1]["canonical_step_index"] = "1"
    _write_mapping(mapping_case, rows)

    with pytest.raises(CycleStepMappingError, match="multiple source steps map"):
        _validate(mapping_case)


def test_rejects_changed_parser_manifest_after_review(mapping_case) -> None:
    rows = mapping_case["rows"]
    rows[0]["parser_manifest_sha256"] = "0" * 64
    _write_mapping(mapping_case, rows)

    with pytest.raises(CycleStepMappingError, match="parser manifest changed after review"):
        _validate(mapping_case)


def test_rejects_changed_evidence_bytes(mapping_case) -> None:
    rows = mapping_case["rows"]
    raw_root = mapping_case["raw_root"]
    assert isinstance(raw_root, Path)
    (raw_root / "evidence" / "cycle-review.txt").write_text("changed", encoding="utf-8")
    _write_mapping(mapping_case, rows)

    with pytest.raises(CycleStepMappingError, match="evidence SHA-256 mismatch"):
        _validate(mapping_case)


def test_rejects_naive_review_timestamp(mapping_case) -> None:
    rows = mapping_case["rows"]
    rows[0]["reviewed_at"] = "2026-10-08T10:00:00"
    _write_mapping(mapping_case, rows)

    with pytest.raises(CycleStepMappingError, match="must include a UTC offset"):
        _validate(mapping_case)


def test_rejects_parser_output_checksum_mismatch(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])
    processed_root = mapping_case["processed_root"]
    assert isinstance(processed_root, Path)
    cycles_path = processed_root / "electrical" / "CELL_A" / "EXP_A" / "cycles.parquet"
    cycles_path.write_bytes(cycles_path.read_bytes() + b"tamper")

    with pytest.raises(CycleStepMappingError, match="parser output checksum mismatch"):
        _validate(mapping_case)


def test_rejects_raw_asset_bytes_changed_after_parse(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])
    raw_root = mapping_case["raw_root"]
    assert isinstance(raw_root, Path)
    (raw_root / "assets" / "E001.xlsx").write_bytes(b"changed workbook")

    with pytest.raises(CycleStepMappingError, match="raw Electrical source changed after parsing"):
        _validate(mapping_case)


def test_rejects_inconsistent_canonical_cycle_for_one_source_cycle(mapping_case) -> None:
    rows = mapping_case["rows"]
    rows[1]["electrical_asset_id"] = "E001"
    rows[1]["cycle_index_raw"] = "1"
    rows[1]["step_index_raw"] = "2"
    rows[1]["canonical_cycle_index"] = "2"
    _write_mapping(mapping_case, rows)

    with pytest.raises(CycleStepMappingError, match="one source Cycle maps to multiple"):
        _validate(mapping_case)

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.provenance.cycle_step_mapping import (
    CYCLE_STEP_MAPPING_FIELDS,
    CycleStepMappingError,
    project_canonical_cycle_step,
    validate_cycle_step_mapping,
)
from battery_workbench.provenance.processed_manifest import content_sha256


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
            "records": content_sha256(records_path),
            "cycles": content_sha256(cycles_path),
            "steps": content_sha256(steps_path),
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
    assert result["mapping_application_status"] == "PROJECTION_AVAILABLE_NOT_INTEGRATED"
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

    with pytest.raises(CycleStepMappingError, match="not current/integrity-verified"):
        _validate(mapping_case)


def test_rejects_raw_asset_bytes_changed_after_parse(mapping_case) -> None:
    _write_mapping(mapping_case, mapping_case["rows"])
    raw_root = mapping_case["raw_root"]
    assert isinstance(raw_root, Path)
    (raw_root / "assets" / "E001.xlsx").write_bytes(b"changed workbook")

    with pytest.raises(CycleStepMappingError, match="not current/integrity-verified"):
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

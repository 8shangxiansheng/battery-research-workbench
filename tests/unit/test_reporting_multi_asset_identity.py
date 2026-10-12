from __future__ import annotations

import hashlib
import json
from pathlib import Path

from battery_workbench.reporting.collector import collect_experiment_record, collect_results


def test_experiment_report_record_preserves_all_source_asset_ids(tmp_path: Path) -> None:
    for modality, asset_ids in (
        ("electrical", ["E001", "E002"]),
        ("ultrasound", ["U001", "U002"]),
    ):
        directory = tmp_path / modality / "CELL_X" / "EXP_X"
        directory.mkdir(parents=True)
        output_files = (
            {"records": "records.parquet", "cycles": "cycles.parquet", "steps": "steps.parquet"}
            if modality == "electrical"
            else {"frames": "frames.parquet", "waveforms": "waveforms.zarr"}
        )
        output_checksums = {}
        for key, filename in output_files.items():
            output = directory / filename
            if key == "waveforms":
                output.mkdir()
                payload = output / "chunk.bin"
                payload.write_bytes(b"waveform")
                checksum = hashlib.sha256(
                    b"chunk.bin" + payload.read_bytes()
                ).hexdigest()
            else:
                output.write_bytes(key.encode())
                checksum = hashlib.sha256(output.read_bytes()).hexdigest()
            output_checksums[key] = checksum
        (directory / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": "CELL_X",
                    "experiment_id": "EXP_X",
                    "source_assets": asset_ids,
                    "output_files": output_files,
                    "output_checksums": output_checksums,
                }
            ),
            encoding="utf-8",
        )

    record = collect_experiment_record(tmp_path, "CELL_X", "EXP_X")

    assert record.raw_assets == ["E001", "E002", "U001", "U002"]


def test_invalid_parser_manifest_is_a_report_limitation_not_a_crash(tmp_path: Path) -> None:
    manifest = tmp_path / "electrical" / "CELL_X" / "EXP_X" / "parser_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("[]", encoding="utf-8")

    record = collect_experiment_record(tmp_path, "CELL_X", "EXP_X")

    assert record.raw_assets == []
    assert record.scientific_status == "INTEGRITY_BLOCKED"
    assert "SOURCE_PROVENANCE_INVALID" in record.limitations
    results = collect_results(tmp_path, "CELL_X", "EXP_X")
    assert len(results) == 1
    assert results[0].result_id == "R::source_provenance_integrity"
    assert results[0].scientific_status == "INTEGRITY_BLOCKED"


def test_unreadable_parser_manifest_is_reported_as_invalid_provenance(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "ultrasound" / "CELL_X" / "EXP_X" / "parser_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"\xff\xfe")

    record = collect_experiment_record(tmp_path, "CELL_X", "EXP_X")

    assert record.raw_assets == []
    assert record.scientific_status == "INTEGRITY_BLOCKED"
    assert "SOURCE_PROVENANCE_INVALID" in record.limitations
    results = collect_results(tmp_path, "CELL_X", "EXP_X")
    assert len(results) == 1
    assert results[0].result_id == "R::source_provenance_integrity"

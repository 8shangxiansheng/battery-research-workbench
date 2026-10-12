from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.provenance.source_map_preflight import (
    SOURCE_MAP_FIELDS,
    SourceMapPreflightError,
    main,
    validate_declared_source_map,
)


def _make_map(root: Path, map_path: Path) -> Path:
    sources = {
        "electrical": ("sample.xlsx", b"xlsx bytes"),
        "ultrasound": ("waveform.txt", b"txt bytes"),
        "time": ("clock.xml", b"clock evidence"),
    }
    for filename, content in sources.values():
        (root / filename).write_bytes(content)
    row = {
        "pair_id": "PAIR_A",
        "electrical_relative_path": "sample.xlsx",
        "ultrasound_relative_path": "waveform.txt",
        "time_anchor_metadata_relative_path": "clock.xml",
        "electrical_sha256": hashlib.sha256(sources["electrical"][1]).hexdigest(),
        "ultrasound_sha256": hashlib.sha256(sources["ultrasound"][1]).hexdigest(),
        "time_anchor_metadata_sha256": hashlib.sha256(sources["time"][1]).hexdigest(),
    }
    with map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_MAP_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return map_path


def test_source_map_preflight_verifies_checksums_without_identity_claims(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    map_path = _make_map(source_root, tmp_path / "pairs.csv")

    result = validate_declared_source_map(map_path, source_root=source_root)

    assert result["status"] == "SOURCE_MAP_INTEGRITY_VERIFIED"
    assert result["declared_pair_count"] == 1
    assert result["pairing_truth_status"] == "NOT_ASSESSED"
    assert result["battery_identity_status"] == "NOT_ASSESSED"
    assert result["experiment_identity_status"] == "NOT_ASSESSED"
    assert result["timebase_validation_status"] == "NOT_ASSESSED"
    assert result["cohort_admission_authorized"] is False
    assert result["pairs"][0]["electrical"]["sha256"]
    assert result["pairs"][0]["time_reference_evidence"]["size_bytes"] == len(
        b"clock evidence"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("electrical_sha256", "0" * 64, "SHA-256 mismatch"),
        ("electrical_relative_path", "../sample.xlsx", "relative and confined"),
        ("ultrasound_relative_path", "sample.xlsx", "unsupported extension"),
    ],
)
def test_source_map_preflight_rejects_bad_hash_paths_and_extensions(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    map_path = _make_map(source_root, tmp_path / "pairs.csv")
    with map_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0][field] = value
    with map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(SourceMapPreflightError, match=message):
        validate_declared_source_map(map_path, source_root=source_root)


def test_source_map_preflight_rejects_duplicate_pair_ids(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    map_path = _make_map(source_root, tmp_path / "pairs.csv")
    with map_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows * 2)

    with pytest.raises(SourceMapPreflightError, match="duplicate pair_id"):
        validate_declared_source_map(map_path, source_root=source_root)


def test_source_map_preflight_cli_emits_json(tmp_path: Path, monkeypatch, capsys) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    map_path = _make_map(source_root, tmp_path / "pairs.csv")
    monkeypatch.setattr(
        "sys.argv", ["source-map-preflight", str(map_path), "--source-root", str(source_root)]
    )

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["declared_pair_count"] == 1

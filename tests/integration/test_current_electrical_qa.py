from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from battery_workbench.electrical.qa import ElectricalQAConfig, run_electrical_qa


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.integration
def test_current_cell_001_baseline_and_input_immutability(tmp_path: Path) -> None:
    input_dir = Path("data/processed/electrical/CELL_001/EXP_001")
    if not input_dir.is_dir():
        pytest.skip("current BRW-003 processed outputs are unavailable")
    inputs = sorted(input_dir.glob("*.parquet")) + [input_dir / "parser_manifest.json"]
    before = {path.name: sha256(path) for path in inputs}

    report = run_electrical_qa(
        "CELL_001", "EXP_001", input_dir, tmp_path / "electrical_qa", ElectricalQAConfig()
    )

    assert report.status == "PASS_WITH_WARNINGS"
    assert report.summary["row_counts"]["records"] == 39996
    assert report.summary["row_counts"]["cycles"] == 2
    assert report.summary["row_counts"]["steps"] == 10
    assert report.temporal["timestamp_min"] == "2024-01-06T09:52:31"
    assert report.temporal["timestamp_max"] == "2024-01-06T20:58:54"
    assert report.temporal["duplicate_timestamp_count"] == 12
    assert {path.name: sha256(path) for path in inputs} == before

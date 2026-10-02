from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.reporting.collector import collect_experiment_record


def test_experiment_report_record_preserves_all_source_asset_ids(tmp_path: Path) -> None:
    for modality, asset_ids in (
        ("electrical", ["E001", "E002"]),
        ("ultrasound", ["U001", "U002"]),
    ):
        manifest = tmp_path / modality / "CELL_X" / "EXP_X" / "parser_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "source_assets": asset_ids
                }
            ),
            encoding="utf-8",
        )

    record = collect_experiment_record(tmp_path, "CELL_X", "EXP_X")

    assert record.raw_assets == ["E001", "E002", "U001", "U002"]

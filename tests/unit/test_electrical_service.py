from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.electrical.service import (
    parse_electrical_experiment,
    write_electrical_experiment,
)


def test_multi_asset_experiment_preserves_rows_and_reports_overlap(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    start = datetime.fromisoformat("2024-01-01 10:00:00")
    first_path = electrical_workbook_factory(name="first.xlsx", start=start)
    second_path = electrical_workbook_factory(
        name="second.xlsx", start=start + timedelta(seconds=1)
    )
    experiment = Experiment(experiment_id="EXP_MULTI", battery_id="CELL_MULTI", start_time=start)
    assets = [
        DataAsset(
            asset_id="E1",
            experiment_id="EXP_MULTI",
            modality="electrical",
            relative_path=first_path.relative_to(tmp_path),
        ),
        DataAsset(
            asset_id="E2",
            experiment_id="EXP_MULTI",
            modality="electrical",
            relative_path=second_path.relative_to(tmp_path),
        ),
    ]

    result = parse_electrical_experiment(experiment, assets, tmp_path)

    assert len(result.records) == 8
    assert set(result.records["electrical_asset_id"]) == {"E1", "E2"}
    assert result.records["timestamp"].is_monotonic_increasing
    assert (
        result.records.duplicated(
            subset=["electrical_asset_id", "source_sheet", "source_row_index"]
        ).sum()
        == 0
    )
    assert any("overlap" in warning.lower() for warning in result.warnings)


def test_write_parquet_and_parser_manifest_round_trip(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = electrical_workbook_factory()
    experiment = Experiment(experiment_id="EXP_OUT", battery_id="CELL_OUT")
    asset = DataAsset(
        asset_id="E_OUT",
        experiment_id="EXP_OUT",
        modality="electrical",
        relative_path=path.relative_to(tmp_path),
        parser_name="custom_excel",
        parser_version="0.1.0",
    )
    result = parse_electrical_experiment(experiment, [asset], tmp_path)

    output = write_electrical_experiment(result, tmp_path / "processed")

    output_dir = tmp_path / "processed" / "CELL_OUT" / "EXP_OUT"
    expected = {
        "records.parquet",
        "cycles.parquet",
        "steps.parquet",
        "aux_temperature.parquet",
        "aux_voltage.parquet",
        "parser_manifest.json",
    }
    assert {path.name for path in output_dir.iterdir()} == expected
    reread = pd.read_parquet(output_dir / "records.parquet")
    assert len(reread) == len(result.records)
    assert reread["timestamp"].equals(result.records["timestamp"].reset_index(drop=True))
    assert reread["electrical_asset_id"].tolist() == result.records["electrical_asset_id"].tolist()

    manifest = json.loads((output_dir / "parser_manifest.json").read_text())
    assert manifest["battery_id"] == "CELL_OUT"
    assert manifest["experiment_id"] == "EXP_OUT"
    assert manifest["source_assets"] == ["E_OUT"]
    assert manifest["row_counts"]["records"] == 4
    assert manifest["cycle_ids_raw"] == [1, 2]
    assert manifest["timestamp_min"] == "2024-01-01T10:00:00"
    assert set(manifest["output_files"]) == {
        "records",
        "cycles",
        "steps",
        "aux_temperature",
        "aux_voltage",
        "parser_manifest",
    }
    assert output.manifest_path == output_dir / "parser_manifest.json"

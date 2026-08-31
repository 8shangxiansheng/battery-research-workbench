from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.electrical.service import parse_electrical_asset


def test_parse_two_cycle_workbook_with_provenance(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = electrical_workbook_factory()
    asset = DataAsset(
        asset_id="E_SYNTH",
        experiment_id="EXP_SYNTH",
        modality="electrical",
        relative_path=path.relative_to(tmp_path),
        parser_name="custom_excel",
        parser_version="0.1.0",
    )

    result = parse_electrical_asset(asset, tmp_path, battery_id="CELL_SYNTH")

    assert len(result.records) == 4
    assert set(result.records["cycle_index_raw"]) == {1, 2}
    assert set(result.records["step_index_raw"]) == {1, 2}
    assert result.records["timestamp"].dtype == "datetime64[ns]"
    assert result.records["current_a"].tolist() == [1.0, 0.0, 1.0, 0.0]
    assert result.records["voltage_v"].tolist() == [3.2, 3.3, 3.4, 3.5]
    assert result.records["capacity_ah"].tolist() == [0.0, 0.1, 0.0, 0.1]
    assert result.records["source_row_index"].tolist() == [2, 3, 4, 5]
    assert set(result.records["electrical_asset_id"]) == {"E_SYNTH"}
    assert set(result.records["source_sheet"]) == {"record"}
    assert len(result.cycles) == 2
    assert len(result.steps) == 4
    assert len(result.aux_temperature) == 4
    assert len(result.aux_voltage) == 4
    assert result.column_mappings["record"]["SOC/DOD(%)"] == "soc_dod_percent"
    assert any("ignored 1 fully blank row" in warning for warning in result.warnings)
    assert any("ignored non-tabular row 7" in warning for warning in result.warnings)
    assert pd.api.types.is_numeric_dtype(result.records["contact_resistance_mohm"])


def test_optional_aux_voltage_is_not_fabricated(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = electrical_workbook_factory(include_aux_voltage=False)
    asset = DataAsset(
        asset_id="E_NO_AUX_V",
        experiment_id="EXP_SYNTH",
        modality="electrical",
        relative_path=path.relative_to(tmp_path),
    )

    result = parse_electrical_asset(asset, tmp_path, battery_id="CELL_SYNTH")

    assert result.aux_voltage is None
    assert "auxVol" not in result.sheets_found

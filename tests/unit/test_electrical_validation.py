from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.electrical.service import parse_electrical_asset
from battery_workbench.io.electrical.validation import ElectricalValidationError


def _asset(path: Path, root: Path) -> DataAsset:
    return DataAsset(
        asset_id="E_INVALID",
        experiment_id="EXP_SYNTH",
        modality="electrical",
        relative_path=path.relative_to(root),
    )


def test_missing_required_record_column_has_context(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = electrical_workbook_factory(missing_record_column="绝对时间")

    with pytest.raises(ElectricalValidationError) as exc_info:
        parse_electrical_asset(_asset(path, tmp_path), tmp_path, battery_id="CELL_SYNTH")

    message = str(exc_info.value)
    assert "asset_id=E_INVALID" in message
    assert "sheet=record" in message
    assert "绝对时间" in message


def test_backwards_timestamp_fails_but_duplicate_timestamp_is_allowed(
    electrical_workbook_factory: Callable[..., Path], tmp_path: Path
) -> None:
    valid_path = electrical_workbook_factory(name="duplicates.xlsx")
    valid = parse_electrical_asset(_asset(valid_path, tmp_path), tmp_path, battery_id="CELL_SYNTH")
    assert valid.records["timestamp"].is_monotonic_increasing
    assert valid.records["timestamp"].duplicated().sum() == 1

    invalid_path = electrical_workbook_factory(name="backwards.xlsx", backwards_timestamp=True)
    with pytest.raises(ElectricalValidationError, match="non-decreasing"):
        parse_electrical_asset(_asset(invalid_path, tmp_path), tmp_path, battery_id="CELL_SYNTH")

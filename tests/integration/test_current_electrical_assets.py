from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.io.electrical.service import parse_electrical_experiment
from battery_workbench.io.experiment.manifest_loader import (
    load_data_assets,
    load_experiments,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw"
MANIFEST_ROOT = RAW_ROOT / "manifests"
GOLDEN_PATH = REPO_ROOT / "tests" / "golden" / "electrical_expected.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.integration
def test_current_cell_001_assets_via_manifest() -> None:
    assets = [
        asset
        for asset in load_data_assets(MANIFEST_ROOT / "data_assets.csv")
        if asset.modality == "electrical"
    ]
    if not assets or not all((RAW_ROOT / asset.relative_path).exists() for asset in assets):
        pytest.skip("Current raw CELL_001 electrical assets are not available")

    experiment = next(
        item
        for item in load_experiments(MANIFEST_ROOT / "experiments.csv")
        if item.experiment_id == "EXP_001"
    )
    hashes_before = {asset.asset_id: _sha256(RAW_ROOT / asset.relative_path) for asset in assets}

    result = parse_electrical_experiment(experiment, assets, RAW_ROOT)

    assert [asset.asset_id for asset in result.assets] == ["E001"]
    assert len(result.records) == 39996
    assert len(result.cycles) == 2
    assert len(result.steps) == 10
    assert set(result.records["cycle_index_raw"]) == {1, 2}
    assert result.records["timestamp"].min().isoformat() == "2024-01-06T09:52:31"
    assert result.records["timestamp"].max().isoformat() == "2024-01-06T20:58:54"
    assert result.records["timestamp"].is_monotonic_increasing
    assert int(result.records["timestamp"].duplicated().sum()) == 12
    assert result.records["cycle_index_raw"].notna().mean() == 1.0
    assert any("ignored non-tabular row 15" in warning for warning in result.warnings)
    assert any("ignored non-tabular row 19" in warning for warning in result.warnings)

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    for expected in golden["checks"]:
        actual = result.records.loc[
            result.records["source_row_index"] == expected["source_row_index"]
        ].iloc[0]
        for field in [
            "record_index_raw",
            "cycle_index_raw",
            "step_index_raw",
            "step_type_raw",
            "current_a",
            "voltage_v",
            "capacity_ah",
        ]:
            assert (
                actual[field] == pytest.approx(expected[field])
                if isinstance(expected[field], float)
                else actual[field] == expected[field]
            )
        assert actual["timestamp"].isoformat() == expected["timestamp"]

    hashes_after = {asset.asset_id: _sha256(RAW_ROOT / asset.relative_path) for asset in assets}
    assert hashes_after == hashes_before

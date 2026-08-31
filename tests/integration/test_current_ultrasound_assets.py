from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import zarr

from battery_workbench.io.experiment.manifest_loader import (
    load_data_assets,
    load_experiments,
)
from battery_workbench.io.ultrasound.service import (
    parse_ultrasound_experiment,
    write_ultrasound_experiment,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.integration
def test_current_ultrasound_asset_matches_independent_golden(tmp_path: Path) -> None:
    raw_root = Path("data/raw")
    assets = [
        asset
        for asset in load_data_assets(raw_root / "manifests/data_assets.csv")
        if asset.modality == "ultrasound"
    ]
    if not assets or not (raw_root / assets[0].relative_path).is_file():
        pytest.skip("current raw Ultrasound DataAsset is unavailable")
    experiments = {
        experiment.experiment_id: experiment
        for experiment in load_experiments(raw_root / "manifests/experiments.csv")
    }
    experiment = experiments[assets[0].experiment_id]
    source = raw_root / assets[0].relative_path
    before = sha256(source)
    golden = json.loads(Path("tests/golden/ultrasound_expected.json").read_text())

    parsed = parse_ultrasound_experiment(experiment, assets, raw_root)
    output = write_ultrasound_experiment(parsed, tmp_path / "processed")

    assert len(parsed.frames) == golden["frame_count"] == 3999
    assert parsed.asset_results[0].frame_index_min == 0
    assert parsed.asset_results[0].frame_index_max == 3998
    assert parsed.asset_results[0].median_frame_interval_s == pytest.approx(10.0)
    waveform = zarr.open_group(output.waveforms_path, mode="r")["U001/waveform"]
    for expected in golden["frames"]:
        row = expected["frame_index_raw"]
        frame = parsed.frames[row]
        assert frame.source_line_index == expected["source_line_index"]
        assert frame.elapsed_time_s == pytest.approx(expected["elapsed_time_s"])
        for position, value in expected["waveform_checks"].items():
            assert int(waveform[row, int(position)]) == value
    manifest = json.loads(output.manifest_path.read_text())
    assert manifest["assets"][0]["sampling_rate_hz"] is None
    assert sha256(source) == before == golden["source_sha256"]

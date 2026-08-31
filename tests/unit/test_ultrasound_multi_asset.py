from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import zarr

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.ultrasound.service import (
    parse_ultrasound_experiment,
    write_ultrasound_experiment,
)


def test_multiple_assets_keep_local_raw_ids_and_separate_zarr_groups(
    ultrasound_txt_factory: Callable[..., Path], tmp_path: Path
) -> None:
    first = ultrasound_txt_factory("first.txt", frame_ids=[0, 1], elapsed_times=[0.0, 10.0])
    second = ultrasound_txt_factory("second.txt", frame_ids=[0, 1], elapsed_times=[0.0, 10.0])
    experiment = Experiment(experiment_id="EXP_TEST", battery_id="CELL_TEST")
    assets = [
        DataAsset(
            asset_id="U001",
            experiment_id="EXP_TEST",
            modality="ultrasound",
            relative_path=Path(first.name),
        ),
        DataAsset(
            asset_id="U002",
            experiment_id="EXP_TEST",
            modality="ultrasound",
            relative_path=Path(second.name),
        ),
    ]

    parsed = parse_ultrasound_experiment(experiment, assets, tmp_path)
    output = write_ultrasound_experiment(parsed, tmp_path / "processed")

    frames = pd.read_parquet(output.frames_path)
    assert list(frames.groupby("ultrasound_asset_id")["frame_index_raw"].first()) == [0, 0]
    assert len(frames) == 4
    assert "waveform_0000" not in frames.columns
    assert frames["waveform_sample_count"].tolist() == [1250] * 4
    root = zarr.open_group(output.waveforms_path, mode="r")
    assert root["U001/waveform"].shape == (2, 1250)
    assert root["U002/waveform"].shape == (2, 1250)
    assert output.manifest_path.is_file()

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.ultrasound.custom_txt import UltrasoundFormatError
from battery_workbench.io.ultrasound.service import parse_ultrasound_asset


def asset(path: Path) -> DataAsset:
    return DataAsset(
        asset_id="U_TEST",
        experiment_id="EXP_TEST",
        modality="ultrasound",
        relative_path=Path(path.name),
        file_start_time="2024-01-01 00:00:00",
        parser_name="custom_txt",
        parser_version="0.1.0",
    )


def test_single_asset_preserves_raw_fields_and_absolute_time(
    ultrasound_txt_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = ultrasound_txt_factory()
    result = parse_ultrasound_asset(asset(path), tmp_path, battery_id="CELL_TEST")

    assert result.frame_count == 3
    assert result.frames[0].frame_index_raw == 0
    assert result.frames[0].unknown_field_1 == "unknown-0"
    assert result.frames[0].unknown_meta_0 == "meta-0"
    assert result.frames[0].unknown_meta_1 == "state-0"
    assert result.frames[0].unknown_tail == [str(index) for index in range(16)]
    assert result.absolute_timestamps[0].isoformat() == "2024-01-01T00:00:00.031000"
    assert result.waveforms.shape == (3, 1250)


def test_non_monotonic_elapsed_time_is_not_silently_sorted(
    ultrasound_txt_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = ultrasound_txt_factory(elapsed_times=[0.0, 20.0, 10.0])
    with pytest.raises(UltrasoundFormatError, match="elapsed_time_s"):
        parse_ultrasound_asset(asset(path), tmp_path, battery_id="CELL_TEST")


def test_frame_gap_is_preserved_and_reported(
    ultrasound_txt_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = ultrasound_txt_factory(frame_ids=[0, 1, 3])
    result = parse_ultrasound_asset(asset(path), tmp_path, battery_id="CELL_TEST")

    assert [frame.frame_index_raw for frame in result.frames] == [0, 1, 3]
    assert any("not contiguous" in warning for warning in result.warnings)


def test_missing_file_start_time_keeps_absolute_timestamp_unknown(
    ultrasound_txt_factory: Callable[..., Path], tmp_path: Path
) -> None:
    path = ultrasound_txt_factory()
    without_start = DataAsset(
        asset_id="U_TEST",
        experiment_id="EXP_TEST",
        modality="ultrasound",
        relative_path=Path(path.name),
    )

    result = parse_ultrasound_asset(without_start, tmp_path, battery_id="CELL_TEST")

    assert result.absolute_timestamps == [None, None, None]
    assert any("file_start_time is unavailable" in warning for warning in result.warnings)

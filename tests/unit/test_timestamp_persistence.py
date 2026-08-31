from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.timestamp_persistence import (
    write_timestamp_parquet,
)


def test_parquet_roundtrip_precision_t18(tmp_path: Path) -> None:
    """T18: microsecond timestamps survive parquet round-trip exactly."""
    df = pd.DataFrame(
        {
            "battery_id": ["CELL_X", "CELL_X"],
            "experiment_id": ["EXP_X", "EXP_X"],
            "ultrasound_asset_id": ["U001", "U001"],
            "frame_index_raw": [0, 1],
            "provisional_absolute_timestamp": [
                datetime(2024, 1, 6, 9, 52, 31, 31217),
                datetime(2024, 1, 6, 9, 52, 41, 31217),
            ],
            "timestamp_available": [True, True],
            "timezone_known": [False, False],
        }
    )
    path = write_timestamp_parquet(df, tmp_path / "out" / "ts.parquet")
    reread = pd.read_parquet(path)
    assert reread["provisional_absolute_timestamp"].iloc[0].microsecond == 31217
    assert reread["provisional_absolute_timestamp"].iloc[0] == datetime(
        2024, 1, 6, 9, 52, 31, 31217
    )


def test_input_checksum_t19(tmp_path: Path) -> None:
    """T19: the manifest records input checksums that stay stable."""
    frames = tmp_path / "frames.parquet"
    df = pd.DataFrame(
        {
            "frame_index_raw": [0],
            "elapsed_time_s": [0.031217],
            "ultrasound_asset_id": ["U001"],
        }
    )
    frames.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(frames, index=False)
    file_bytes = frames.read_bytes()

    # The time-anchor state input must exist for its checksum to be computed.
    anchors_path = tmp_path / "time_anchors.json"
    anchors_path.write_text('{"battery_id":"CELL_X"}', encoding="utf-8")
    anchor_bytes = anchors_path.read_bytes()

    from battery_workbench.synchronization.timestamp_persistence import (
        build_timestamp_manifest,
    )

    manifest = build_timestamp_manifest(
        battery_id="CELL_X",
        experiment_id="EXP_X",
        engine_version="0.1.0",
        frames_path=frames,
        time_anchor_state_path=anchors_path,
        output_path=tmp_path / "out.parquet",
        asset_row_counts={"U001": 1},
        warnings=[],
    )
    # Reading inputs does not mutate them.
    assert frames.read_bytes() == file_bytes
    assert anchors_path.read_bytes() == anchor_bytes
    # Manifest exposes input checksum keys.
    assert "input_checksums" in manifest
    assert "frames" in manifest["input_checksums"]
    assert "time_anchor_state" in manifest["input_checksums"]

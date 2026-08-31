from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.synchronization.timestamp_engine import (
    build_ultrasound_timestamps,
)
from battery_workbench.synchronization.timestamp_schemas import TimestampEngineConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
FRAMES = PROCESSED_ROOT / "ultrasound" / "CELL_001" / "EXP_001" / "frames.parquet"
ANCHORS = PROCESSED_ROOT / "synchronization" / "CELL_001" / "EXP_001" / "time_anchors.json"
CONFIG = TimestampEngineConfig.from_yaml(REPO_ROOT / "configs" / "timestamp_engine.yaml")


@pytest.mark.skipif(
    not (FRAMES.exists() and ANCHORS.exists()), reason="CELL_001 inputs not present"
)
def test_current_cell001_timestamp_engine(tmp_path: Path) -> None:
    """T23: real CELL_001/EXP_001 timestamp construction."""
    report = build_ultrasound_timestamps(
        frames_path=FRAMES,
        time_anchor_state_path=ANCHORS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    assert report.experiment_id == "EXP_001"
    assert report.battery_id == "CELL_001"
    assert report.input_frame_count == 3999
    assert report.output_frame_count == 3999
    assert report.validated_sync is False
    assert report.status in ("PASS", "PASS_WITH_WARNINGS")

    u001 = next(a for a in report.assets if a.asset_id == "U001")
    assert u001.frame_count == 3999
    assert u001.timestamp_available_count == 3999
    assert u001.anchor_status == "PROVISIONAL"
    assert u001.is_elapsed_strictly_increasing is True

    out_df = pd.read_parquet(
        tmp_path
        / "synchronization"
        / "CELL_001"
        / "EXP_001"
        / "timestamped_ultrasound_frames.parquet"
    )
    assert len(out_df) == 3999
    # First / last provisional timestamps match the anchor-derived baseline.
    assert out_df["provisional_absolute_timestamp"].iloc[0] == pd.Timestamp(
        "2024-01-06T09:52:31.031217"
    )
    assert out_df["provisional_absolute_timestamp"].iloc[-1] == pd.Timestamp(
        "2024-01-06T20:58:51.030000"
    )


@pytest.mark.skipif(
    not (FRAMES.exists() and ANCHORS.exists()), reason="CELL_001 inputs not present"
)
def test_current_cell001_golden_frames_t24(tmp_path: Path) -> None:
    """T24: golden frames 0/1000/2000/3000/3998 independently verified."""
    build_ultrasound_timestamps(
        frames_path=FRAMES,
        time_anchor_state_path=ANCHORS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    out_df = pd.read_parquet(
        tmp_path
        / "synchronization"
        / "CELL_001"
        / "EXP_001"
        / "timestamped_ultrasound_frames.parquet"
    )
    anchor = pd.Timestamp("2024-01-06T09:52:31")
    index = {0, 1000, 2000, 3000, 3998}
    for frame_idx in index:
        row = out_df[out_df["frame_index_raw"] == frame_idx].iloc[0]
        elapsed = float(row["elapsed_time_s"])
        expected = anchor + pd.Timedelta(seconds=elapsed)
        assert row["provisional_absolute_timestamp"] == expected


def test_timestamp_engine_config_loads() -> None:
    """config from_yaml parses the OFFSET_ONLY policy."""
    cfg = TimestampEngineConfig.from_yaml(REPO_ROOT / "configs" / "timestamp_engine.yaml")
    assert cfg.clock.model_type == "OFFSET_ONLY"
    assert cfg.clock.scale == 1.0
    assert cfg.clock.drift_enabled is False

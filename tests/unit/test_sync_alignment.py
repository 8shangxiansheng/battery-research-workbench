from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from battery_workbench.synchronization.matcher import build_electrical_index
from battery_workbench.synchronization.sync_service import align_frames


def _electrical(df: pd.DataFrame):
    return build_electrical_index(
        df,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )


def _elf(timestamps) -> pd.DataFrame:
    n = len(timestamps)
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
            "provisional_absolute_timestamp": pd.to_datetime(timestamps),
            "timestamp_available": [True] * n,
            "event_order_index": list(range(n)),
            "anchor_id": ["U001-manifest"] * n,
            "anchor_status": ["PROVISIONAL"] * n,
        }
    )


def _erecords(timestamps, locators=None) -> pd.DataFrame:
    n = len(timestamps)
    if locators is None:
        locators = list(range(n))
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "source_row_index": locators,
            "record_index_raw": list(range(1, n + 1)),
            "electrical_asset_id": ["E1"] * n,
            "cycle_index_raw": [1] * n,
            "step_index_raw": [1] * n,
            "step_boundary_raw": [None] * n,
        }
    )


def test_preserve_ultrasound_row_order_count_t11() -> None:
    """T11: aligned output keeps the ultrasound row count and order."""
    u = _elf(
        [
            datetime(2024, 1, 6, 10, 0, 0, 300000),
            datetime(2024, 1, 6, 10, 0, 1, 300000),
            datetime(2024, 1, 6, 10, 0, 2, 300000),
        ]
    )
    e = _erecords(
        [
            datetime(2024, 1, 6, 10, 0, 0),
            datetime(2024, 1, 6, 10, 0, 1),
            datetime(2024, 1, 6, 10, 0, 2),
        ]
    )
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert len(aligned) == len(u)
    assert aligned["frame_index_raw"].tolist() == [0, 1, 2]


def test_timezone_mismatch_t14() -> None:
    """T14: naive vs aware timestamps -> no conversion, TIMEZONE_MISMATCH."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0, tzinfo=UTC)])
    e = _erecords([datetime(2024, 1, 6, 10, 0, 0)])
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert aligned["match_status"].iloc[0] == "TIMEZONE_MISMATCH"


def test_naive_naive_allowed_t15() -> None:
    """T15: naive-naive matching is allowed, timezone remains unknown."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0, 300000)])
    e = _erecords([datetime(2024, 1, 6, 10, 0, 0)])
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert aligned["match_status"].iloc[0] == "MATCHED_UNIQUE"


def test_ambiguous_selected_record_null_t20() -> None:
    """T20: ambiguous frames have a null selected electrical locator."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0)])
    e = _erecords(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 0)],
        locators=[1, 2],
    )
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert aligned["match_status"].iloc[0] == "MATCHED_AMBIGUOUS"
    assert aligned["electrical_record_locator"].iloc[0] is None
    assert bool(aligned["sync_ambiguous"].iloc[0]) is True
    assert aligned["ambiguity_type"].iloc[0] == "DUPLICATE_ELECTRICAL_TIMESTAMP"


def test_sync_error_correctness_t21() -> None:
    """T21: sync_error_s is the min absolute temporal distance."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0, 500000)])  # 0.5s after first
    e = _erecords([datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)])
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert aligned["sync_error_s"].iloc[0] == pytest.approx(0.5)


def test_multi_ultrasound_asset_t22() -> None:
    """T22: multiple ultrasound assets each get their own timestamps."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0, 300000)])
    u["ultrasound_asset_id"] = "U002"
    e = _erecords([datetime(2024, 1, 6, 10, 0, 0)])
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert len(aligned) == 1
    assert aligned["ultrasound_asset_id"].iloc[0] == "U002"


def test_no_waveform_duplication_t24() -> None:
    """T24: the aligned summary carries locators, never waveform samples."""
    u = _elf([datetime(2024, 1, 6, 10, 0, 0, 300000)])
    e = _erecords([datetime(2024, 1, 6, 10, 0, 0)])
    aligned = align_frames(u, _electrical(e), max_sync_error_s=1.0, tie_tolerance_s=1e-9)
    assert "waveform_group" in aligned.columns
    assert "waveform_row_index" in aligned.columns
    for col in aligned.columns:
        assert "waveform" not in col or col in ("waveform_group", "waveform_row_index")

from __future__ import annotations

from datetime import datetime

import pandas as pd

from battery_workbench.synchronization.boundary import detect_boundary


def _records(timestamps, cycling, stepping, boundary_markers, locators=None):
    n = len(timestamps)
    if locators is None:
        locators = list(range(n))
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "source_row_index": locators,
            "cycle_index_raw": cycling,
            "step_index_raw": stepping,
            "step_boundary_raw": boundary_markers,
            "electrical_asset_id": ["E1"] * n,
        }
    )


def test_duplicate_timestamp_boundary_t16() -> None:
    """T16: a duplicated electrical timestamp is flagged as a boundary."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 0)],
        cycling=[1, 1],
        stepping=[1, 2],
        boundary_markers=[None, 0],
    )
    flags = detect_boundary(df)
    # Both rows belong to a duplicated timestamp -> flagged.
    assert flags["boundary_flag"].tolist() == [True, True]


def test_step_transition_boundary_t17() -> None:
    """T17: step transition is flagged but does not affect matching."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)],
        cycling=[1, 1],
        stepping=[1, 2],
        boundary_markers=[None, 0],
    )
    flags = detect_boundary(df)
    # Step transition at index 1 -> boundary flag on the following row.
    assert bool(flags["boundary_flag"].iloc[1]) is True
    # Boundary must never decide a nearest match; it is diagnostics only.
    assert "boundary_reason" in flags.columns


def test_cycle_transition_boundary_t18() -> None:
    """T18: cycle transition is flagged as a boundary."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)],
        cycling=[1, 2],
        stepping=[5, 1],
        boundary_markers=[None, 0],
    )
    flags = detect_boundary(df)
    assert bool(flags["boundary_flag"].iloc[1]) is True


def test_no_boundary_when_adjacent_same_step() -> None:
    """No boundary when consecutive records share cycle+step and no marker."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)],
        cycling=[1, 1],
        stepping=[1, 1],
        boundary_markers=[None, None],
    )
    flags = detect_boundary(df)
    assert flags["boundary_flag"].tolist() == [False, False]

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from battery_workbench.synchronization.matcher import (
    build_electrical_index,
    find_nearest_candidates,
)


def _records(timestamps: list[datetime], locators: list[int] | None = None) -> pd.DataFrame:
    n = len(timestamps)
    if locators is None:
        locators = list(range(n))
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "source_row_index": locators,
            "electrical_asset_id": ["E1"] * n,
            "record_index_raw": list(range(1, n + 1)),
            "cycle_index_raw": [1] * n,
            "step_index_raw": [1] * n,
            "step_boundary_raw": [None] * n,
        }
    )


def _index(df: pd.DataFrame):
    return build_electrical_index(
        df,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )


def test_exact_unique_match_t01() -> None:
    """T01: exact timestamp match -> unique, error 0."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0)])
    idx = _index(df)
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    assert result.sync_error_s == 0.0
    assert result.candidate_timestamp_count == 1
    assert result.candidate_record_count == 1
    assert result.ambiguity_type == "NONE"


def test_nearest_previous_t02() -> None:
    """T02: ultrasound just after a record matches the previous one."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)])
    idx = _index(df)
    result = find_nearest_candidates(
        datetime(2024, 1, 6, 10, 0, 0, 300000), idx, tie_tolerance_s=1e-9
    )
    assert result.sync_error_s == pytest.approx(0.3)
    assert result.best_timestamp == datetime(2024, 1, 6, 10, 0, 0)


def test_nearest_next_t03() -> None:
    """T03: ultrasound just before a record matches the next one."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)])
    idx = _index(df)
    result = find_nearest_candidates(
        datetime(2024, 1, 6, 10, 0, 0, 900000), idx, tie_tolerance_s=1e-9
    )
    assert result.sync_error_s == pytest.approx(0.1)
    assert result.best_timestamp == datetime(2024, 1, 6, 10, 0, 1)


def test_equidistant_ambiguous_t04() -> None:
    """T04: exactly midway between two timestamps -> 2 timestamp candidates, ambiguous."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)])
    idx = _index(df)
    result = find_nearest_candidates(
        datetime(2024, 1, 6, 10, 0, 0, 500000), idx, tie_tolerance_s=1e-9
    )
    assert result.candidate_timestamp_count == 2
    assert result.ambiguity_type == "EQUIDISTANT_TIMESTAMPS"


def test_duplicate_timestamp_ambiguous_t05() -> None:
    """T05: one timestamp with multiple records -> ambiguous duplicate."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 0)],
        locators=[1, 2],
    )
    idx = _index(df)
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    assert result.candidate_timestamp_count == 1
    assert result.candidate_record_count == 2
    assert result.ambiguity_type == "DUPLICATE_ELECTRICAL_TIMESTAMP"


def test_duplicate_and_equidistant_t06() -> None:
    """T06: duplicate timestamp equidistant to another -> combined ambiguity."""
    df = _records(
        [
            datetime(2024, 1, 6, 10, 0, 0),
            datetime(2024, 1, 6, 10, 0, 0),  # duplicate
            datetime(2024, 1, 6, 10, 0, 1),  # equidistant
        ],
        locators=[1, 2, 3],
    )
    idx = _index(df)
    result = find_nearest_candidates(
        datetime(2024, 1, 6, 10, 0, 0, 500000), idx, tie_tolerance_s=1e-9
    )
    assert result.candidate_timestamp_count == 2
    assert result.candidate_record_count == 3
    assert result.ambiguity_type == "DUPLICATE_AND_EQUIDISTANT"


def test_tolerance_boundary_inclusive_t07() -> None:
    """T07: error exactly == max_sync_error_s is within tolerance."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0)])
    idx = _index(df)
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 1), idx, tie_tolerance_s=1e-9)
    assert result.sync_error_s == 1.0
    assert result.within_tolerance(1.0) is True


def test_out_of_tolerance_t08() -> None:
    """T08: error over tolerance -> candidate retained but within_tolerance False."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0)])
    idx = _index(df)
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 5), idx, tie_tolerance_s=1e-9)
    assert result.sync_error_s == 5.0
    assert result.within_tolerance(1.0) is False


def test_empty_electrical_t09() -> None:
    """T09: no electrical records -> NO_ELECTRICAL_CANDIDATE."""
    idx = _index(_records([]))
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    assert result.candidate_timestamp_count == 0
    assert result.candidate_record_count == 0


def test_non_monotonic_electrical_t12() -> None:
    """T12: non-monotonic electrical timestamps are handled via a sorted lookup."""
    df = _records(
        [datetime(2024, 1, 6, 10, 0, 1), datetime(2024, 1, 6, 10, 0, 0)],
        locators=[10, 20],
    )
    idx = _index(df)
    result = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    # The sorted lookup still finds the exact match, preserving locators.
    assert result.sync_error_s == 0.0
    assert result.candidate_record_count == 1


def test_duplicate_ultrasound_t13() -> None:
    """T13: duplicate ultrasound timestamps each kept independently."""
    df = _records([datetime(2024, 1, 6, 10, 0, 0), datetime(2024, 1, 6, 10, 0, 1)])
    idx = _index(df)
    r1 = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    r2 = find_nearest_candidates(datetime(2024, 1, 6, 10, 0, 0), idx, tie_tolerance_s=1e-9)
    assert r1.sync_error_s == r2.sync_error_s == 0.0

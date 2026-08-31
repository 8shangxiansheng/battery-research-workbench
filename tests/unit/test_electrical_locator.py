from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from battery_workbench.multimodal.electrical_index import (
    LocatorError,
    build_aux_index,
    build_electrical_index,
    normalize_locator,
    resolve_selected,
)


def test_normalize_locator_valid_string_integer() -> None:
    """C: \"2\" parses to integer 2 (explicit, no implicit coercion)."""
    assert normalize_locator("2") == 2
    assert normalize_locator("39996") == 39996


@pytest.mark.parametrize("bad", ["", "abc", "2.5", "--1", "1e3"])
def test_normalize_locator_invalid(bad: str) -> None:
    """C: non-canonical locator strings raise LocatorError."""
    with pytest.raises(LocatorError):
        normalize_locator(bad)


def _records_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_row_index": [2, 3, 4, 5],
            "record_index_raw": [1, 2, 3, 4],
            "electrical_asset_id": ["E1", "E1", "E1", "E1"],
            "timestamp": pd.to_datetime(
                [
                    datetime(2024, 1, 6, 10, 0, 0),
                    datetime(2024, 1, 6, 10, 0, 1),
                    datetime(2024, 1, 6, 10, 0, 2),
                    datetime(2024, 1, 6, 10, 0, 3),
                ]
            ),
            "cycle_index_raw": [1, 1, 1, 1],
            "step_index_raw": [1, 1, 1, 1],
            "voltage_v": [3.0, 3.1, 3.2, 3.3],
            "current_a": [1.0, 0.0, 1.0, 0.0],
            "capacity_ah": [0.0, 0.1, 0.0, 0.1],
        }
    )


def test_resolve_selected_exact_one_row() -> None:
    """selected locator resolves to exactly one record."""
    idx = build_electrical_index(_records_df())
    rec = resolve_selected("3", idx)
    assert rec["source_row_index"] == 3
    assert rec["voltage_v"] == 3.1


def test_no_timestamp_fallback_rematch() -> None:
    """The selected locator wins even when another row has a closer/full-equal timestamp.

    Row A (locator \"4\") is selected; row B (locator \"2\") has an identical but
    earlier timestamp. BRW-011 must still use row A, never re-match by timestamp.
    """
    idx = build_electrical_index(_records_df())
    rec = resolve_selected("4", idx)
    # Selected by locator, NOT by nearest timestamp.
    assert rec["source_row_index"] == 4
    assert rec["capacity_ah"] == 0.0


def test_resolve_missing_locator_integrity_error() -> None:
    """missing selected locator -> LocatorError (never timestamp fallback)."""
    idx = build_electrical_index(_records_df())
    with pytest.raises(LocatorError):
        resolve_selected("999", idx)


def test_resolve_duplicated_locator_integrity_error() -> None:
    """duplicated selected locator -> LocatorError (must map to exactly one row).

    The duplicate is detected at index build time (source_row_index is a unique
    key), which surfaces the same integrity error as resolution would.
    """
    df = _records_df()
    df = pd.concat(
        [df, pd.DataFrame(df.iloc[2:3])], ignore_index=True
    )  # add a dup source_row_index=4
    with pytest.raises(LocatorError):
        build_electrical_index(df)


def test_duplicated_locator_in_input_index() -> None:
    """A duplicated source_row_index in the input is a schema integrity error."""
    df = _records_df()
    df = pd.concat([df, pd.DataFrame(df.iloc[0:1])], ignore_index=True)
    with pytest.raises(LocatorError):
        build_electrical_index(df)


def _aux_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_row_index": [3, 4, 5],
            "temperature_c": [25.0, 25.1, 25.2],
            "temperature_channel": ["T1", "T1", "T1"],
        }
    )


def test_aux_exact_join_success() -> None:
    """E Case1: record locator has an aux row -> temperature enriched."""
    aux = build_aux_index(_aux_df())
    assert aux[3] == 25.0
    assert aux[4] == 25.1


def test_aux_missing_temperature_null() -> None:
    """E Case2: record locator has no aux row -> temperature null / limitation."""
    aux = build_aux_index(_aux_df())
    assert 2 not in aux  # locator 2 has no aux row


def test_aux_duplicate_locator_integrity_error() -> None:
    """E Case3: one source_row_index maps to multiple aux rows -> integrity error."""
    df = pd.concat(
        [
            _aux_df(),
            pd.DataFrame(
                {"source_row_index": [3], "temperature_c": [99.0], "temperature_channel": ["T1"]}
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(LocatorError):
        build_aux_index(df)

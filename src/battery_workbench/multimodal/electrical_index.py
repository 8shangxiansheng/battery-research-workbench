"""Exact electrical locator index + normalization for BRW-011.

BRW-010 stores ``electrical_record_locator`` as a string (e.g. ``"2"``) that is
really the BRW-003 ``source_row_index``. BRW-011 normalizes it explicitly and
resolves it through an *exact* index — never by timestamp, never by row
position. This module contains no time-matching logic.
"""

from __future__ import annotations

import pandas as pd


class LocatorError(ValueError):
    """Raised when a locator is malformed, missing, or non-unique."""


def normalize_locator(locator: str | int | None) -> int:
    """Parse a canonical locator string/integer to a non-negative int.

    Accepts plain integer text (``"2"`` / ``2``). Rejects empty, non-numeric,
    fractional, NaN, or malformed values. No implicit pandas coercion.
    """
    if locator is None:
        raise LocatorError("locator is None")
    if isinstance(locator, float) and pd.isna(locator):
        raise LocatorError("locator is NaN")
    text = str(locator).strip()
    if not text:
        raise LocatorError("locator is empty")
    # Reject anything that is not a canonical unsigned integer literal.
    if not text.isdigit():
        raise LocatorError(f"locator is not an unsigned integer literal: {locator!r}")
    return int(text)


def build_electrical_index(
    records: pd.DataFrame,
    *,
    locator_col: str = "source_row_index",
) -> dict[int, dict]:
    """Build an exact ``source_row_index -> record`` map.

    Every row must have a unique locator. A duplicated locator is an integrity
    error (it cannot resolve to exactly one record). Never uses timestamps.
    """
    if records.empty:
        return {}
    col = records[locator_col]
    if not col.is_unique:
        raise LocatorError("source_row_index is not unique in records")
    index: dict[int, dict] = {}
    for _, row in records.iterrows():
        loc = normalize_locator(row[locator_col])
        if loc in index:
            raise LocatorError(f"duplicate locator {loc}")
        index[loc] = row.to_dict()
    return index


def build_aux_index(
    aux: pd.DataFrame,
    *,
    locator_col: str = "source_row_index",
    value_col: str = "temperature_c",
) -> dict[int, float]:
    """Build an exact ``source_row_index -> temperature_c`` map.

    A duplicated aux locator is an integrity error. Missing values are simply
    absent from the map (caller reports them as null).
    """
    if aux.empty:
        return {}
    col = aux[locator_col]
    if not col.is_unique:
        raise LocatorError("aux source_row_index is not unique")
    index: dict[int, float] = {}
    for _, row in aux.iterrows():
        loc = normalize_locator(row[locator_col])
        if loc in index:
            raise LocatorError(f"duplicate aux locator {loc}")
        index[loc] = float(row[value_col])
    return index


def resolve_selected(
    locator: str | int | None,
    index: dict[int, dict],
) -> dict:
    """Resolve a selected locator to exactly one record.

    Raises ``LocatorError`` when the locator is missing, malformed, or has no
    matching record. Never falls back to timestamp matching.
    """
    loc = normalize_locator(locator)
    if loc not in index:
        raise LocatorError(f"selected locator not found: {locator!r}")
    return index[loc]

"""BRW-011 exact electrical index over the composite selected identity.

Canonical selected identity at BRW-010 is the pair::

    (electrical_asset_id, electrical_record_locator)

A locator alone is ambiguous across electrical assets (E001 row 10 vs E002
row 10). This index keys records by the composite pair; ``resolve_selected``
requires the asset id and NEVER falls back to locator-only lookup and NEVER
re-matches by timestamp.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel


class LocatorError(ValueError):
    """Integrity error for malformed/ambiguous selected-identity lookups."""


def normalize_locator(locator: str | int | None) -> int:
    if locator is None:
        raise LocatorError("locator is empty")
    text = str(locator).strip()
    if not text:
        raise LocatorError("locator is empty")
    # Reject anything that is not a canonical unsigned integer literal.
    if not text.isdigit():
        raise LocatorError(f"locator is not an unsigned integer literal: {locator!r}")
    return int(text)


def normalize_asset_id(asset_id: str | int | None) -> str:
    if asset_id is None:
        raise LocatorError("electrical_asset_id is required (composite identity)")
    text = str(asset_id).strip()
    if not text or text.lower() in {"none", "nan"}:
        raise LocatorError("electrical_asset_id is required (composite identity)")
    return text


def build_electrical_index(
    records: pd.DataFrame,
    *,
    locator_col: str = "source_row_index",
    asset_col: str = "electrical_asset_id",
) -> dict[tuple[str, int], dict[str, Any]]:
    """Build an exact ``(electrical_asset_id, source_row_index) -> record`` map.

    The same locator may exist on different assets — those are distinct
    records. A duplicated (asset, locator) pair is an integrity error.
    Timestamps are never used for lookup.
    """
    if records.empty:
        return {}
    required = {locator_col, asset_col}
    missing = required - set(records.columns)
    if missing:
        raise LocatorError(f"records missing composite identity columns: {sorted(missing)}")
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for _, row in records.iterrows():
        asset = normalize_asset_id(row[asset_col])
        loc = normalize_locator(row[locator_col])
        key = (asset, loc)
        if key in index:
            raise LocatorError(f"duplicate composite identity {key}")
        value: dict[str, Any] = {str(k): v for k, v in row.to_dict().items()}
        index[key] = value
    return index


def build_aux_index(
    aux: pd.DataFrame,
    *,
    locator_col: str = "source_row_index",
    value_col: str = "temperature_c",
) -> dict[tuple[str, int], float]:
    """Exact ``(electrical_asset_id, source_row_index) -> temperature_c`` map.

    A duplicated composite aux identity is an integrity error. Missing values
    are simply absent from the map (caller reports them as null).
    """
    if aux.empty:
        return {}
    asset_col = "electrical_asset_id"
    required = {locator_col, value_col, asset_col}
    missing = required - set(aux.columns)
    if missing:
        raise LocatorError(f"aux missing composite identity columns: {sorted(missing)}")
    index: dict[tuple[str, int], float] = {}
    for _, row in aux.iterrows():
        asset = normalize_asset_id(row[asset_col])
        loc = normalize_locator(row[locator_col])
        key = (asset, loc)
        if key in index:
            raise LocatorError(f"duplicate composite aux identity {key}")
        index[key] = float(row[value_col])
    return index


class SelectedElectricalRecord(BaseModel):
    """One resolved selected electrical record (composite identity)."""

    electrical_asset_id: str
    electrical_record_locator: int
    record: dict[str, Any]


def resolve_selected(
    locator: str | int | None,
    index: dict[tuple[str, int], dict[str, Any]],
    *,
    asset_id: str | int | None,
) -> dict[str, Any]:
    """Resolve a selected record by composite (asset_id, locator).

    Raises ``LocatorError`` when the identity is missing/malformed/absent, or
    when the asset id is missing (no locator-only fallback). Never falls back
    to timestamp matching.
    """
    asset = normalize_asset_id(asset_id)
    loc = normalize_locator(locator)
    key = (asset, loc)
    if key not in index:
        raise LocatorError(f"selected composite identity not found in electrical index: {key}")
    return index[key]

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.io.electrical.custom_excel import ElectricalWorkbookData, RawSheetData


class ElectricalValidationError(ValueError):
    """Raised when an electrical workbook cannot be parsed without data loss."""


def validation_context(
    *,
    asset_id: str,
    source_file: Path,
    sheet: str | None = None,
    column: str | None = None,
    source_row_index: int | None = None,
) -> str:
    parts = [f"asset_id={asset_id}", f"file={source_file}"]
    if sheet is not None:
        parts.append(f"sheet={sheet}")
    if column is not None:
        parts.append(f"column={column}")
    if source_row_index is not None:
        parts.append(f"source_row_index={source_row_index}")
    return " ".join(parts)


def validate_required_sheets(
    workbook: ElectricalWorkbookData, *, asset_id: str, source_file: Path
) -> None:
    missing = sorted({"record", "cycle", "step"} - workbook.sheets.keys())
    if missing:
        context = validation_context(asset_id=asset_id, source_file=source_file)
        raise ElectricalValidationError(f"{context}: missing required sheets {missing}")


def validate_required_columns(
    sheet: RawSheetData,
    required: Iterable[str],
    *,
    asset_id: str,
    source_file: Path,
) -> None:
    missing = sorted(set(required) - set(sheet.headers))
    if missing:
        context = validation_context(asset_id=asset_id, source_file=source_file, sheet=sheet.name)
        raise ElectricalValidationError(f"{context}: missing required columns {missing}")


def is_fully_blank(values: Iterable[Any]) -> bool:
    return all(value is None or (isinstance(value, str) and not value.strip()) for value in values)


def validate_required_values(
    values: dict[str, Any],
    required: Iterable[str],
    *,
    asset_id: str,
    source_file: Path,
    sheet: str,
    source_row_index: int,
) -> None:
    for column in required:
        value = values[column]
        if value is None or (isinstance(value, str) and not value.strip()):
            context = validation_context(
                asset_id=asset_id,
                source_file=source_file,
                sheet=sheet,
                column=column,
                source_row_index=source_row_index,
            )
            raise ElectricalValidationError(f"{context}: required value is blank")


def validate_non_decreasing_timestamps(
    timestamps: pd.Series,
    *,
    asset_id: str,
    source_file: Path,
    sheet: str,
) -> None:
    if not timestamps.is_monotonic_increasing:
        context = validation_context(
            asset_id=asset_id, source_file=source_file, sheet=sheet, column="timestamp"
        )
        raise ElectricalValidationError(f"{context}: timestamps must be non-decreasing")


def timestamp_order_diagnostic(
    timestamps: pd.Series,
    source_rows: pd.Series,
    *,
    asset_id: str,
    source_file: Path,
    sheet: str,
) -> str | None:
    """Describe backward transitions without reordering or dropping raw rows.

    Synchronization builds a timestamp-sorted lookup copy and retains each
    source-row locator, so source order remains auditable without blocking
    records that contain explicit absolute timestamps.
    """
    backwards: list[tuple[int, int, float]] = []
    values = timestamps.tolist()
    rows = source_rows.tolist()
    for index in range(1, len(values)):
        previous = pd.Timestamp(values[index - 1])
        current = pd.Timestamp(values[index])
        delta_s = (current - previous).total_seconds()
        if delta_s < 0:
            backwards.append((int(rows[index - 1]), int(rows[index]), delta_s))
    if not backwards:
        return None

    context = validation_context(
        asset_id=asset_id, source_file=source_file, sheet=sheet, column="timestamp"
    )
    details = ", ".join(f"{left}->{right} ({delta_s:g}s)" for left, right, delta_s in backwards[:5])
    return (
        f"{context}: found {len(backwards)} backward timestamp transition(s); "
        f"rows preserved in source order without repair; first transitions: {details}"
    )

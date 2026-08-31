"""Deterministic condition-filtering over MeasurementEvents.

``apply_condition_slice`` applies a typed ``ConditionSliceSpec`` to a frame of
canonical measurement events. Same-field values combine with OR; different
fields combine with AND. Numeric/time ranges are inclusive. Numeric-null rows
are excluded by default unless ``include_null_numeric_values`` is set. No
waveform / feature processing occurs here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.analysis.schemas import ConditionSliceSpec

# Canonical column names used in MeasurementEvents.
_COL = {
    "cycle_indices": "cycle_index_raw",
    "step_indices": "step_index_raw",
    "step_types": "step_type",
    "battery_ids": "battery_id",
    "experiment_ids": "experiment_id",
    "ultrasound_asset_ids": "ultrasound_asset_id",
}
# (spec-suffix, dataframe column, breakdown key)
_RANGE_FIELDS = [
    ("voltage_v", "voltage_v", "voltage"),
    ("current_a", "current_a", "current"),
    ("capacity_ah", "capacity_ah", "capacity"),
    ("temperature_c", "temperature_c", "temperature"),
    ("soc_dod_percent", "soc_dod_percent", "soc_dod"),
    ("elapsed_time_s", "elapsed_time_s", "time"),
]


def _in_range(values: pd.Series, min_v: Any, max_v: Any) -> pd.Series:
    """Inclusive range mask; handles one-sided bounds (min or max may be None)."""
    mask = pd.Series(True, index=values.index)
    if min_v is not None:
        mask &= values >= min_v
    if max_v is not None:
        mask &= values <= max_v
    return mask


def _list_apply(df: pd.DataFrame, values: list, col: str) -> pd.DataFrame:
    return df[df[col].isin(values)]


def apply_condition_slice(
    events: pd.DataFrame,
    spec: ConditionSliceSpec,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Filter ``events`` by ``spec``; returns ``(frame, filter_breakdown)``.

    Deterministic; never mutates input; never computes waveform features.
    """
    from battery_workbench.analysis.validation import validate_spec

    validate_spec(spec)
    include_null = spec.include_null_numeric_values

    breakdown: dict[str, int] = {"rows_before": len(events)}
    df = events

    # Quality.
    if spec.analysis_eligible_only:
        df = df[df["analysis_eligible"] == True]
    breakdown["rows_after_quality"] = len(df)
    if spec.event_quality_statuses:
        df = _list_apply(df, spec.event_quality_statuses, "event_quality_status")
    if spec.max_sync_error_s is not None:
        df = df[df["sync_error_s"] <= spec.max_sync_error_s]
    if spec.boundary_flag is not None:
        df = df[df["boundary_flag"] == spec.boundary_flag]

    # Identity.
    for attr, col in (
        ("battery_ids", "battery_id"),
        ("experiment_ids", "experiment_id"),
        ("ultrasound_asset_ids", "ultrasound_asset_id"),
    ):
        values = getattr(spec, attr)
        if values:
            df = _list_apply(df, values, col)
    breakdown["rows_after_identity"] = len(df)

    # Protocol.
    if spec.cycle_indices:
        df = _list_apply(df, spec.cycle_indices, _COL["cycle_indices"])
    breakdown["rows_after_cycle"] = len(df)
    if spec.step_indices:
        df = _list_apply(df, spec.step_indices, _COL["step_indices"])
    if spec.step_types:
        df = _list_apply(df, spec.step_types, _COL["step_types"])
    breakdown["rows_after_step"] = len(df)

    # Numeric ranges (inclusive). Split so each stage is recorded.
    for attr, col, key in _RANGE_FIELDS:
        min_v = getattr(spec, f"{attr}_min")
        max_v = getattr(spec, f"{attr}_max")
        if min_v is not None or max_v is not None:
            if include_null:
                # Retain rows with a null value; only reject rows with an
                # out-of-range non-null value.
                df = df[df[col].isna() | _in_range(df[col], min_v, max_v)]
            else:
                df = df[df[col].notna() & _in_range(df[col], min_v, max_v)]
            breakdown[f"rows_after_{key}"] = len(df)

    # Time.
    if spec.provisional_timestamp_start is not None or spec.provisional_timestamp_end is not None:
        col = "provisional_absolute_timestamp"
        if spec.provisional_timestamp_start is not None:
            df = df[df[col] >= spec.provisional_timestamp_start]
        if spec.provisional_timestamp_end is not None:
            df = df[df[col] <= spec.provisional_timestamp_end]
    breakdown["rows_after_time"] = len(df)

    return df, breakdown

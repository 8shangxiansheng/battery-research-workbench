"""Canonical column-role assignments for BRW-016 datasets.

Every column in a dataset carries exactly one role. Roles are deterministic
lookups — no per-run configuration drift.
"""

from __future__ import annotations

from battery_workbench.datasets.schemas import ColumnRole

_IDENTITY = frozenset(
    {
        "measurement_event_id",
        "battery_id",
        "experiment_id",
        "ultrasound_asset_id",
        "frame_index_raw",
        "event_order_index",
        "waveform_group",
        "waveform_row_index",
    }
)
_GROUP = frozenset(
    {
        "battery_group_id",
        "experiment_group_id",
        "cycle_group_id",
        "label_group_id",
        "independent_soh_group_id",
        "temporal_block_id",
    }
)
_TARGET = frozenset({"soc_reference_percent", "soh_capacity_reference_percent"})
_CONTEXT = frozenset(
    {
        "cycle_index_raw",
        "step_index_raw",
        "step_type",
        "voltage_v",
        "current_a",
        "capacity_ah",
        "temperature_c",
        "elapsed_time_s",
        "provisional_absolute_timestamp",
    }
)
_QUALITY = frozenset(
    {
        "sync_error_s",
        "event_quality_status",
        "analysis_eligible",
        "feature_status",
        "soc_reference_quality",
        "soc_label_temporality",
        "soc_formula_version",
        "soc_anchor_quality",
        "soh_reference_quality",
        "soh_label_eligible",
        "soh_reference_cycle_index",
    }
)
_FORBIDDEN = frozenset(
    {
        "soc_dod_percent",
        "soc_reference_capacity_ah",
        "soc_integral_unbounded_percent",
        "capacity_retention_percent",
        "discharge_capacity_measured_ah",
        "charge_capacity_measured_ah",
        "soh_reference_capacity_ah",
    }
)
_PROVENANCE = frozenset(
    {
        "feature_set_id",
        "label_set_id",
        "parameter_set_id",
        "analysis_slice_id",
        "dataset_id",
        "xcorr_reference_measurement_event_id",
    }
)


def get_column_role(name: str) -> ColumnRole:
    if name in _TARGET:
        return ColumnRole.TARGET
    if name in _FORBIDDEN:
        return ColumnRole.FORBIDDEN_PREDICTOR
    if name in _IDENTITY:
        return ColumnRole.IDENTITY
    if name in _GROUP:
        return ColumnRole.GROUP
    if name in _PROVENANCE:
        return ColumnRole.PROVENANCE
    if name in _QUALITY:
        return ColumnRole.QUALITY
    if name in _CONTEXT:
        return ColumnRole.CONTEXT
    # Remaining waveform/envelope/xcorr columns are ultrasound predictors.
    if name.startswith(("waveform_", "envelope_", "xcorr_")):
        return ColumnRole.PREDICTOR
    return ColumnRole.CONTEXT


def predictor_enabled(role: ColumnRole) -> bool:
    return role == ColumnRole.PREDICTOR

"""BRW-017 V2: feature_label_analysis table.

Joins candidate ultrasound features with SOC/SOH reference labels on
measurement_event_id (exact join) for exploratory correlation/trend analysis.

This table is EXPLORATORY_FULL_DATA by construction: it spans the full
dataset without grouped splits. Formal ML-safe feature selection must be
redone inside grouped TRAIN splits (BRW-018/019).
"""

from __future__ import annotations

import pandas as pd

from battery_workbench.datasets.joins import exact_event_join

# Columns that identify the row and its group structure (always kept).
_IDENTITY_COLUMNS = [
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "cycle_index_raw",
]

# SOC/SOH reference label columns (target-side of the analysis table).
_LABEL_COLUMNS = [
    "soc_reference_percent",
    "soh_capacity_reference_percent",
]

# Formula intermediates and vendor fields that must never enter the
# analysis table (same non-predictor policy as the dataset builder).
_EXCLUDED_FROM_ANALYSIS = [
    "soc_integral_unbounded_percent",
    "soc_reference_capacity_ah",
    "soh_reference_capacity_ah",
    "soc_dod_percent",
    "capacity_ah",
]


def build_feature_label_analysis(
    *,
    features: pd.DataFrame,
    event_labels: pd.DataFrame,
    cycle_labels: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Exact-join candidate features with reference labels per measurement_event_id."""
    joined = exact_event_join(features, event_labels, report_surplus=False)
    if isinstance(joined, tuple):  # pragma: no cover - report_surplus=False never returns tuple
        raise TypeError("exact_event_join returned unexpected tuple")
    if cycle_labels is not None:
        from battery_workbench.datasets.joins import exact_cycle_join

        joined = exact_cycle_join(joined, cycle_labels)

    keep: list[str] = []
    for col in _IDENTITY_COLUMNS + _LABEL_COLUMNS:
        if col in joined.columns and col not in keep:
            keep.append(col)

    # Candidate ultrasound features: every BRW-013 sample-domain feature column.
    feature_cols = [
        c
        for c in joined.columns
        if c not in keep
        and c not in _EXCLUDED_FROM_ANALYSIS
        and c.startswith(("waveform_", "envelope_", "xcorr_"))
        and c != "xcorr_reference_measurement_event_id"
        and c != "xcorr_warning"
    ]
    keep.extend(feature_cols)

    # User-visible core features, if already materialized upstream. TOF
    # status/block-reason accompany canonical tof_us so nulls stay explainable.
    for col in (
        "tof_us",
        "tof_status",
        "tof_block_reason",
        "amplitude_a_u",
        "wave_speed_m_s",
    ):
        if col in joined.columns and col not in keep:
            keep.append(col)

    missing = [c for c in _LABEL_COLUMNS if c in event_labels.columns and c not in keep]
    if missing:
        raise ValueError(f"label columns missing after join: {missing}")

    return joined[keep].copy()

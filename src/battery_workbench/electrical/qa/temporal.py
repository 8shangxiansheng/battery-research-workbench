from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly
from battery_workbench.electrical.qa.schemas import ElectricalQAConfig, QAAnomaly


def analyze_temporal(
    records: pd.DataFrame, config: ElectricalQAConfig
) -> tuple[dict[str, Any], list[QAAnomaly]]:
    if "timestamp" not in records or records.empty:
        return {}, []
    timestamps = records["timestamp"]
    diffs = timestamps.diff().dt.total_seconds()
    positive = diffs[diffs > 0]
    grouped = records.loc[timestamps.duplicated(keep=False)].groupby("timestamp", sort=True)
    duplicate_groups = []
    for timestamp, group in grouped:
        pairs = []
        if {"cycle_index_raw", "step_index_raw"} <= set(group.columns):
            pairs = [
                [int(value) for value in pair]
                for pair in group[["cycle_index_raw", "step_index_raw"]]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            ]
        duplicate_groups.append(
            {
                "timestamp": pd.Timestamp(str(timestamp)).isoformat(),
                "row_count": len(group),
                "duplicate_count": len(group) - 1,
                "cycle_step_pairs": pairs,
                "likely_boundary_duplicate": len(pairs) > 1,
            }
        )
    duplicate_count = int(timestamps.duplicated().sum())
    largest_gap = float(positive.max()) if not positive.empty else 0.0
    issues: list[QAAnomaly] = []
    if duplicate_count:
        severity = "critical" if config.temporal.duplicate_timestamps_are_fatal else "warning"
        issues.append(
            anomaly(
                "DUPLICATE_TIMESTAMP",
                severity,
                "records",
                f"Found {duplicate_count} duplicate timestamps; rows were preserved",
                count=duplicate_count,
                metadata={"group_count": len(duplicate_groups)},
            )
        )
    if not timestamps.is_monotonic_increasing:
        issues.append(
            anomaly(
                "NON_MONOTONIC_TIMESTAMP",
                "warning",
                "records",
                "Record timestamps are not monotonic non-decreasing",
            )
        )
    if largest_gap > config.temporal.large_gap_warning_s:
        issues.append(
            anomaly(
                "LARGE_TIMESTAMP_GAP",
                "warning",
                "records",
                f"Largest timestamp gap is {largest_gap:g} s",
                metadata={"largest_gap_s": largest_gap},
            )
        )
    interval_counts = diffs.dropna().value_counts().sort_index()
    return {
        "timestamp_min": timestamps.min().isoformat(),
        "timestamp_max": timestamps.max().isoformat(),
        "duration_s": float((timestamps.max() - timestamps.min()).total_seconds()),
        "is_monotonic_non_decreasing": bool(timestamps.is_monotonic_increasing),
        "duplicate_timestamp_count": duplicate_count,
        "duplicate_timestamp_groups": duplicate_groups,
        "largest_gap_s": largest_gap,
        "median_interval_s": float(positive.median()) if not positive.empty else 0.0,
        "interval_distribution": {
            str(float(key)): int(value) for key, value in interval_counts.items()
        },
    }, issues

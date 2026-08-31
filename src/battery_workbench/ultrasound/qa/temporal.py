from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.ultrasound.qa.anomalies import anomaly
from battery_workbench.ultrasound.qa.schemas import QAAnomaly, UltrasoundQAConfig


def analyze_temporal(
    frames: pd.DataFrame, config: UltrasoundQAConfig
) -> tuple[dict[str, Any], list[QAAnomaly]]:
    issues: list[QAAnomaly] = []
    assets: list[dict[str, Any]] = []
    all_intervals: list[np.ndarray] = []
    for asset_id, group in frames.groupby("ultrasound_asset_id", sort=False):
        elapsed = group["elapsed_time_s"].to_numpy(dtype=float)
        intervals = np.diff(elapsed)
        positive = intervals[intervals > 0]
        median = float(np.median(positive)) if len(positive) else 0.0
        threshold = median * config.temporal.large_gap_factor
        duplicate_count = int(pd.Series(elapsed).duplicated().sum())
        nonpositive_count = int(np.sum(intervals <= 0))
        large_gap_count = int(np.sum(intervals > threshold)) if threshold else 0
        if nonpositive_count:
            issues.append(
                anomaly(
                    "NON_MONOTONIC_ELAPSED_TIME",
                    "warning",
                    "asset",
                    "elapsed_time_s contains duplicate or decreasing intervals",
                    asset_id=str(asset_id),
                    metrics={"nonpositive_interval_count": nonpositive_count},
                )
            )
        if large_gap_count:
            issues.append(
                anomaly(
                    "LARGE_FRAME_GAP",
                    "warning",
                    "asset",
                    "elapsed_time_s contains intervals above the configured gap factor",
                    asset_id=str(asset_id),
                    metrics={"count": large_gap_count, "threshold_s": threshold},
                )
            )
        if "file_start_time" in group and "absolute_timestamp" in group:
            start = pd.to_datetime(group["file_start_time"])
            absolute = pd.to_datetime(group["absolute_timestamp"])
            expected = start + pd.to_timedelta(group["elapsed_time_s"], unit="s")
            error_s = (absolute - expected).abs().dt.total_seconds()
            inconsistent = int((error_s > config.temporal.absolute_timestamp_tolerance_s).sum())
            if inconsistent:
                issues.append(
                    anomaly(
                        "ABSOLUTE_TIMESTAMP_MISMATCH",
                        "warning",
                        "asset",
                        "absolute_timestamp is not mechanically consistent with elapsed_time_s",
                        asset_id=str(asset_id),
                        metrics={
                            "count": inconsistent,
                            "tolerance_s": config.temporal.absolute_timestamp_tolerance_s,
                            "max_error_s": float(error_s.max()),
                        },
                    )
                )
        if len(intervals):
            all_intervals.append(intervals)
        assets.append(
            {
                "asset_id": str(asset_id),
                "elapsed_time_min_s": float(elapsed.min()),
                "elapsed_time_max_s": float(elapsed.max()),
                "duration_s": float(elapsed.max() - elapsed.min()),
                "is_strictly_increasing": nonpositive_count == 0,
                "duplicate_elapsed_count": duplicate_count,
                "nonpositive_interval_count": nonpositive_count,
                "median_interval_s": median,
                "min_interval_s": float(intervals.min()) if len(intervals) else 0.0,
                "max_interval_s": float(intervals.max()) if len(intervals) else 0.0,
                "large_gap_threshold_s": threshold,
                "large_gap_count": large_gap_count,
            }
        )
    elapsed_all = frames["elapsed_time_s"].to_numpy(dtype=float)
    combined = np.concatenate(all_intervals) if all_intervals else np.array([], dtype=float)
    positive_all = combined[combined > 0]
    result = {
        "elapsed_time_min_s": float(elapsed_all.min()) if len(elapsed_all) else None,
        "elapsed_time_max_s": float(elapsed_all.max()) if len(elapsed_all) else None,
        "median_interval_s": float(np.median(positive_all)) if len(positive_all) else 0.0,
        "min_interval_s": float(combined.min()) if len(combined) else 0.0,
        "max_interval_s": float(combined.max()) if len(combined) else 0.0,
        "assets": assets,
    }
    return result, issues

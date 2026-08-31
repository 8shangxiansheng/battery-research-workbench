from __future__ import annotations

from bisect import bisect_left
from datetime import datetime


def nearest_timestamp_index(
    target: datetime,
    ordered_timestamps: list[datetime],
) -> tuple[int, float]:
    """Return nearest timestamp index and absolute error in seconds."""
    if not ordered_timestamps:
        raise ValueError("ordered_timestamps must not be empty")

    pos = bisect_left(ordered_timestamps, target)
    candidates: list[int] = []
    if pos < len(ordered_timestamps):
        candidates.append(pos)
    if pos > 0:
        candidates.append(pos - 1)

    best = min(candidates, key=lambda idx: abs((ordered_timestamps[idx] - target).total_seconds()))
    error = abs((ordered_timestamps[best] - target).total_seconds())
    return best, error

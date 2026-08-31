from __future__ import annotations
from datetime import datetime


def is_near_boundary(
    timestamp: datetime,
    boundaries: list[datetime],
    tolerance_s: float = 1.0,
) -> bool:
    return any(abs((timestamp - boundary).total_seconds()) <= tolerance_s for boundary in boundaries)

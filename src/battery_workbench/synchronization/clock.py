from __future__ import annotations
from datetime import datetime, timedelta


def elapsed_to_absolute(file_start_time: datetime, elapsed_time_s: float) -> datetime:
    """Convert one ultrasound file-relative frame time to an absolute timestamp."""
    return file_start_time + timedelta(seconds=elapsed_time_s)


def apply_linear_clock_model(
    file_start_time: datetime,
    elapsed_time_s: float,
    *,
    offset_s: float = 0.0,
    rate: float = 1.0,
) -> datetime:
    """V1.1 clock model: absolute = start + offset + rate * elapsed."""
    corrected = offset_s + rate * elapsed_time_s
    return file_start_time + timedelta(seconds=corrected)

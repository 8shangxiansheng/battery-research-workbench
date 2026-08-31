from __future__ import annotations

from datetime import datetime, timedelta


def elapsed_to_absolute(file_start_time: datetime, elapsed_time_s: float) -> datetime:
    """Convert one ultrasound file-relative frame time to an absolute timestamp."""
    return file_start_time + timedelta(seconds=elapsed_time_s)


def construct_timestamp(
    anchor_datetime: datetime,
    elapsed_time_s: float,
    elapsed_time_s_at_anchor: float,
) -> datetime:
    """Construct a provisional absolute timestamp for one frame.

    V1 OFFSET_ONLY clock model:

        t_abs = anchor_datetime + (elapsed_time_s - elapsed_time_s_at_anchor)

    Deterministic, microsecond precision, no drift, no timezone inference.
    A naive ``anchor_datetime`` yields a naive result.
    """
    delta_s = elapsed_time_s - elapsed_time_s_at_anchor
    return anchor_datetime + timedelta(seconds=delta_s)


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

from __future__ import annotations

from datetime import datetime

from battery_workbench.synchronization.clock import construct_timestamp
from battery_workbench.synchronization.timestamp_schemas import ClockModel


def test_basic_arithmetic_t01() -> None:
    """T01: T0 + (elapsed - elapsed_at_anchor), microsecond exact."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    # first frame elapsed = 0.031217, elapsed_at_anchor = 0
    result = construct_timestamp(anchor, 0.031217, 0.0)
    assert result == datetime(2024, 1, 6, 9, 52, 31, 31217)
    assert result.microsecond == 31217


def test_non_zero_elapsed_at_anchor_t02() -> None:
    """T02: a non-zero elapsed_at_anchor shifts the origin."""
    anchor = datetime(2024, 1, 6, 12, 0, 10)
    # elapsed_at_anchor = 10: the anchor corresponds to elapsed=10, not elapsed=0.
    result = construct_timestamp(anchor, 15.0, 10.0)
    assert result == datetime(2024, 1, 6, 12, 0, 15)


def test_first_elapsed_not_anchor_t03() -> None:
    """T03: the first frame timestamp is not equal to the anchor itself."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    first = construct_timestamp(anchor, 0.031217, 0.0)
    assert first != anchor
    assert first == datetime(2024, 1, 6, 9, 52, 31, 31217)


def test_no_drift_t21() -> None:
    """T21: the V1 clock model is OFFSET_ONLY with scale=1.0 and no drift."""
    model = ClockModel(
        model_type="OFFSET_ONLY",
        anchor_id="U001-manifest",
        anchor_datetime=datetime(2024, 1, 6, 9, 52, 31),
        elapsed_time_s_at_anchor=0.0,
    )
    assert model.model_type == "OFFSET_ONLY"
    assert model.scale == 1.0
    assert model.offset_s == 0.0
    assert model.drift_enabled is False


def test_clock_model_defaults() -> None:
    model = ClockModel(
        anchor_id="U001-manifest",
        anchor_datetime=datetime(2024, 1, 6, 9, 52, 31),
    )
    assert model.scale == 1.0
    assert model.offset_s == 0.0
    assert model.drift_enabled is False


def test_fractional_elapsed_preserved() -> None:
    """Non-integer elapsed must not be rounded to whole seconds."""
    anchor = datetime(2024, 1, 6, 9, 52, 31)
    result = construct_timestamp(anchor, 10.031217, 0.0)
    assert result.microsecond == 31217
    assert result.second == 41

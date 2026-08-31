from __future__ import annotations

import pytest

from battery_workbench.analysis.schemas import ConditionSliceSpec
from battery_workbench.analysis.validation import (
    compute_slice_status,
    validate_spec,
)


def test_invalid_voltage_range_rejected() -> None:
    with pytest.raises(ValueError):
        validate_spec(ConditionSliceSpec(voltage_v_min=5.0, voltage_v_max=3.0))


def test_invalid_current_range_rejected() -> None:
    with pytest.raises(ValueError):
        validate_spec(ConditionSliceSpec(current_a_min=1.0, current_a_max=-1.0))


def test_valid_spec_passes() -> None:
    validate_spec(ConditionSliceSpec(voltage_v_min=3.0, voltage_v_max=4.5))
    validate_spec(ConditionSliceSpec(cycle_indices=[1, 2]))


def test_inclusive_bounds_allowed_equal() -> None:
    # min == max is a valid degenerate range (single value, inclusive).
    validate_spec(ConditionSliceSpec(voltage_v_min=3.5, voltage_v_max=3.5))


def test_status_compute() -> None:
    assert compute_slice_status(rows_before=10, rows_after=10, warning=False) == "READY"
    assert (
        compute_slice_status(rows_before=10, rows_after=10, warning=True) == "READY_WITH_WARNINGS"
    )
    assert compute_slice_status(rows_before=10, rows_after=0, warning=True) == "EMPTY"

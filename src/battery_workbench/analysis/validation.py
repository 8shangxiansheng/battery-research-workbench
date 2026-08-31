"""BRW-012 slice-engine validation.

Spec validation rejects inverted numeric ranges (min > max) rather than
silently swapping them. Status computation is deterministic from row counts and
warnings. Unknown step values are a warning, never a guessed mapping.
"""

from __future__ import annotations

from battery_workbench.analysis.schemas import ConditionSliceSpec, SliceStatus

_RANGE_PAIRS = [
    ("voltage_v", "voltage_v_min", "voltage_v_max"),
    ("current_a", "current_a_min", "current_a_max"),
    ("capacity_ah", "capacity_ah_min", "capacity_ah_max"),
    ("temperature_c", "temperature_c_min", "temperature_c_max"),
    ("soc_dod_percent", "soc_dod_percent_min", "soc_dod_percent_max"),
    ("elapsed_time_s", "elapsed_time_s_min", "elapsed_time_s_max"),
]


class ConditionSliceValidationError(ValueError):
    """Raised when a ConditionSliceSpec is structurally invalid."""


def validate_spec(spec: ConditionSliceSpec) -> None:
    """Validate a spec; raise ``ConditionSliceValidationError`` on an inverted range."""
    for name, min_attr, max_attr in _RANGE_PAIRS:
        min_v = getattr(spec, min_attr)
        max_v = getattr(spec, max_attr)
        if min_v is not None and max_v is not None and min_v > max_v:
            raise ConditionSliceValidationError(
                f"inverted {name} range: {min_attr}={min_v} > {max_attr}={max_v}"
            )


def compute_slice_status(*, rows_before: int, rows_after: int, warning: bool) -> SliceStatus:
    """Deterministic slice status from row counts / warnings."""
    if rows_before == 0 or rows_after == 0:
        return "EMPTY"
    if warning:
        return "READY_WITH_WARNINGS"
    return "READY"


def validate_step_types(step_types: list[str], available: set[str]) -> list[str]:
    """Return warnings for any unknown step_type (never guessed)."""
    return [f"unknown step_type '{s}' matches 0 rows" for s in step_types if s not in available]

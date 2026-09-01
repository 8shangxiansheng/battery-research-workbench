"""Unit canonicalization for BRW-015.

Canonical units: frequency Hz, time s, capacity Ah, length m, temperature degC,
gain dB, sample index sample. Equivalent expressions normalize to the identical
scientific value BEFORE any hashing, so 100 MHz == 1e8 Hz produces the same
parameter identity.
"""

from __future__ import annotations

# unit -> (canonical_unit, factor_to_canonical, dimension)
_UNITS: dict[str, tuple[str, float, str]] = {
    # frequency -> Hz
    "Hz": ("Hz", 1.0, "frequency"),
    "kHz": ("Hz", 1e3, "frequency"),
    "MHz": ("Hz", 1e6, "frequency"),
    "GHz": ("Hz", 1e9, "frequency"),
    # time -> s
    "s": ("s", 1.0, "time"),
    "ms": ("s", 1e-3, "time"),
    "us": ("s", 1e-6, "time"),
    "ns": ("s", 1e-9, "time"),
    # capacity -> Ah
    "Ah": ("Ah", 1.0, "capacity"),
    "mAh": ("Ah", 1e-3, "capacity"),
    # length -> m
    "m": ("m", 1.0, "length"),
    "mm": ("m", 1e-3, "length"),
    "cm": ("m", 1e-2, "length"),
    "um": ("m", 1e-6, "length"),
    # passthrough dimensions
    "degC": ("degC", 1.0, "temperature"),
    "dB": ("dB", 1.0, "gain"),
    "sample": ("sample", 1.0, "sample_index"),
    "samples": ("sample", 1.0, "sample_index"),
    "text": ("text", 1.0, "text"),
}

_DIMENSION_ALIASES = {"sample_index": "sample_index", "index": "sample_index"}


class UnitError(ValueError):
    """Raised for unknown units, missing units on critical values, or
    dimension mismatches."""


def canonical_unit_for(unit: str) -> str:
    if unit not in _UNITS:
        raise UnitError(f"unknown unit: {unit!r}")
    return _UNITS[unit][0]


def dimension_of(unit: str) -> str:
    if unit not in _UNITS:
        raise UnitError(f"unknown unit: {unit!r}")
    return _UNITS[unit][2]


def canonicalize(
    value: float | None,
    unit: str | None,
    *,
    dimension: str | None = None,
) -> float | None:
    """Normalize ``value`` in ``unit`` to the canonical unit of its dimension.

    ``dimension`` (when given) must match the unit's dimension — a frequency
    value stored in seconds is rejected instead of silently converted.
    """
    if value is None:
        return None
    if unit is None:
        raise UnitError("missing unit for a parameter value")
    if unit not in _UNITS:
        raise UnitError(f"unknown unit: {unit!r}")
    _canonical_unit, factor, unit_dimension = _UNITS[unit]
    effective_dimension = (
        _DIMENSION_ALIASES.get(dimension, dimension) if dimension else unit_dimension
    )
    if dimension is not None and effective_dimension != unit_dimension:
        raise UnitError(
            f"dimension mismatch: unit {unit!r} is {unit_dimension}, expected {effective_dimension}"
        )
    return float(value) * factor

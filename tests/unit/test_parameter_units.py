from __future__ import annotations

import pytest

from battery_workbench.parameters.units import (
    UnitError,
    canonical_unit_for,
    canonicalize,
)


def test_mhz_to_hz_t09() -> None:
    assert canonicalize(100.0, "MHz") == pytest.approx(1e8)
    assert canonicalize(100.0, "MHz") == pytest.approx(1e8, rel=1e-12)


def test_khz_to_hz_t10() -> None:
    assert canonicalize(25.0, "kHz") == pytest.approx(25_000.0)


def test_us_to_s_t11() -> None:
    assert canonicalize(1000.0, "us") == pytest.approx(0.001)


def test_mm_to_m_t12() -> None:
    assert canonicalize(10.0, "mm") == pytest.approx(0.01)


def test_mah_to_ah_t13() -> None:
    assert canonicalize(1000.0, "mAh") == pytest.approx(1.0)


def test_invalid_dimension_t14() -> None:
    """T14: a frequency value cannot be given a time unit."""
    with pytest.raises(UnitError):
        canonicalize(100.0, "s", dimension="frequency")


def test_missing_critical_unit_t15() -> None:
    """T15: a scientific-critical parameter cannot be stored without a unit."""
    with pytest.raises(UnitError):
        canonicalize(1e8, None, dimension="frequency")


def test_canonical_roundtrip_t16() -> None:
    """T16: canonicalizing an already-canonical value is a no-op."""
    assert canonicalize(1e8, "Hz") == pytest.approx(1e8)
    assert canonicalize(0.01, "m") == pytest.approx(0.01)
    assert canonicalize(1.0, "Ah") == pytest.approx(1.0)
    assert canonical_unit_for("Hz") == "Hz"


def test_degc_and_db_passthrough() -> None:
    assert canonicalize(25.0, "degC") == pytest.approx(25.0)
    assert canonicalize(10.0, "dB") == pytest.approx(10.0)


def test_unit_equivalence_100mhz_is_1e8hz() -> None:
    """100 MHz and 1e8 Hz normalize to the identical scientific value."""
    assert canonicalize(100.0, "MHz") == canonicalize(1e8, "Hz")

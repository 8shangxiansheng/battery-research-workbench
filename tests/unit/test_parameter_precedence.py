from __future__ import annotations

import pytest

from battery_workbench.parameters.catalog import get_spec
from battery_workbench.parameters.resolution import resolve_parameter
from battery_workbench.parameters.schemas import ParameterRecord


def _rec(
    name: str,
    value: float | None,
    source: str,
    verification: str,
    scope: str,
    *,
    scope_key: str = "CELL_001/EXP_001",
    record_id: str | None = None,
    unit: str | None = None,
) -> ParameterRecord:
    return ParameterRecord(
        parameter_record_id=record_id or f"{name}:{source}:{scope}:{value}",
        canonical_name=name,
        value=value,
        unit=unit or get_spec(name).unit,
        source_type=source,
        verification_status=verification,
        scope_type=scope,
        scope_key=scope_key,
    )


_NAME = "ultrasound.sampling_rate_hz"


def test_asset_beats_experiment_t17() -> None:
    """T17: DATA_ASSET scope outranks EXPERIMENT at equal verification."""
    result = resolve_parameter(
        [
            _rec(_NAME, 1e6, "USER_SUPPLIED", "UNVERIFIED", "EXPERIMENT", record_id="exp"),
            _rec(
                _NAME,
                2e6,
                "USER_SUPPLIED",
                "UNVERIFIED",
                "DATA_ASSET",
                scope_key="CELL_001/EXP_001/U001",
                record_id="asset",
            ),
        ],
        get_spec(_NAME),
    )
    assert result.value == pytest.approx(2e6)
    assert result.selected_parameter_record_id == "asset"


def test_experiment_beats_battery_t18() -> None:
    """T18: EXPERIMENT outranks BATTERY at equal verification."""
    result = resolve_parameter(
        [
            _rec(_NAME, 1e6, "USER_SUPPLIED", "UNVERIFIED", "BATTERY", scope_key="CELL_001"),
            _rec(_NAME, 3e6, "USER_SUPPLIED", "UNVERIFIED", "EXPERIMENT"),
        ],
        get_spec(_NAME),
    )
    assert result.value == pytest.approx(3e6)


def test_verified_beats_unverified_t19() -> None:
    """T19: verification is the primary key — a verified battery-level value
    outranks an unverified asset-level value."""
    result = resolve_parameter(
        [
            _rec(
                _NAME,
                1e6,
                "USER_SUPPLIED",
                "UNVERIFIED",
                "DATA_ASSET",
                scope_key="CELL_001/EXP_001/U001",
            ),
            _rec(_NAME, 2e6, "CALIBRATION_RECORD", "VERIFIED", "BATTERY", scope_key="CELL_001"),
        ],
        get_spec(_NAME),
    )
    assert result.value == pytest.approx(2e6)


def test_deterministic_source_priority_t20() -> None:
    """T20: equal verification + equal scope -> deterministic source ordering."""
    result = resolve_parameter(
        [
            _rec(_NAME, 1e6, "FILE_REPORTED", "VERIFIED", "EXPERIMENT"),
            _rec(_NAME, 2e6, "CALIBRATION_RECORD", "VERIFIED", "EXPERIMENT"),
        ],
        get_spec(_NAME),
    )
    assert result.value == pytest.approx(2e6)  # calibration outranks file report


def test_same_priority_same_value_t21() -> None:
    """T21: duplicate records agreeing on the value resolve normally."""
    result = resolve_parameter(
        [
            _rec(_NAME, 1e8, "FILE_REPORTED", "VERIFIED", "EXPERIMENT"),
            _rec(_NAME, 1e8, "MANIFEST_REPORTED", "VERIFIED", "EXPERIMENT"),
        ],
        get_spec(_NAME),
    )
    assert result.status == "RESOLVED"
    assert result.value == pytest.approx(1e8)


def test_same_priority_conflict_t22() -> None:
    """T22: fully tied records (same verification/scope/source) disagreeing on
    the value -> CONFLICT block; no silent selection."""
    result = resolve_parameter(
        [
            _rec(_NAME, 1e8, "FILE_REPORTED", "VERIFIED", "EXPERIMENT", record_id="a"),
            _rec(_NAME, 2e8, "FILE_REPORTED", "VERIFIED", "EXPERIMENT", record_id="b"),
        ],
        get_spec(_NAME),
    )
    assert result.status == "CONFLICT"
    assert result.value is None


def test_unrelated_scope_ignored_t23() -> None:
    """T23: records targeting other batteries/experiments do not participate."""
    result = resolve_parameter(
        [
            _rec(
                _NAME, 5e6, "USER_SUPPLIED", "VERIFIED", "EXPERIMENT", scope_key="CELL_999/EXP_001"
            ),
            _rec(
                _NAME,
                1e8,
                "USER_SUPPLIED",
                "UNVERIFIED",
                "EXPERIMENT",
                scope_key="CELL_001/EXP_001",
            ),
        ],
        get_spec(_NAME),
        target_scope_key="CELL_001/EXP_001",
    )
    assert result.value == pytest.approx(1e8)


def test_shadowed_records_retained_t24() -> None:
    """T24: losing records are preserved as shadowed provenance."""
    winner = _rec(_NAME, 2e6, "CALIBRATION_RECORD", "VERIFIED", "EXPERIMENT", record_id="win")
    loser = _rec(
        _NAME,
        1e6,
        "USER_SUPPLIED",
        "UNVERIFIED",
        "DATA_ASSET",
        scope_key="CELL_001/EXP_001/U001",
        record_id="lose",
    )
    result = resolve_parameter([loser, winner], get_spec(_NAME))
    assert result.selected_parameter_record_id == "win"
    assert "lose" in result.shadowed_records


def test_empty_records_unknown() -> None:
    result = resolve_parameter([], get_spec(_NAME))
    assert result.status == "UNKNOWN"
    assert result.value is None


def test_unit_equivalent_records_agree() -> None:
    """100 MHz and 1e8 Hz records are the same scientific value — no conflict."""
    a = _rec(_NAME, 1e8, "FILE_REPORTED", "VERIFIED", "EXPERIMENT", unit="Hz")
    b = _rec(_NAME, 100.0, "MANIFEST_REPORTED", "VERIFIED", "EXPERIMENT", unit="MHz")
    result = resolve_parameter([a, b], get_spec(_NAME))
    assert result.status == "RESOLVED"
    assert result.value == pytest.approx(1e8)

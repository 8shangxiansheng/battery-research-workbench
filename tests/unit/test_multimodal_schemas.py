from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from battery_workbench.domain.measurement import MeasurementEvent as LegacyMeasurementEvent
from battery_workbench.multimodal.schemas import CanonicalMeasurementEvent

# ELECTRICAL_ENRICHMENT_WHITELIST — the BRW-011 allowed enrichment columns.
WHITELIST = [
    "cycle_index_raw",
    "step_index_raw",
    "step_type",
    "voltage_v",
    "current_a",
    "capacity_ah",
    "charge_capacity_ah",
    "discharge_capacity_ah",
    "energy_wh",
    "power_w",
    "temperature_c",
    "soc_dod_percent",
    "contact_resistance_mohm",
    "dq_dv_raw",
]


def _event(**overrides) -> CanonicalMeasurementEvent:
    base = {
        "measurement_event_id": "ME::CELL_001::EXP_001::U001::3998",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "ultrasound_asset_id": "U001",
        "frame_index_raw": 3998,
        "event_order_index": 3998,
        "source_file": "export.txt",
        "source_line_index": 3999,
        "waveform_group": "U001/waveform",
        "waveform_row_index": 3998,
        "provisional_absolute_timestamp": datetime(2024, 1, 6, 20, 58, 51, 30000),
        "elapsed_time_s": 39980.03,
        "timezone_known": False,
        "timezone_name": None,
        "match_status": "MATCHED_UNIQUE",
        "sync_error_s": 0.03,
        "within_tolerance": True,
        "candidate_timestamp_count": 1,
        "candidate_record_count": 1,
        "sync_ambiguous": False,
        "ambiguity_type": "NONE",
        "boundary_flag": False,
        "matching_performed": True,
        "validated_sync": False,
        "sync_semantics": "MATCHED_USING_PROVISIONAL_TIMEBASE",
        "anchor_id": "U001-manifest",
        "anchor_status": "PROVISIONAL",
        "event_quality_status": "READY",
        "analysis_eligible": True,
        "event_quality_reason": "",
    }
    base.update(overrides)
    return CanonicalMeasurementEvent(**base)


def test_backward_compat_old_domain_model_unchanged() -> None:
    """Backward-compat guard: the re-exported MeasurementEvent is still the OLD class."""
    from battery_workbench.domain.models import MeasurementEvent as Reexported

    # The re-exported symbol is the legacy domain model, not the new canonical one.
    assert Reexported is LegacyMeasurementEvent
    # Legacy model keeps its original field names (event_id / soc_percent), NOT the
    # BRW-011 canonical names.
    assert "event_id" in LegacyMeasurementEvent.model_fields
    assert "soc_percent" in LegacyMeasurementEvent.model_fields
    assert "soc_dod_percent" not in LegacyMeasurementEvent.model_fields
    assert "measurement_event_id" not in LegacyMeasurementEvent.model_fields


def test_canonical_model_is_distinct_class() -> None:
    """T13: CanonicalMeasurementEvent is a distinct class, never the legacy one."""
    assert CanonicalMeasurementEvent is not LegacyMeasurementEvent


def test_canonical_event_has_whitelist_fields() -> None:
    """The canonical event exposes the electrical-enrichment whitelist columns."""
    fields = set(CanonicalMeasurementEvent.model_fields)
    for name in WHITELIST:
        assert name in fields


def test_canonical_event_locks_soc_dod_semantics() -> None:
    """soc_dod_percent is the canonical field; soc_percent is NOT introduced."""
    fields = set(CanonicalMeasurementEvent.model_fields)
    assert "soc_dod_percent" in fields
    assert "soc_percent" not in fields


def test_canonical_event_no_waveform_samples() -> None:
    """The event schema must not carry waveform samples / sample arrays."""
    for forbidden in ("waveform", "samples", "raw_waveform", "sample_000"):
        assert forbidden not in CanonicalMeasurementEvent.model_fields


def test_canonical_event_round_trip_naive_timezone() -> None:
    event = _event()
    assert event.provisional_absolute_timestamp.tzinfo is None
    assert event.timezone_known is False
    assert event.validated_sync is False
    assert event.anchor_status == "PROVISIONAL"


def test_invalid_quality_status_rejected() -> None:
    with pytest.raises(ValidationError):
        _event(event_quality_status="VALIDATED")

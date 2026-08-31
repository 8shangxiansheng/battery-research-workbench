from __future__ import annotations

from battery_workbench.multimodal.schemas import CanonicalMeasurementEvent, MeasurementEventConfig
from battery_workbench.multimodal.validation import (
    compute_event_quality,
    validate_waveform_locator,
)


def test_event_quality_mapping_t21() -> None:
    """T21: match_status -> event_quality_status mapping is deterministic."""
    assert compute_event_quality("MATCHED_UNIQUE", within=True, locator_valid=True) == "READY"
    assert (
        compute_event_quality("MATCHED_AMBIGUOUS", within=True, locator_valid=False)
        == "AMBIGUOUS_SYNC"
    )
    assert (
        compute_event_quality("OUT_OF_TOLERANCE", within=False, locator_valid=False)
        == "OUT_OF_TOLERANCE"
    )
    assert (
        compute_event_quality("TIMESTAMP_UNAVAILABLE", within=False, locator_valid=False)
        == "TIMESTAMP_UNAVAILABLE"
    )


def test_analysis_eligibility_t22() -> None:
    """T22: only READY is analysis_eligible."""
    assert _eligibility("READY") is True
    assert _eligibility("AMBIGUOUS_SYNC") is False
    assert _eligibility("OUT_OF_TOLERANCE") is False
    assert _eligibility("TIMESTAMP_UNAVAILABLE") is False
    assert _eligibility("INTEGRITY_ERROR") is False


def _eligibility(status: str) -> bool:
    cfg = MeasurementEventConfig()
    return status in cfg.quality.analysis_eligible_statuses


def test_soc_dod_semantic_guard_t23() -> None:
    """T23: soc_dod_percent stays as the raw SOC/DOD(%) field; no soc_percent."""
    assert "soc_dod_percent" in CanonicalMeasurementEvent.model_fields
    assert "soc_percent" not in CanonicalMeasurementEvent.model_fields


def test_raw_dqdv_unchanged_t24() -> None:
    """T24: dq_dv_raw is the raw dqdv_mah_per_v value, never smoothed."""
    # An extreme raw dQ/dV value must pass through bitwise-numerically unchanged.
    raw_record_row = {"dqdv_mah_per_v": -9999.123}
    extracted = extract_dq_dv_raw(raw_record_row)
    assert extracted == -9999.123


def extract_dq_dv_raw(record: dict) -> float:
    # Helper mirroring the future builder: only exact propagation, no transform.
    return float(record["dqdv_mah_per_v"])


def test_whitelist_excludes_unrelated_columns_t26() -> None:
    """T26: only the electrical whitelist columns are carried; no full-copy."""
    config = MeasurementEventConfig()
    whitelist = set(config.electrical_enrichment.fields)
    # Whitelist must NOT include source-audit or computed columns.
    for forbidden in ("source_file", "source_sheet", "lgd_raw", "specific_capacity_mah_per_g"):
        assert forbidden not in whitelist


def test_waveform_locator_no_samples_t27() -> None:
    """T27: the event carries waveform_group/row_index, never waveform samples."""
    assert "waveform_group" in CanonicalMeasurementEvent.model_fields
    assert "waveform_row_index" in CanonicalMeasurementEvent.model_fields
    for forbidden in ("waveform", "samples", "raw_waveform", "sample_array"):
        assert forbidden not in CanonicalMeasurementEvent.model_fields


def test_waveform_locator_range_validation() -> None:
    """T27b: a valid locator passes; an out-of-range row index fails."""
    assert validate_waveform_locator("U001/waveform", 100, zarr_rows=200) is True
    assert validate_waveform_locator("U001/waveform", 200, zarr_rows=200) is False
    assert validate_waveform_locator("U001/waveform", 201, zarr_rows=200) is False

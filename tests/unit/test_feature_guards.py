from __future__ import annotations

from pathlib import Path

from battery_workbench.features.validation import (
    physical_features_available,
    validate_locator,
    validate_no_physical_features,
)


def test_sampling_rate_null_t31() -> None:
    # V1: sampling rate is null -> physical features unavailable.
    assert physical_features_available(None) == (False, False)


def test_no_tof_column_t32() -> None:
    validate_no_physical_features()
    # Ensure a no-op guard doesn't introduce physical feature names.
    from battery_workbench.features.definitions import FEATURE_DEFINITIONS

    names = [d["name"] for d in FEATURE_DEFINITIONS]
    for forbidden in ("tof_us", "time_delay_us", "frequency_hz", "frequency_mhz", "fft_peak_hz"):
        assert forbidden not in names


def test_locator_validation_t25() -> None:
    assert validate_locator("U001/waveform", 5, zarr_rows=10) is True
    assert validate_locator("U001/waveform", -1, zarr_rows=10) is False
    assert validate_locator("U001/waveform", 10, zarr_rows=10) is False
    assert validate_locator("", 5, zarr_rows=10) is False


def test_feature_definitions_schema_t37(tmp_path: Path) -> None:
    from battery_workbench.features.definitions import FEATURE_DEFINITIONS

    assert len(FEATURE_DEFINITIONS) >= 12
    for d in FEATURE_DEFINITIONS:
        for key in (
            "name",
            "version",
            "description",
            "formula",
            "unit",
            "dtype",
            "requires_sampling_rate",
            "preprocessing",
            "null_behavior",
        ):
            assert key in d
        assert d["requires_sampling_rate"] is False  # V1 sample-domain only

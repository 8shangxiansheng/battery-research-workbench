from __future__ import annotations

from battery_workbench.labels.tof_readiness import (
    evaluate_tof_readiness,
    frame_cadence_is_not_sampling_rate,
    sample_count_is_not_sampling_rate,
)


def test_missing_fs_blocked_t37() -> None:
    """T37: null sampling rate -> BLOCKED_MISSING_SAMPLING_RATE."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=None,
        trigger_zero_available=False,
        system_delay_calibration_available=False,
    )
    assert r.absolute_tof_status == "BLOCKED_MISSING_SAMPLING_RATE"
    assert "missing_sampling_rate" in r.blocking_reasons
    assert r.physical_time_features_available is False


def test_fs_present_no_trigger_blocked_t38() -> None:
    """T38: fs present but no trigger zero -> BLOCKED_MISSING_TIME_ZERO."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=25e6,
        trigger_zero_available=False,
        system_delay_calibration_available=False,
    )
    assert r.absolute_tof_status == "BLOCKED_MISSING_TIME_ZERO"
    assert "missing_time_zero" in r.blocking_reasons


def test_calibration_state_t39() -> None:
    """T39: fs+trigger present but no calibration -> BLOCKED_MISSING_CALIBRATION."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=25e6,
        trigger_zero_available=True,
        system_delay_calibration_available=False,
    )
    assert r.absolute_tof_status == "BLOCKED_MISSING_CALIBRATION"


def test_all_metadata_ready_t40() -> None:
    """T40: full metadata -> READY_FOR_ABSOLUTE_TOF_DEVELOPMENT."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=25e6,
        trigger_zero_available=True,
        system_delay_calibration_available=True,
    )
    assert r.absolute_tof_status == "READY_FOR_ABSOLUTE_TOF_DEVELOPMENT"
    assert r.blocking_reasons == []


def test_no_tof_us_output_t41() -> None:
    """T41: the readiness struct never carries a tof_us value."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=25e6,
        trigger_zero_available=True,
        system_delay_calibration_available=True,
    )
    assert not hasattr(r, "tof_us")
    assert not hasattr(r, "tof_raw_s")


def test_frame_cadence_not_fs_t42() -> None:
    """T42: the ~10s frame acquisition interval is never the sampling rate."""
    assert frame_cadence_is_not_sampling_rate(10.0) is True
    assert frame_cadence_is_not_sampling_rate(25e6) is False


def test_sample_count_not_fs_t43() -> None:
    """T43: 1250 samples can never be inverted into a sampling rate."""
    assert sample_count_is_not_sampling_rate(1250) is True


def test_arrival_detector_not_selected_t44() -> None:
    r = evaluate_tof_readiness(
        sampling_rate_hz=None,
        trigger_zero_available=False,
        system_delay_calibration_available=False,
    )
    assert r.arrival_detector_status == "NOT_SELECTED"


def test_xcorr_shift_is_not_absolute_tof_t45() -> None:
    """T45: relative xcorr shift (samples) is NOT an absolute TOF claim."""
    r = evaluate_tof_readiness(
        sampling_rate_hz=None,
        trigger_zero_available=False,
        system_delay_calibration_available=False,
    )
    assert r.absolute_tof_status.startswith("BLOCKED")
    # Even in the READY state, sample shifts are only relative features.
    assert r.xcorr_shift_is_absolute_tof is False

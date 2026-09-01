"""TOF readiness assessment (BRW-014) — a reservation, not a TOF feature.

Absolute TOF stays BLOCKED until the waveform sampling rate, a trigger/time
zero, and a system-delay calibration all exist. The ~10s frame acquisition
interval is never a sampling rate, and the 1250-sample record length can never
be inverted into one.
"""

from __future__ import annotations

from battery_workbench.labels.schemas import TofReadiness

# The known frame acquisition interval in the current baseline (seconds).
FRAME_ACQUISITION_INTERVAL_S = 10.0


def frame_cadence_is_not_sampling_rate(value_hz: float) -> bool:
    """A sub-kHz "sampling rate" cannot be an ultrasound waveform rate.

    The ~10s frame acquisition interval expressed as a frequency (~0.1 Hz) —
    or any value in that range — is a frame cadence, never the waveform
    sampling rate. Real ultrasonic sampling rates are MHz-scale.
    """
    return value_hz < 1000.0


def sample_count_is_not_sampling_rate(sample_count: int) -> bool:
    """A sample count is not a rate; it can never be inverted into one."""
    return sample_count > 0


def evaluate_tof_readiness(
    *,
    sampling_rate_hz: float | None,
    trigger_zero_available: bool,
    system_delay_calibration_available: bool,
    waveform_sample_count: int | None = None,
    frame_acquisition_interval_s: float | None = FRAME_ACQUISITION_INTERVAL_S,
) -> TofReadiness:
    """Assess absolute-TOF readiness with explicit blocking reasons."""
    reasons: list[str] = []
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        reasons.append("missing_sampling_rate")
    elif not trigger_zero_available:
        reasons.append("missing_time_zero")
    elif not system_delay_calibration_available:
        reasons.append("missing_calibration")

    if not reasons:
        status = "READY_FOR_ABSOLUTE_TOF_DEVELOPMENT"
    elif "missing_sampling_rate" in reasons:
        status = "BLOCKED_MISSING_SAMPLING_RATE"
    elif "missing_time_zero" in reasons:
        status = "BLOCKED_MISSING_TIME_ZERO"
    else:
        status = "BLOCKED_MISSING_CALIBRATION"

    return TofReadiness(
        absolute_tof_status=status,
        sampling_rate_hz=sampling_rate_hz,
        sampling_rate_source=None if sampling_rate_hz is None else "provided",
        trigger_zero_available=trigger_zero_available,
        system_delay_calibration_available=system_delay_calibration_available,
        waveform_sample_count=waveform_sample_count,
        arrival_detector_status="NOT_SELECTED",
        blocking_reasons=reasons,
        frame_acquisition_interval_s=frame_acquisition_interval_s,
        frame_acquisition_interval_is_waveform_period=False,
        xcorr_shift_is_absolute_tof=False,
        physical_time_features_available=status == "READY_FOR_ABSOLUTE_TOF_DEVELOPMENT",
    )

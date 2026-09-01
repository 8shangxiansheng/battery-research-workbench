"""BRW-017 V2 physical feature engine — canonical TOF semantics (final).

Canonical definition (FINAL, supersedes the earlier xcorr-based reading):

    tof_us =
        (arrival_sample_index - trigger_sample_index)
        / sampling_rate_hz
        * 1e6

``tof_us`` is an **ABSOLUTE ARRIVAL-BASED FLIGHT TIME ESTIMATE**.

It is NOT the xcorr relative shift: ``xcorr_shift_samples`` only measures a
relative propagation-delay shift between a measurement and its per-asset
reference. That quantity keeps existing under its own name
(``compute_relative_delay_us``, AUXILIARY_CANDIDATE_FEATURE
``xcorr_shift_samples``) and must never be presented as, or converted into,
canonical ``tof_us``.

Unlock conditions for tof_us (ALL required, else null):
  1. sampling_rate_hz available
  2. trigger/time-zero available
  3. validated arrival detector available

The arrival detector is an algorithm capability — never a user-supplied
parameter.
"""

from __future__ import annotations

TOF_STATUS_READY = "READY"
TOF_STATUS_BLOCKED = "BLOCKED"

TOF_BLOCK_DETECTOR = "ARRIVAL_DETECTOR_NOT_VALIDATED"
TOF_BLOCK_FS = "MISSING_SAMPLING_RATE"
TOF_BLOCK_TRIGGER = "MISSING_TRIGGER"
TOF_BLOCK_ARRIVAL = "MISSING_ARRIVAL_DETECTION"
TOF_BLOCK_NONPHYSICAL = "NONPHYSICAL_FLIGHT_TIME"


def compute_tof_us(
    *,
    sampling_rate_hz: float | None = None,
    trigger_sample_index: int | None = None,
    arrival_sample_index: int | None = None,
    arrival_detector_validated: bool = False,
    xcorr_shift_samples: int | None = None,
) -> float | None:
    """Absolute arrival-based flight time estimate in microseconds.

    ``xcorr_shift_samples`` is accepted but deliberately **ignored**: no
    combination of xcorr shift + fs may populate canonical ``tof_us``.
    """
    if not arrival_detector_validated:
        return None
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        return None
    if trigger_sample_index is None or arrival_sample_index is None:
        return None
    tof_us = (arrival_sample_index - trigger_sample_index) / sampling_rate_hz * 1e6
    if tof_us <= 0:
        # Negative or zero flight time is unphysical for an absolute estimate.
        return None
    return tof_us


def tof_block_reason(
    *,
    sampling_rate_hz: float | None = None,
    trigger_sample_index: int | None = None,
    arrival_sample_index: int | None = None,
    arrival_detector_validated: bool = False,
    xcorr_shift_samples: int | None = None,
) -> str:
    """Primary machine-readable reason ``tof_us`` is null; '' when READY."""
    if not arrival_detector_validated:
        return TOF_BLOCK_DETECTOR
    if sampling_rate_hz is None or sampling_rate_hz <= 0:
        return TOF_BLOCK_FS
    if trigger_sample_index is None:
        return TOF_BLOCK_TRIGGER
    if arrival_sample_index is None:
        return TOF_BLOCK_ARRIVAL
    if (arrival_sample_index - trigger_sample_index) / sampling_rate_hz * 1e6 <= 0:
        return TOF_BLOCK_NONPHYSICAL
    return ""


def tof_status(
    *,
    sampling_rate_hz: float | None = None,
    trigger_sample_index: int | None = None,
    arrival_sample_index: int | None = None,
    arrival_detector_validated: bool = False,
    xcorr_shift_samples: int | None = None,
) -> str:
    """READY when tof_us is computable, BLOCKED otherwise."""
    ready = (
        tof_block_reason(
            sampling_rate_hz=sampling_rate_hz,
            trigger_sample_index=trigger_sample_index,
            arrival_sample_index=arrival_sample_index,
            arrival_detector_validated=arrival_detector_validated,
            xcorr_shift_samples=xcorr_shift_samples,
        )
        == ""
    )
    return TOF_STATUS_READY if ready else TOF_STATUS_BLOCKED


def compute_relative_delay_us(
    *,
    xcorr_shift_samples: int | None,
    sampling_rate_hz: float | None,
) -> float | None:
    """Analysis-layer relative propagation-delay shift from the xcorr lag.

    This is NOT canonical ``tof_us`` and must never be surfaced as one.
    """
    if xcorr_shift_samples is None or sampling_rate_hz is None or sampling_rate_hz <= 0:
        return None
    return xcorr_shift_samples / sampling_rate_hz * 1e6


def absolute_tof_available(
    *,
    has_detector: bool,
    trigger: bool = False,
    fs: float | None = None,
) -> bool:
    """Absolute TOF requires validated detector + trigger + fs."""
    return has_detector and trigger and fs is not None and fs > 0


def compute_wave_speed(
    *,
    tof_s: float | None,
    path_length_m: float | None,
    cell_thickness_m: float | None = None,
) -> float | None:
    """wave_speed_m_s = path_length_m / tof_s — only from a VALID tof_us.

    ``tof_s`` must be a valid absolute flight time (positive, arrival-based).
    Cell thickness is never auto-substituted for the acoustic path length.
    """
    if tof_s is None or tof_s <= 0 or path_length_m is None or path_length_m <= 0:
        return None
    return path_length_m / tof_s


def frame_cadence_cannot_resolve_fs(cadence_s: float) -> bool:
    return cadence_s >= 1.0


def sample_count_cannot_resolve_fs(sample_count: int) -> bool:
    return sample_count > 0

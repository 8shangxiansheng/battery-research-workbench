"""TOF activation chain: effective parameters + arrivals + validated detector.

``build_tof_column`` is the single wiring point of the real TOF chain:
  参数录入 (BRW-015 effective parameters, user_overrides)
    + validated arrival detector (synthetic suite passed)
    → canonical tof_us column + tof_status + tof_block_reason.
"""

from __future__ import annotations

from typing import Any

from battery_workbench.features_physical.engine import (
    TOF_BLOCK_DETECTOR,
    TOF_BLOCK_FS,
    TOF_BLOCK_NONPHYSICAL,
    TOF_BLOCK_TRIGGER,
    TOF_STATUS_BLOCKED,
    TOF_STATUS_READY,
)


def build_tof_column(
    *,
    effective: dict[str, dict[str, Any]],
    arrival_samples: list[int | None],
    detector_validated: bool,
) -> tuple[list[float | None], str, str]:
    """Compute the canonical tof_us column from resolved parameters.

    Returns ``(tof_us_values, tof_status, tof_block_reason)`` where the
    status/reason describe the whole column (a chain-level gate) and any
    value stays null unless the full chain is ready.
    """
    if not detector_validated:
        return _blocked(arrival_samples, TOF_BLOCK_DETECTOR)

    fs_entry = effective.get("ultrasound.sampling_rate_hz", {})
    fs = fs_entry.get("value")
    if fs is None or not isinstance(fs, (int, float)) or fs <= 0:
        return _blocked(arrival_samples, TOF_BLOCK_FS)

    trigger_entry = effective.get("ultrasound.trigger_sample_index", {})
    trigger = trigger_entry.get("value")
    if trigger is None or not isinstance(trigger, (int, float)):
        return _blocked(arrival_samples, TOF_BLOCK_TRIGGER)
    trigger_i = int(trigger)

    tof_values: list[float | None] = []
    for arrival in arrival_samples:
        if arrival is None:
            tof_values.append(None)
            continue
        tof_us = (arrival - trigger_i) / fs * 1e6
        tof_values.append(tof_us if tof_us > 0 else None)
    if not any(v is not None for v in tof_values):
        # Gate is open but no event yields a physical flight time (e.g. the
        # signal is already present at the window start with trigger=0).
        return tof_values, TOF_STATUS_BLOCKED, TOF_BLOCK_NONPHYSICAL
    return tof_values, TOF_STATUS_READY, ""


def _blocked(arrival_samples: list[int | None], reason: str) -> tuple[list[float | None], str, str]:
    return [None] * len(arrival_samples), TOF_STATUS_BLOCKED, reason

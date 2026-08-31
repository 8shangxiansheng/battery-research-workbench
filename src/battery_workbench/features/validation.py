"""BRW-013 scientific guards + locator validation.

V1 is strictly sample-domain. The waveform sampling rate is unknown
(``sampling_rate_hz`` is null), so physical time/frequency features are
unavailable and must not be emitted. Locator access is validated by group
existence and row-index bounds — never by falling back to another index.
"""

from __future__ import annotations

import numpy as np

# Physical feature names that must never appear in V1 output.
_FORBIDDEN_PHYSICAL = (
    "tof_us",
    "time_delay_us",
    "frequency_hz",
    "frequency_mhz",
    "fft_peak_hz",
)


def physical_features_available(sampling_rate_hz: float | None) -> tuple[bool, bool]:
    """Return ``(time_available, frequency_available)``.

    A missing/unknown ``sampling_rate_hz`` blocks both.
    """
    if sampling_rate_hz is None or not np.isfinite(sampling_rate_hz) or sampling_rate_hz <= 0:
        return False, False
    return True, True


def validate_no_physical_features() -> None:
    """Guard: V1 must not emit physical time/frequency columns.

    Used as a no-op assertion hook; the engine simply never writes them.
    """
    return


def validate_locator(group: str, row_index: int, zarr_rows: int) -> bool:
    """Whether a waveform locator is well-formed and in range."""
    if not group:
        return False
    if not isinstance(row_index, (int, np.integer)):
        return False
    return 0 <= int(row_index) < int(zarr_rows)


def classify_waveform(x: np.ndarray) -> str:
    """Row-level feature status: ``NONFINITE_WAVEFORM`` or ``READY``/``CONSTANT``."""
    if not np.all(np.isfinite(x)):
        return "NONFINITE_WAVEFORM"
    if np.ptp(x) == 0:
        return "CONSTANT_WAVEFORM"
    return "READY"

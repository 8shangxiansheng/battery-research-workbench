"""BRW-015 scientific guards.

The frozen prohibitions: a frame cadence and a sample count can never provide
a waveform sampling rate, and an UNVERIFIED scientific-critical parameter
never unlocks a physical capability.
"""

from __future__ import annotations

# The known frame acquisition interval (seconds) in the current baseline.
FRAME_ACQUISITION_INTERVAL_S = 10.0
KNOWN_SAMPLE_COUNT = 1250


def frame_cadence_cannot_resolve_fs(cadence_s: float) -> bool:
    """The ~10s frame acquisition interval can never fill sampling_rate_hz."""
    return cadence_s >= 1.0


def sample_count_cannot_resolve_fs(sample_count: int) -> bool:
    """A sample count is a record length, never an invertible rate."""
    return sample_count > 0


def unverified_fs_unlocks_nothing(verification_status: str) -> bool:
    """An UNVERIFIED fs unlocks no physical capability."""
    return verification_status != "VERIFIED"

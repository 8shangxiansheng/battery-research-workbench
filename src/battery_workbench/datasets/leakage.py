"""Leakage-isolation policy for BRW-016 datasets."""

from __future__ import annotations

_LEAKAGE_REASONS = [
    "adjacent waveform correlation (10s frame cadence)",
    "continuous SOC trajectory within segments",
    "shared cycle SOH across thousands of frames",
    "shared reference capacity within experiment",
    "temporal proximity of frames",
]


def frame_random_split_prohibited() -> bool:
    """Fixed policy — frame-level random splits always leak."""
    return True


def leakage_reasons() -> list[str]:
    return list(_LEAKAGE_REASONS)


def minimum_safe_grouping_key() -> str:
    return "cycle_group_id"


def future_split_preference() -> list[str]:
    return ["battery_level (leave-one-battery-out)", "experiment_level", "cycle_group_fallback"]

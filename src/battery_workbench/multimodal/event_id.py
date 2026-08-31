"""Deterministic event identity for BRW-011.

The event id is anchored to the ultrasound frame grain only: battery, experiment,
ultrasound asset, and frame index. It is independent of the electrical matching
result, the output row ordinal, and any candidate selection.
"""

from __future__ import annotations


def build_measurement_event_id(
    battery_id: str,
    experiment_id: str,
    ultrasound_asset_id: str,
    frame_index_raw: int,
) -> str:
    """Build the deterministic canonical event id.

    Format: ``ME::{battery_id}::{experiment_id}::{ultrasound_asset_id}::{frame}``.
    """
    if not battery_id:
        raise ValueError("battery_id must not be empty")
    if not experiment_id:
        raise ValueError("experiment_id must not be empty")
    if not ultrasound_asset_id:
        raise ValueError("ultrasound_asset_id must not be empty")
    if frame_index_raw < 0:
        raise ValueError(f"frame_index_raw must be non-negative: {frame_index_raw}")
    return f"ME::{battery_id}::{experiment_id}::{ultrasound_asset_id}::{frame_index_raw}"

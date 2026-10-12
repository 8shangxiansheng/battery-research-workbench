"""Deterministic event identity for BRW-011.

The event id is anchored to the ultrasound frame grain only: battery, experiment,
ultrasound asset, and frame index. It is independent of the electrical matching
result, the output row ordinal, and any candidate selection.
"""

from __future__ import annotations

from collections.abc import Iterable


class MeasurementEventIdentityError(ValueError):
    """A canonical event-key column is malformed or non-unique."""

    def __init__(self, reason_code: str, artifact_name: str) -> None:
        self.reason_code = reason_code
        self.artifact_name = artifact_name
        super().__init__(
            f"{artifact_name} measurement_event_id is invalid: {reason_code}"
        )


def validate_measurement_event_ids(
    values: Iterable[object], *, artifact_name: str
) -> None:
    """Require event IDs to be non-empty, trimmed strings and unique."""
    event_ids = list(values)
    if any(not isinstance(value, str) for value in event_ids):
        raise MeasurementEventIdentityError(
            "MEASUREMENT_EVENT_ID_INVALID", artifact_name
        )
    string_ids = [value for value in event_ids if isinstance(value, str)]
    if any(not value or value.strip() != value for value in string_ids):
        raise MeasurementEventIdentityError(
            "MEASUREMENT_EVENT_ID_INVALID", artifact_name
        )
    if len(set(string_ids)) != len(string_ids):
        raise MeasurementEventIdentityError(
            "MEASUREMENT_EVENT_ID_DUPLICATE", artifact_name
        )


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

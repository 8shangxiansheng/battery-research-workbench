"""Fail-closed assignment of declared condition intervals to measurement events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from battery_workbench.conditions.segments import ConditionSegmentValidation
from battery_workbench.multimodal.schemas import CanonicalMeasurementEvent

ConditionAssignmentStatus = Literal[
    "ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK",
    "UNCLASSIFIED_NO_SEGMENT",
    "BLOCKED_CROSS_ASSET_TIMEBASE",
    "BLOCKED_TIMESTAMP_UNAVAILABLE",
    "CONFLICTING_SEGMENTS",
]


class ConditionAssignment(BaseModel):
    """One auditable event × condition-axis assignment decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    battery_id: str
    experiment_id: str
    condition_axis_id: str
    condition_value: str | None = None
    unit: str | None = None
    segment_id: str | None = None
    time_reference_asset_id: str | None = None
    event_asset_id: str
    event_timestamp: datetime | None = None
    status: ConditionAssignmentStatus
    absolute_timebase_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    synchronization_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"


def assign_condition_segments_to_events(
    segments: list[ConditionSegmentValidation],
    events: list[CanonicalMeasurementEvent],
) -> list[ConditionAssignment]:
    """Match events to operator-declared intervals without transferring clocks.

    Assignment is allowed only when the event's ultrasound asset is exactly the
    segment's declared time-reference asset. Cross-asset comparisons are blocked;
    provisional timestamps are not treated as validated absolute time. This
    function returns a separate provenance table and never mutates events.
    """
    segment_groups: dict[tuple[str, str, str], list[ConditionSegmentValidation]] = {}
    for validation in segments:
        segment = validation.segment
        key = (segment.battery_id, segment.experiment_id, segment.condition_axis_id)
        segment_groups.setdefault(key, []).append(validation)

    assignments: list[ConditionAssignment] = []
    for event in events:
        matching_groups = {
            axis: items
            for (battery_id, experiment_id, axis), items in segment_groups.items()
            if battery_id == event.battery_id and experiment_id == event.experiment_id
        }
        for axis, candidates in matching_groups.items():
            event_time = event.provisional_absolute_timestamp
            same_asset = [
                item
                for item in candidates
                if item.segment.time_reference_asset_id == event.ultrasound_asset_id
            ]
            cross_asset = [item for item in candidates if item not in same_asset]

            if event_time is None or event_time.utcoffset() is None:
                assignments.append(
                    _decision(event, axis, status="BLOCKED_TIMESTAMP_UNAVAILABLE")
                )
                continue

            matching = [
                item
                for item in same_asset
                if item.segment.start_time <= event_time < item.segment.end_time
            ]
            if len(matching) > 1:
                assignments.append(
                    _decision(event, axis, status="CONFLICTING_SEGMENTS")
                )
            elif matching:
                segment = matching[0].segment
                assignments.append(
                    ConditionAssignment(
                        event_id=event.measurement_event_id,
                        battery_id=event.battery_id,
                        experiment_id=event.experiment_id,
                        condition_axis_id=axis,
                        condition_value=segment.condition_value,
                        unit=segment.unit,
                        segment_id=segment.segment_id,
                        time_reference_asset_id=segment.time_reference_asset_id,
                        event_asset_id=event.ultrasound_asset_id,
                        event_timestamp=event_time,
                        status="ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK",
                    )
                )
            elif cross_asset:
                assignments.append(
                    _decision(
                        event,
                        axis,
                        status="BLOCKED_CROSS_ASSET_TIMEBASE",
                        time_reference_asset_id=cross_asset[0].segment.time_reference_asset_id,
                    )
                )
            else:
                assignments.append(
                    _decision(event, axis, status="UNCLASSIFIED_NO_SEGMENT")
                )
    return assignments


def _decision(
    event: CanonicalMeasurementEvent,
    axis: str,
    *,
    status: ConditionAssignmentStatus,
    time_reference_asset_id: str | None = None,
) -> ConditionAssignment:
    return ConditionAssignment(
        event_id=event.measurement_event_id,
        battery_id=event.battery_id,
        experiment_id=event.experiment_id,
        condition_axis_id=axis,
        time_reference_asset_id=time_reference_asset_id,
        event_asset_id=event.ultrasound_asset_id,
        event_timestamp=event.provisional_absolute_timestamp,
        status=status,
    )

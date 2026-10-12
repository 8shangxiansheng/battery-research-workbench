"""Read-only validation for evidence-linked, operator-declared condition intervals.

This module deliberately does not assign conditions to MeasurementEvents. It only
validates identity, explicit absolute-time intervals, DataAsset bounds, and source
evidence integrity. A validated file/checksum is not proof that a condition was
scientifically measured or that clocks were synchronized.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.experiment.manifest_loader import data_asset_matches

_REQUIRED_COLUMNS = {
    "segment_id",
    "battery_id",
    "experiment_id",
    "condition_axis_id",
    "condition_value",
    "unit",
    "time_reference_asset_id",
    "start_time",
    "end_time",
    "evidence_relative_path",
    "evidence_sha256",
    "declared_by",
    "declared_at",
}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ConditionSegment(BaseModel):
    """One operator-declared condition value over a half-open absolute-time interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str
    battery_id: str
    experiment_id: str
    condition_axis_id: str
    condition_value: str
    unit: str | None = None
    time_reference_asset_id: str
    start_time: datetime
    end_time: datetime
    evidence_relative_path: str
    evidence_sha256: str
    declared_by: str
    declared_at: datetime
    declaration_status: Literal["OPERATOR_DECLARED"] = "OPERATOR_DECLARED"

    @field_validator(
        "segment_id",
        "battery_id",
        "experiment_id",
        "condition_axis_id",
        "condition_value",
        "time_reference_asset_id",
        "evidence_relative_path",
        "declared_by",
        mode="before",
    )
    @classmethod
    def require_nonblank_identity(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("condition segment identity and evidence fields must be nonblank")
        return value.strip()

    @field_validator("start_time", "end_time", "declared_at", mode="before")
    @classmethod
    def parse_timezone_aware_datetime(cls, value: object) -> datetime:
        parsed = datetime.fromisoformat(value.strip()) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.utcoffset() is None:
            raise ValueError("condition segment timestamps must include an explicit UTC offset")
        return parsed

    @field_validator("evidence_sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("evidence_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_optional_unit(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> ConditionSegment:
        if self.start_time >= self.end_time:
            raise ValueError("condition segment interval must satisfy start_time < end_time")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("unit must be nonblank when supplied; use an explicit unit otherwise")
        return self


class ConditionSegmentValidation(BaseModel):
    """Validation outcome that separates manifest integrity from scientific clocks."""

    segment: ConditionSegment
    asset_window_status: Literal["WITHIN_DECLARED_ASSET_WINDOW"]
    absolute_timebase_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    synchronization_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    measurement_event_assignment_status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"


def _resolve_evidence(raw_root: Path, reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"evidence path must be relative to raw_root: {reference!r}")
    root = raw_root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"evidence path must resolve to a file beneath raw_root: {reference!r}")
    return candidate


def _verify_evidence(raw_root: Path, segment: ConditionSegment) -> None:
    path = _resolve_evidence(raw_root, segment.evidence_relative_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != segment.evidence_sha256:
        raise ValueError(
            f"condition segment {segment.segment_id!r} evidence checksum mismatch"
        )


def _resolve_time_reference(
    segment: ConditionSegment,
    data_assets: list[DataAsset],
) -> DataAsset:
    candidates = [
        asset
        for asset in data_assets
        if asset.asset_id == segment.time_reference_asset_id
        and data_asset_matches(asset, segment.battery_id, segment.experiment_id)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"condition segment {segment.segment_id!r} must reference exactly one "
            "DataAsset within the same Battery/Experiment identity"
        )
    asset = candidates[0]
    start, end = asset.file_start_time, asset.file_end_time
    if start is None or end is None or start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError(
            f"time-reference DataAsset {asset.asset_id!r} requires timezone-aware "
            "file_start_time and file_end_time"
        )
    if start >= end:
        raise ValueError(f"time-reference DataAsset {asset.asset_id!r} has invalid time bounds")
    if segment.start_time < start or segment.end_time > end:
        raise ValueError(
            f"condition segment {segment.segment_id!r} lies outside DataAsset "
            f"{asset.asset_id!r} time bounds"
        )
    return asset


def _reject_overlaps(segments: list[ConditionSegment]) -> None:
    groups: dict[tuple[str, str, str, str], list[ConditionSegment]] = {}
    for segment in segments:
        key = (
            segment.battery_id,
            segment.experiment_id,
            segment.time_reference_asset_id,
            segment.condition_axis_id,
        )
        groups.setdefault(key, []).append(segment)

    for key, items in groups.items():
        ordered = sorted(items, key=lambda item: item.start_time)
        for previous, current in pairwise(ordered):
            # Intervals are [start_time, end_time): adjacent segments are allowed.
            if current.start_time < previous.end_time:
                raise ValueError(
                    "overlapping condition segments for Battery/Experiment/asset/axis "
                    f"{key!r}: {previous.segment_id!r} and {current.segment_id!r}"
                )


def load_condition_segments(
    manifest_path: str | Path,
    *,
    raw_root: str | Path,
    data_assets: list[DataAsset],
) -> list[ConditionSegmentValidation]:
    """Load and validate a condition-segments CSV without modifying source data.

    Each row is an operator declaration only. Time windows must be offset-aware,
    contained by the referenced DataAsset's declared time bounds, backed by a
    raw-root evidence file with matching SHA-256, and non-overlapping within a
    Battery/Experiment/asset/axis. Uncovered intervals remain unclassified.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("condition segment manifest is missing its header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("condition segment manifest header contains duplicate columns")
        missing_columns = _REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            raise ValueError(
                "condition segment manifest is missing required columns: "
                f"{sorted(missing_columns)}"
            )
        rows = list(reader)

    segments = [ConditionSegment.model_validate(row) for row in rows]
    identities = [
        (item.battery_id, item.experiment_id, item.segment_id) for item in segments
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("segment_id must be unique within each Battery/Experiment")

    validated: list[ConditionSegmentValidation] = []
    for segment in segments:
        _resolve_time_reference(segment, data_assets)
        _verify_evidence(Path(raw_root), segment)
        validated.append(
            ConditionSegmentValidation(
                segment=segment,
                asset_window_status="WITHIN_DECLARED_ASSET_WINDOW",
            )
        )
    _reject_overlaps(segments)
    return validated

"""BRW-010 nearest-record matcher (Ultrasound LEFT, Electrical RIGHT).

Builds a read-only sorted timestamp lookup over electrical records, then, for
each ultrasound frame timestamp, finds the nearest electrical timestamp
group(s). It preserves candidate *counts* (distinct timestamps vs. records)
and reports ambiguity without guessing a selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from battery_workbench.synchronization.sync_schemas import (
    AmbiguityType,
    NearestCandidate,
)


@dataclass
class ElectricalIndex:
    """Read-only timestamp-sorted lookup over electrical records."""

    sorted_timestamps: list[datetime]
    record_lists: dict[datetime, list[dict]]
    timestamp_to_row: dict[datetime, list[int]]
    timestamp_record_counts: dict[datetime, int]
    duplicate_timestamp_set: set[datetime]
    record_count: int
    original_rows: pd.DataFrame = field(repr=False, default=None)  # type: ignore[assignment]
    locator_col: str = "source_row_index"

    @property
    def is_empty(self) -> bool:
        return self.record_count == 0


def build_electrical_index(
    records: pd.DataFrame,
    *,
    timestamp_col: str,
    locator_col: str,
    asset_col: str,
) -> ElectricalIndex:
    """Build a sorted, read-only lookup; never mutates the input frame."""
    records = records.reset_index(drop=True)
    if records.empty:
        return ElectricalIndex(
            sorted_timestamps=[],
            record_lists={},
            timestamp_to_row={},
            timestamp_record_counts={},
            duplicate_timestamp_set=set(),
            record_count=0,
        )

    group_map: dict[datetime, list[dict]] = {}
    for idx, row in records.iterrows():
        ts_val = pd.Timestamp(row[timestamp_col])
        record = {
            "row_index": int(idx),
            "locator": str(row[locator_col]),
            "asset_id": str(row[asset_col]),
            "timestamp": ts_val.to_pydatetime(),
        }
        group_map.setdefault(ts_val.to_pydatetime(), []).append(record)

    sorted_ts = sorted(group_map.keys())
    duplicate_set = {t for t, recs in group_map.items() if len(recs) > 1}
    record_counts = {t: len(recs) for t, recs in group_map.items()}
    return ElectricalIndex(
        sorted_timestamps=sorted_ts,
        record_lists=group_map,
        timestamp_to_row={},
        timestamp_record_counts=record_counts,
        duplicate_timestamp_set=duplicate_set,
        record_count=len(records),
        original_rows=records,
        locator_col=locator_col,
    )


@dataclass
class NearestMatchResult:
    """Result of nearest-candidate resolution for one ultrasound timestamp."""

    best_timestamp: datetime | None
    sync_error_s: float | None
    candidate_counts: list[int]
    candidate_timestamps: list[datetime]
    candidate_record_count: int
    ambiguity_type: AmbiguityType
    nearest_candidates: list[NearestCandidate] = field(default_factory=list)

    @property
    def candidate_timestamp_count(self) -> int:
        """Number of distinct nearest timestamp groups (tie-aware)."""
        return len(self.candidate_timestamps)

    def within_tolerance(self, max_sync_error_s: float) -> bool:
        """Whether the minimum error is within the given tolerance."""
        if self.sync_error_s is None:
            return False
        return self.sync_error_s <= max_sync_error_s


def _ambiguity_type(candidate_ts_count: int, candidate_counts: list[int]) -> AmbiguityType:
    """Classify ambiguity from distinct-timestamp count and per-group record counts.

    ``candidate_counts`` lists the number of records under each nearest
    timestamp group. A group with >=2 records is a duplicate timestamp.
    """
    has_multiple_ts = candidate_ts_count >= 2
    has_duplicate_group = any(count >= 2 for count in candidate_counts)
    if has_multiple_ts and has_duplicate_group:
        return "DUPLICATE_AND_EQUIDISTANT"
    if has_multiple_ts:
        return "EQUIDISTANT_TIMESTAMPS"
    if has_duplicate_group:
        return "DUPLICATE_ELECTRICAL_TIMESTAMP"
    return "NONE"


def find_nearest_candidates(
    ultrasound_timestamp: datetime,
    index: ElectricalIndex,
    *,
    tie_tolerance_s: float = 1e-9,
) -> NearestMatchResult:
    """Find the nearest electrical timestamp group(s) to one ultrasound time.

    Uses a sorted timestamp list; candidates are all timestamp groups whose
    distance to the ultrasound time equals the minimum (within the tie
    tolerance). Never mutates inputs.
    """
    if index.is_empty:
        return NearestMatchResult(
            best_timestamp=None,
            sync_error_s=None,
            candidate_counts=[],
            candidate_timestamps=[],
            candidate_record_count=0,
            ambiguity_type="NONE",
        )

    target = pd.Timestamp(ultrasound_timestamp)
    sorted_ts = index.sorted_timestamps
    # Bisect to locate the surrounding timestamps.
    import bisect

    pos = bisect.bisect_left(sorted_ts, target)
    nearby = []
    if pos < len(sorted_ts):
        nearby.append(pos)
    if pos > 0:
        nearby.append(pos - 1)
    # Dedup indices.
    nearby = sorted(set(nearby))

    if not nearby:
        return NearestMatchResult(
            best_timestamp=None,
            sync_error_s=None,
            candidate_counts=[],
            candidate_timestamps=[],
            candidate_record_count=0,
            ambiguity_type="NONE",
        )

    def dist(ts_val: datetime) -> float:
        return abs((pd.Timestamp(ts_val) - target).total_seconds())

    min_err = min(dist(sorted_ts[i]) for i in nearby)
    tied = [sorted_ts[i] for i in nearby if abs(dist(sorted_ts[i]) - min_err) <= tie_tolerance_s]

    # Build candidate records: all records under each tied timestamp group.
    candidates: list[NearestCandidate] = []
    record_total = 0
    for rank_ts, ts_val in enumerate(sorted(tied), start=1):
        recs = index.record_lists[ts_val]
        duplicate_count = len(recs)
        record_total += duplicate_count
        candidates.append(
            NearestCandidate(
                electrical_timestamp=ts_val,
                sync_error_s=dist(ts_val),
                candidate_timestamp_rank=rank_ts,
                candidate_record_rank=1,
                within_tolerance=False,
                electrical_timestamp_duplicate_count=duplicate_count,
            )
        )

    counts = [len(index.record_lists[t]) for t in tied]
    return NearestMatchResult(
        best_timestamp=min(tied, key=dist),
        sync_error_s=min_err,
        candidate_counts=counts,
        candidate_timestamps=sorted(tied),
        candidate_record_count=record_total,
        ambiguity_type=_ambiguity_type(len(tied), counts),
        nearest_candidates=candidates,
    )


def candidates_for_frame(
    ultrasound_timestamp: datetime,
    index: ElectricalIndex,
    *,
    tie_tolerance_s: float,
) -> list[dict]:
    """Return one candidate dict per nearest electrical record (audit table)."""
    result = find_nearest_candidates(ultrasound_timestamp, index, tie_tolerance_s=tie_tolerance_s)
    if result.best_timestamp is None:
        return []
    rows: list[dict] = []
    for cand in result.nearest_candidates:
        ts_rank = cand.candidate_timestamp_rank
        recs = index.record_lists[cand.electrical_timestamp]
        for rec_rank, rec in enumerate(recs, start=1):
            rows.append(
                {
                    "electrical_timestamp": rec["timestamp"],
                    "electrical_record_locator": rec["locator"],
                    "electrical_row_index": rec["row_index"],
                    "electrical_asset_id": rec["asset_id"],
                    "electrical_timestamp_duplicate_count": cand.electrical_timestamp_duplicate_count,
                    "sync_error_s": cand.sync_error_s,
                    "candidate_timestamp_rank": ts_rank,
                    "candidate_record_rank": rec_rank,
                }
            )
    return rows

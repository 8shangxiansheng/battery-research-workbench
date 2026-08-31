from __future__ import annotations

from datetime import datetime

import pandas as pd


def is_near_boundary(
    timestamp: datetime,
    boundaries: list[datetime],
    tolerance_s: float = 1.0,
) -> bool:
    return any(
        abs((timestamp - boundary).total_seconds()) <= tolerance_s for boundary in boundaries
    )


def detect_boundary(records: pd.DataFrame) -> pd.DataFrame:
    """Add ``boundary_flag`` / ``boundary_reason`` columns to an electrical frame.

    Boundary detection uses the *original record order* (index / source_row_index),
    never a timestamp-sorted copy, so that step/cycle transitions are evaluated
    against the canonical event sequence. Boundary evidence is diagnostics only:
    it never participates in nearest-time matching.

    Evidence:
      A. the record's timestamp is duplicated in the frame
      B. cycle id changes vs. the adjacent (previous) original record
      C. step id changes vs. the adjacent (previous) original record
      D. an explicit start/end marker is present (``step_boundary_raw`` non-null)
    """
    records = records.reset_index(drop=True)
    n = len(records)
    flags: list[bool] = [False] * n
    reasons: list[str] = [""] * n

    has_ts = "timestamp" in records.columns
    has_cycle = "cycle_index_raw" in records.columns
    has_step = "step_index_raw" in records.columns
    has_marker = "step_boundary_raw" in records.columns

    # A. duplicate timestamp evidence.
    dup_ts: set = set()
    if has_ts:
        counts = records["timestamp"].value_counts()
        dup_ts = set(counts[counts > 1].index)

    for i in range(n):
        evidence: list[str] = []
        if has_ts and records["timestamp"].iloc[i] in dup_ts:
            evidence.append("duplicate_timestamp")
        if has_marker and pd.notna(records["step_boundary_raw"].iloc[i]):
            evidence.append("explicit_boundary_marker")
        if i > 0:
            if (
                has_cycle
                and records["cycle_index_raw"].iloc[i] != records["cycle_index_raw"].iloc[i - 1]
            ):
                evidence.append("cycle_transition")
            if (
                has_step
                and records["step_index_raw"].iloc[i] != records["step_index_raw"].iloc[i - 1]
            ):
                evidence.append("step_transition")
        if evidence:
            flags[i] = True
            reasons[i] = "|".join(evidence)

    out = records.copy()
    out["boundary_flag"] = flags
    out["boundary_reason"] = reasons
    return out

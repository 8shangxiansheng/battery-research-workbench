"""BRW-011 event quality + integrity validation.

Deterministic quality mapping from upstream match status, plus integrity checks
that enforce: no timestamp re-matching, candidate-count invariants, ambiguous
events carry no selected record, and waveform locators are only carried (never
samples).
"""

from __future__ import annotations

import pandas as pd

from battery_workbench.multimodal.event_id import build_measurement_event_id

# Event quality status vocabulary.
READY = "READY"
AMBIGUOUS_SYNC = "AMBIGUOUS_SYNC"
OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
TIMESTAMP_UNAVAILABLE = "TIMESTAMP_UNAVAILABLE"
INTEGRITY_ERROR = "INTEGRITY_ERROR"


def compute_event_quality(
    match_status: str,
    *,
    within: bool,
    locator_valid: bool,
) -> str:
    """Deterministic quality mapping (BRW-011 §14)."""
    if match_status == "MATCHED_UNIQUE":
        if within and locator_valid:
            return READY
        return INTEGRITY_ERROR
    if match_status == "MATCHED_AMBIGUOUS":
        return AMBIGUOUS_SYNC
    if match_status == "OUT_OF_TOLERANCE":
        return OUT_OF_TOLERANCE
    if match_status == "TIMESTAMP_UNAVAILABLE":
        return TIMESTAMP_UNAVAILABLE
    return INTEGRITY_ERROR


def validate_whitelist_only(columns: list[str], whitelist: set[str]) -> bool:
    """Ensure extracted columns are a strict subset of the whitelist."""
    return set(columns) <= whitelist


def validate_waveform_locator(group: str, row_index: int, zarr_rows: int) -> bool:
    """Whether a waveform locator is in-range. Never reads sample data."""
    if not group:
        return False
    return 0 <= row_index < zarr_rows


def _event_id(row: pd.Series) -> str | None:
    """Build an event id only if the identity columns are present; else None."""
    if not {"battery_id", "experiment_id", "ultrasound_asset_id"}.issubset(row.index):
        return None
    return build_measurement_event_id(
        str(row["battery_id"]),
        str(row["experiment_id"]),
        str(row["ultrasound_asset_id"]),
        int(row["frame_index_raw"]),
    )


def _frame_identity(aligned: pd.DataFrame) -> dict[int, str]:
    """Build frame_index_raw -> measurement_event_id from the aligned frame."""
    mapping: dict[int, str] = {}
    for _, row in aligned.iterrows():
        eid = _event_id(row)
        if eid is not None:
            mapping[int(row["frame_index_raw"])] = eid
    return mapping


def validate_candidate_invariant(
    aligned: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    """Every ambiguous event's candidate relation rows must equal candidate_record_count."""
    if candidates.empty:
        return
    # Candidates may not carry measurement_event_id; derive via aligned frame identity.
    frame_to_event = _frame_identity(aligned)
    if "measurement_event_id" in candidates.columns:
        count_by_event: dict[str, int] = candidates.groupby("measurement_event_id").size().to_dict()
    else:
        count_by_event = {}
        for _, crow in candidates.iterrows():
            frame = int(crow["frame_index_raw"])
            eid = frame_to_event.get(frame)
            if eid is not None:
                count_by_event[eid] = count_by_event.get(eid, 0) + 1
    for _, row in aligned.iterrows():
        if row["match_status"] != "MATCHED_AMBIGUOUS":
            continue
        eid = frame_to_event.get(int(row["frame_index_raw"]))
        if eid is None:
            continue
        declared = (
            int(row["candidate_record_count"]) if pd.notna(row["candidate_record_count"]) else 0
        )
        actual = int(count_by_event.get(eid, 0))
        if actual != declared:
            raise ValueError(
                f"candidate count mismatch for {eid}: declared={declared} actual={actual}"
            )


def validate_ambiguous_no_selection(aligned: pd.DataFrame) -> None:
    """Ambiguous frames must NOT carry a selected electrical locator."""
    for _, row in aligned.iterrows():
        if row["match_status"] == "MATCHED_AMBIGUOUS":
            locator = row.get("electrical_record_locator")
            if locator is not None and pd.notna(locator) and str(locator).strip() != "":
                eid = _event_id(row)
                label = eid if eid is not None else f"frame {row.get('frame_index_raw')}"
                raise ValueError(
                    f"ambiguous frame {label} must not carry a selected locator: {locator!r}"
                )

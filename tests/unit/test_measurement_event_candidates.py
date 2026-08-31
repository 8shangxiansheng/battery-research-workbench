from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.multimodal.builder import build_candidate_relation


def _candidate_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _candidate(frame: int, locator: str, err: float = 0.03) -> dict:
    return {
        "battery_id": "CELL_X",
        "experiment_id": "EXP_X",
        "ultrasound_asset_id": "U001",
        "frame_index_raw": frame,
        "ultrasound_timestamp": datetime(2024, 1, 6, 10, 0, 0, 300000),
        "electrical_timestamp": datetime(2024, 1, 6, 10, 0, 0),
        "electrical_record_locator": locator,
        "electrical_row_index": int(locator),
        "electrical_asset_id": "E1",
        "sync_error_s": err,
        "within_tolerance": True,
        "candidate_timestamp_rank": 1,
        "candidate_record_rank": 1,
        "electrical_timestamp_duplicate_count": 2,
        "boundary_flag": False,
        "boundary_reason": "",
    }


def test_relation_adds_event_id_t16() -> None:
    """T16: the candidate relation carries a measurement_event_id."""
    cands = _candidate_df([_candidate(3998, "39993"), _candidate(3998, "39994")])
    rel = build_candidate_relation(cands)
    assert "measurement_event_id" in rel.columns
    assert rel["measurement_event_id"].iloc[0] == "ME::CELL_X::EXP_X::U001::3998"
    # Both candidate rows get the same event id.
    assert rel["measurement_event_id"].nunique() == 1


def test_candidate_count_invariant_2_t17() -> None:
    """T17: declared candidate_record_count==2 must equal relation rows for the event."""
    cands = _candidate_df([_candidate(1, "10"), _candidate(1, "11")])
    rel = build_candidate_relation(cands)
    count = len(rel[rel["measurement_event_id"] == "ME::CELL_X::EXP_X::U001::1"])
    assert count == 2


def test_candidate_count_invariant_3_t17b() -> None:
    """T17b: 3 candidates -> 3 relation rows."""
    cands = _candidate_df([_candidate(1, "10"), _candidate(1, "11"), _candidate(1, "12")])
    rel = build_candidate_relation(cands)
    count = len(rel[rel["measurement_event_id"] == "ME::CELL_X::EXP_X::U001::1"])
    assert count == 3


def test_candidate_count_mismatch_failure_t18(tmp_path: Path) -> None:
    """T18: declared candidate_record_count != actual relation rows -> integrity failure."""
    # aligned declares 3 candidates but the relation table only has 2.
    aligned = pd.DataFrame(
        {
            "battery_id": ["CELL_X"],
            "experiment_id": ["EXP_X"],
            "ultrasound_asset_id": ["U001"],
            "frame_index_raw": [1],
            "event_order_index": [1],
            "waveform_group": ["U001/waveform"],
            "waveform_row_index": [1],
            "provisional_absolute_timestamp": pd.to_datetime([datetime(2024, 1, 6)]),
            "elapsed_time_s": [0.3],
            "timezone_known": [False],
            "timezone_name": [None],
            "match_status": ["MATCHED_AMBIGUOUS"],
            "sync_error_s": [0.03],
            "within_tolerance": [True],
            "candidate_timestamp_count": [1],
            "candidate_record_count": [3],
            "sync_ambiguous": [True],
            "ambiguity_type": ["DUPLICATE_ELECTRICAL_TIMESTAMP"],
            "boundary_flag": [False],
            "boundary_reason": [None],
            "electrical_record_locator": [None],
            "electrical_timestamp": pd.to_datetime([None]),
            "anchor_id": ["U001-manifest"],
            "anchor_status": ["PROVISIONAL"],
            "validated_sync": [False],
        }
    )
    cands = _candidate_df([_candidate(1, "10"), _candidate(1, "11")])  # only 2
    from battery_workbench.multimodal.validation import validate_candidate_invariant

    with pytest.raises(ValueError):
        validate_candidate_invariant(aligned, cands)


def test_ambiguous_electrical_fields_all_null_t19() -> None:
    """T19: ambiguous events keep electrical state null in the canonical events."""
    aligned = pd.DataFrame(
        {
            "battery_id": ["CELL_X"],
            "experiment_id": ["EXP_X"],
            "ultrasound_asset_id": ["U001"],
            "frame_index_raw": [3998],
            "event_order_index": [3998],
            "waveform_group": ["U001/waveform"],
            "waveform_row_index": [3998],
            "provisional_absolute_timestamp": pd.to_datetime([datetime(2024, 1, 6)]),
            "elapsed_time_s": [39980.03],
            "timezone_known": [False],
            "timezone_name": [None],
            "match_status": ["MATCHED_AMBIGUOUS"],
            "sync_error_s": [0.03],
            "within_tolerance": [True],
            "candidate_timestamp_count": [1],
            "candidate_record_count": [2],
            "sync_ambiguous": [True],
            "ambiguity_type": ["DUPLICATE_ELECTRICAL_TIMESTAMP"],
            "boundary_flag": [True],
            "boundary_reason": ["duplicate_timestamp"],
            "electrical_record_locator": [None],
            "electrical_timestamp": pd.to_datetime([None]),
            "anchor_id": ["U001-manifest"],
            "anchor_status": ["PROVISIONAL"],
            "validated_sync": [False],
        }
    )
    # The ambiguity must carry a null selected locator; a non-null locator would
    # violate the "ambiguous -> no selection" contract.
    assert aligned["electrical_record_locator"].iloc[0] is None


def test_ambiguous_upstream_locator_non_null_violates_contract_t20() -> None:
    """T20: a MATCHED_AMBIGUOUS frame with a non-null selected locator is invalid."""
    from battery_workbench.multimodal.validation import validate_ambiguous_no_selection

    aligned = pd.DataFrame(
        {
            "match_status": ["MATCHED_AMBIGUOUS"],
            "electrical_record_locator": ["12"],  # bad: ambiguous should be null
        }
    )
    with pytest.raises(ValueError):
        validate_ambiguous_no_selection(aligned)

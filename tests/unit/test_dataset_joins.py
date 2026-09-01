"""T01-T08: exact event/cycle join integrity."""

from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.datasets.joins import (
    DatasetIntegrityError,
    exact_cycle_join,
    exact_event_join,
)


def _features(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "cycle_index_raw": [1.0] * n,
            "waveform_rms_a_u": [1.0 * j for j in range(n)],
            "event_order_index": list(range(n)),
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "feature_status": ["READY"] * n,
            "analysis_eligible": [True] * n,
            "sync_error_s": [0.03] * n,
            "event_quality_status": ["READY"] * n,
            "elapsed_time_s": [float(i * 10) for i in range(n)],
            "step_type": ["恒流放电"] * n,
            "voltage_v": [3.5] * n,
            "current_a": [1.0] * n,
            "temperature_c": [25.0] * n,
            "step_index_raw": [4.0] * n,
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * n),
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
        }
    )


def _labels(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "cycle_index_raw": [1.0] * n,
            "soc_reference_percent": [10.0 * i for i in range(n)],
            "soc_label_eligible": [True] * n,
            "soc_label_temporality": ["RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"] * n,
            "soc_reference_quality": ["VALID_REFERENCE"] * n,
            "soc_formula_version": ["0.2.0"] * n,
            "soc_anchor_quality": ["REFERENCE_PROTOCOL_ANCHOR"] * n,
            "soc_integral_unbounded_percent": [10.0 * i for i in range(n)],
            "soh_capacity_reference_percent": [100.0] * n,
            "soh_reference_quality": ["VALID_REFERENCE"] * n,
            "soh_label_eligible": [True] * n,
            "soh_reference_cycle_index": [1] * n,
            "battery_group_id": ["BG::CELL_X"] * n,
            "experiment_group_id": ["EG::CELL_X::EXP_X"] * n,
            "cycle_group_id": [f"CG::CELL_X::EXP_X::{(j % 2) + 1}" for j in range(n)],
            "label_group_id": [f"LG::CELL_X::EXP_X::{(j % 2) + 1}" for j in range(n)],
        }
    )


def _cycles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X", "CELL_X"],
            "experiment_id": ["EXP_X", "EXP_X"],
            "cycle_index_raw": [1.0, 2.0],
            "soh_capacity_reference_percent": [100.0, 99.68],
            "soh_reference_cycle_index": [1, 1],
            "soh_reference_quality": ["VALID_REFERENCE"] * 2,
            "soh_label_eligible": [True, True],
        }
    )


def test_exact_event_join_t01() -> None:
    joined = exact_event_join(_features(), _labels())
    assert len(joined) == 4
    assert "soc_reference_percent" in joined.columns
    assert "waveform_rms_a_u" in joined.columns


def test_feature_duplicate_key_fail_t02() -> None:
    feats = pd.concat([_features(2), _features(2).iloc[:1]], ignore_index=True)
    with pytest.raises(DatasetIntegrityError, match="duplicate"):
        exact_event_join(feats, _labels(2))


def test_label_duplicate_key_fail_t03() -> None:
    lbls = pd.concat([_labels(2), _labels(2).iloc[:1]], ignore_index=True)
    with pytest.raises(DatasetIntegrityError, match="duplicate"):
        exact_event_join(_features(2), lbls)


def test_feature_missing_label_fail_t04() -> None:
    feats = _features(4)
    lbls = _labels(3)  # ME::3 missing
    with pytest.raises(DatasetIntegrityError, match="missing"):
        exact_event_join(feats, lbls)


def test_surplus_labels_reported_t05() -> None:
    """Surplus labels (no feature) are reported, not an integrity failure."""
    joined, surplus = exact_event_join(_features(2), _labels(4), report_surplus=True)
    assert len(joined) == 2
    assert surplus == 2


def test_no_timestamp_join_t06() -> None:
    """Join is on measurement_event_id only — timestamps are never compared."""
    feats = _features(2)
    lbls = _labels(2)
    # Different timestamps on both sides — join must still work.
    feats["provisional_absolute_timestamp"] = pd.to_datetime(["2020-01-01", "2020-01-02"])
    joined = exact_event_join(feats, lbls)
    assert len(joined) == 2


def test_no_row_position_join_t07() -> None:
    """Shuffling one side does not corrupt the join."""
    feats = _features(4)
    lbls = _labels(4).sample(frac=1, random_state=42)
    joined = exact_event_join(feats, lbls)
    r0 = joined[joined["measurement_event_id"] == "ME::0"].iloc[0]
    assert r0["soc_reference_percent"] == 0.0
    assert r0["waveform_rms_a_u"] == 0.0


def test_exact_cycle_join_t08() -> None:
    result = exact_cycle_join(_features(4), _cycles())
    assert len(result) == 4
    assert "soh_capacity_reference_percent" in result.columns
    assert result["soh_capacity_reference_percent"].nunique() == 1  # all cycle 1

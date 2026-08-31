from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from battery_workbench.analysis.conditions import apply_condition_slice
from battery_workbench.analysis.schemas import ConditionSliceSpec


def _events() -> pd.DataFrame:
    """A small synthetic event set covering the key filter dimensions."""
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * 6,
            "experiment_id": ["EXP_X"] * 6,
            "measurement_event_id": [f"ME::CELL_X::EXP_X::U001::{i}" for i in range(6)],
            "ultrasound_asset_id": ["U001"] * 6,
            "frame_index_raw": list(range(6)),
            "event_order_index": list(range(6)),
            "waveform_group": ["U001/waveform"] * 6,
            "waveform_row_index": list(range(6)),
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * 6),
            "elapsed_time_s": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
            "cycle_index_raw": [1.0, 1.0, 1.0, 2.0, 2.0, 2.0],
            "step_index_raw": [1.0, 2.0, 3.0, 4.0, 5.0, 5.0],
            "step_type": ["恒流充电", "恒流充电", "搁置", "恒压充电", "恒流放电", "恒流放电"],
            "voltage_v": [3.5, 3.8, 4.0, 3.2, 3.6, 3.9],
            "current_a": [1.0, 0.5, 0.0, -0.5, -1.0, -1.5],
            "capacity_ah": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
            "temperature_c": [25.0, 25.1, 25.2, 25.3, 25.4, 25.5],
            "soc_dod_percent": [10.0, 30.0, 50.0, 70.0, 90.0, 99.0],
            "sync_error_s": [0.03, 0.03, 0.03, 0.03, 0.03, 0.6],
            "boundary_flag": [False] * 6,
            "event_quality_status": ["READY", "READY", "READY", "READY", "READY", "READY"],
            "analysis_eligible": [True, True, True, True, True, True],
        }
    )


def test_default_eligible_only_t01() -> None:
    """T01: default excludes non-eligible events."""
    events = _events()
    events.loc[0, "analysis_eligible"] = False
    events.loc[0, "event_quality_status"] = "AMBIGUOUS_SYNC"
    out, _ = apply_condition_slice(events, ConditionSliceSpec())
    assert len(out) == 5
    assert (out["analysis_eligible"] == True).all()


def test_include_ineligible_t02() -> None:
    """T02: explicit include_ineligible keeps all rows."""
    events = _events()
    events.loc[0, "analysis_eligible"] = False
    out, _ = apply_condition_slice(events, ConditionSliceSpec(analysis_eligible_only=False))
    assert len(out) == 6


def test_cycle_single_t03() -> None:
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(cycle_indices=[1]))
    assert set(out["cycle_index_raw"]) == {1.0}


def test_cycle_multi_or_t04() -> None:
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(cycle_indices=[1, 2]))
    assert len(out) == 6  # both cycles present


def test_step_single_t05() -> None:
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(step_indices=[5]))
    assert set(out["step_index_raw"]) == {5.0}
    assert len(out) == 2


def test_step_multi_or_t06() -> None:
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(step_indices=[1, 3]))
    # step_index_raw values: [1,2,3,4,5,5]; step 1 -> row 0, step 3 -> row 2.
    assert len(out) == 2
    assert set(out["step_index_raw"]) == {1.0, 3.0}


def test_cross_field_and_t07() -> None:
    """Different fields combine with AND."""
    out, _ = apply_condition_slice(
        _events(),
        ConditionSliceSpec(cycle_indices=[1], step_types=["恒流充电"]),
    )
    assert len(out) == 2
    assert (out["cycle_index_raw"] == 1).all()


def test_voltage_inclusive_t08() -> None:
    """3.5 <= voltage <= 4.0 is inclusive on both bounds."""
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(voltage_v_min=3.5, voltage_v_max=4.0)
    )
    # voltage values: [3.5,3.8,4.0,3.2,3.6,3.9]; in [3.5,4.0] -> 3.5,3.8,4.0,3.6,3.9.
    assert 3.5 in set(out["voltage_v"])  # inclusive min
    assert 4.0 in set(out["voltage_v"])  # inclusive max
    assert 3.2 not in set(out["voltage_v"])  # below the range


def test_current_inclusive_t09() -> None:
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(current_a_min=-1.0, current_a_max=1.0)
    )
    assert 1.0 in set(out["current_a"])
    assert -1.0 in set(out["current_a"])


def test_capacity_range_t10() -> None:
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(capacity_ah_min=0.2, capacity_ah_max=0.4)
    )
    assert len(out) == 3  # 0.2, 0.3, 0.4


def test_temperature_range_t11() -> None:
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(temperature_c_min=25.1, temperature_c_max=25.4)
    )
    assert len(out) == 4


def test_soc_dod_range_t12() -> None:
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(soc_dod_percent_min=40, soc_dod_percent_max=60)
    )
    assert len(out) == 1  # row 2 (50%)


def test_null_excluded_t13() -> None:
    """A numeric range filter excludes numeric-null rows by default."""
    events = _events()
    events.loc[1, "voltage_v"] = None
    out, _ = apply_condition_slice(events, ConditionSliceSpec(voltage_v_min=3.0, voltage_v_max=4.5))
    assert 1 not in out["frame_index_raw"].tolist()


def test_include_null_t14() -> None:
    events = _events()
    events.loc[1, "voltage_v"] = None
    out, _ = apply_condition_slice(
        events,
        ConditionSliceSpec(voltage_v_min=3.0, voltage_v_max=4.5, include_null_numeric_values=True),
    )
    assert 1 in out["frame_index_raw"].tolist()


def test_elapsed_range_t15() -> None:
    out, _ = apply_condition_slice(
        _events(), ConditionSliceSpec(elapsed_time_s_min=10.0, elapsed_time_s_max=30.0)
    )
    assert len(out) == 3


def test_timestamp_range_t16() -> None:
    out, _ = apply_condition_slice(
        _events(),
        ConditionSliceSpec(
            provisional_timestamp_start=datetime(2024, 1, 6, 10, 0, 0),
            provisional_timestamp_end=datetime(2024, 1, 6, 10, 0, 0),
        ),
    )
    assert len(out) == 6  # all share the same timestamp


def test_max_sync_error_t17() -> None:
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(max_sync_error_s=0.1))
    assert len(out) == 5  # row with 0.6 excluded


def test_boundary_filter_t18() -> None:
    events = _events()
    events.loc[2, "boundary_flag"] = True
    out, _ = apply_condition_slice(events, ConditionSliceSpec(boundary_flag=True))
    assert len(out) == 1
    assert out["frame_index_raw"].tolist() == [2]


def test_invalid_range_t19() -> None:
    with pytest.raises(ValueError):
        apply_condition_slice(
            _events(),
            ConditionSliceSpec(voltage_v_min=4.0, voltage_v_max=3.0),  # min > max
        )


def test_unknown_step_t20() -> None:
    """Unknown step value yields 0 rows + warning, never a guessed mapping."""
    out, _ = apply_condition_slice(_events(), ConditionSliceSpec(step_types=["FOO"]))
    assert len(out) == 0

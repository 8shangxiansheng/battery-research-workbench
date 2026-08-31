from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.analysis.conditions import apply_condition_slice
from battery_workbench.analysis.schemas import AnalysisSliceConfig, ConditionSliceSpec
from battery_workbench.analysis.slice_engine import create_analysis_slice

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS = (
    REPO_ROOT
    / "data"
    / "processed"
    / "multimodal"
    / "CELL_001"
    / "EXP_001"
    / "measurement_events.parquet"
)
CONFIG = AnalysisSliceConfig.from_yaml(REPO_ROOT / "configs" / "analysis_slice.yaml")


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 measurement events not present")
def test_real_ready_all_t33(tmp_path: Path) -> None:
    events = pd.read_parquet(EVENTS)
    real_eligible = int(events["analysis_eligible"].sum())
    report = create_analysis_slice(
        measurement_events_path=EVENTS,
        spec=ConditionSliceSpec(analysis_eligible_only=True),
        output_root=tmp_path,
        config=CONFIG,
    )
    assert report.analysis_slice_id.startswith("AS::")
    assert report.output_row_count == real_eligible == 3995
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_001"
        / "EXP_001"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert (out["analysis_eligible"] == True).all()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 measurement events not present")
def test_real_cycle_1_t34(tmp_path: Path) -> None:
    report = create_analysis_slice(
        measurement_events_path=EVENTS,
        spec=ConditionSliceSpec(analysis_eligible_only=True, cycle_indices=[1]),
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_001"
        / "EXP_001"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert report.output_row_count == 2092
    assert (out["cycle_index_raw"] == 1.0).all()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 measurement events not present")
def test_real_discharge_t35(tmp_path: Path) -> None:
    # DISCHARGE uses the actual canonical step_type value.
    events = pd.read_parquet(EVENTS)
    discharge_value = "恒流放电"
    assert discharge_value in set(events["step_type"].dropna().unique())
    report = create_analysis_slice(
        measurement_events_path=EVENTS,
        spec=ConditionSliceSpec(analysis_eligible_only=True, step_types=[discharge_value]),
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_001"
        / "EXP_001"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert report.output_row_count == 1588
    assert (out["step_type"] == discharge_value).all()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 measurement events not present")
def test_real_mid_soc_dod_t36(tmp_path: Path) -> None:
    # soc_dod is well-covered (not all-null), so MID_SOC_DOD is implemented directly.
    report = create_analysis_slice(
        measurement_events_path=EVENTS,
        spec=ConditionSliceSpec(
            analysis_eligible_only=True,
            soc_dod_percent_min=40,
            soc_dod_percent_max=60,
        ),
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_001"
        / "EXP_001"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert report.output_row_count > 0
    assert (out["soc_dod_percent"] >= 40).all()
    assert (out["soc_dod_percent"] <= 60).all()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 measurement events not present")
def test_real_golden_audit(tmp_path: Path) -> None:
    """Independent per-row audit of READY_ALL + CYCLE_1 + DISCHARGE slices."""
    events = pd.read_parquet(EVENTS)

    # READY_ALL: every row must be analysis_eligible.
    ready, _ = apply_condition_slice(events, ConditionSliceSpec(analysis_eligible_only=True))
    assert (ready["analysis_eligible"] == True).all()

    # CYCLE_1 golden: first/middle/last rows all cycle 1.
    cycle1, _ = apply_condition_slice(
        events, ConditionSliceSpec(analysis_eligible_only=True, cycle_indices=[1])
    )
    assert (cycle1["cycle_index_raw"] == 1.0).all()
    # spot-check first/middle/last.
    for idx in (0, len(cycle1) // 2, len(cycle1) - 1):
        assert cycle1.iloc[idx]["cycle_index_raw"] == 1.0
        assert cycle1.iloc[idx]["analysis_eligible"]

    # DISCHARGE golden: every row's step_type is the discharge value.
    discharge, _ = apply_condition_slice(
        events, ConditionSliceSpec(analysis_eligible_only=True, step_types=["恒流放电"])
    )
    assert (discharge["step_type"] == "恒流放电").all()
    for idx in (0, len(discharge) // 2, len(discharge) - 1):
        assert discharge.iloc[idx]["step_type"] == "恒流放电"

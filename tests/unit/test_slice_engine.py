from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from battery_workbench.analysis.schemas import AnalysisSliceConfig, ConditionSliceSpec
from battery_workbench.analysis.slice_engine import create_analysis_slice


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * 4,
            "experiment_id": ["EXP_X"] * 4,
            "measurement_event_id": [f"ME::CELL_X::EXP_X::U001::{i}" for i in range(4)],
            "ultrasound_asset_id": ["U001"] * 4,
            "frame_index_raw": list(range(4)),
            "event_order_index": list(range(4)),
            "waveform_group": ["U001/waveform"] * 4,
            "waveform_row_index": list(range(4)),
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * 4),
            "elapsed_time_s": [0.0, 10.0, 20.0, 30.0],
            "cycle_index_raw": [1.0, 1.0, 2.0, 2.0],
            "step_index_raw": [1.0, 1.0, 5.0, 5.0],
            "step_type": ["恒流充电", "恒流充电", "恒流放电", "恒流放电"],
            "voltage_v": [3.5, 3.8, 3.6, 3.9],
            "current_a": [1.0, 0.5, -1.0, -1.5],
            "capacity_ah": [0.0, 0.1, 0.4, 0.5],
            "temperature_c": [25.0, 25.1, 25.4, 25.5],
            "soc_dod_percent": [10.0, 30.0, 90.0, 99.0],
            "sync_error_s": [0.03, 0.03, 0.03, 0.6],
            "boundary_flag": [False] * 4,
            "event_quality_status": ["READY"] * 4,
            "analysis_eligible": [True] * 4,
        }
    )


def _config() -> AnalysisSliceConfig:
    return AnalysisSliceConfig()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_events(tmp_path: Path) -> Path:
    p = tmp_path / "events.parquet"
    _events().to_parquet(p, index=False)
    return p


def test_preserve_event_id_and_waveform_t26_t27(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(cycle_indices=[1]),
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_X"
        / "EXP_X"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert "measurement_event_id" in out.columns
    assert "waveform_group" in out.columns
    assert "waveform_row_index" in out.columns
    # Preserved exact event ids.
    assert out["measurement_event_id"].tolist() == [
        "ME::CELL_X::EXP_X::U001::0",
        "ME::CELL_X::EXP_X::U001::1",
    ]


def test_no_waveform_samples_t28(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(),
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_X"
        / "EXP_X"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    for forbidden in ("waveform", "samples", "raw_waveform", "tof_us", "fft_peak_hz"):
        assert forbidden not in out.columns


def test_preserve_order_t29(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(),
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_X"
        / "EXP_X"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert out["frame_index_raw"].tolist() == [0, 1, 2, 3]


def test_empty_slice_t30(tmp_path: Path) -> None:
    """An empty (legal) slice persists an empty, schema-consistent parquet."""
    events_path = _write_events(tmp_path)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(step_types=["FOO"]),
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "analysis_slices"
        / "CELL_X"
        / "EXP_X"
        / report.analysis_slice_id
        / "analysis_slice.parquet"
    )
    assert len(out) == 0
    assert "measurement_event_id" in out.columns


def test_filter_breakdown_t31(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(cycle_indices=[1], current_a_min=0.0),
        output_root=tmp_path,
        config=_config(),
    )
    assert report.filter_breakdown["rows_before"] == 4
    assert report.filter_breakdown["rows_after_quality"] == 4
    assert report.filter_breakdown["rows_after_cycle"] == 2
    assert report.filter_breakdown["rows_after_current"] == 2


def test_input_immutable_t32(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    before = _sha256(events_path)
    create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(),
        output_root=tmp_path,
        config=_config(),
    )
    assert _sha256(events_path) == before


def test_slice_id_in_report_consistent(tmp_path: Path) -> None:
    events_path = _write_events(tmp_path)
    r1 = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(cycle_indices=[1]),
        output_root=tmp_path,
        config=_config(),
    )
    r2 = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(cycle_indices=[1]),
        output_root=tmp_path,
        config=_config(),
    )
    assert r1.analysis_slice_id == r2.analysis_slice_id

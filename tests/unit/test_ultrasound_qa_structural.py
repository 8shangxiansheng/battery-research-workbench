from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import zarr

from battery_workbench.ultrasound.qa import UltrasoundQAConfig, run_ultrasound_qa


def run_fixture(factory: Callable[..., Path], tmp_path: Path, **kwargs: object):
    input_dir = factory(**kwargs)
    report = run_ultrasound_qa(
        "CELL_TEST",
        "EXP_TEST",
        input_dir,
        tmp_path / "artifacts" / input_dir.name,
        UltrasoundQAConfig(),
    )
    return input_dir, report


def codes(report: object) -> set[str]:
    return {item.code for item in report.anomalies}  # type: ignore[attr-defined]


def test_perfect_synthetic_passes(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    _, report = run_fixture(ultrasound_qa_input_factory, tmp_path)
    assert report.status == "PASS"
    assert report.summary["frame_count"] == 5
    assert report.summary["zarr_shapes"] == {"U_TEST": [5, 1250]}
    assert report.temporal["median_interval_s"] == 10.0


def test_metadata_zarr_mismatch_fails(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    input_dir = ultrasound_qa_input_factory()
    frames = pd.read_parquet(input_dir / "frames.parquet").iloc[:-1]
    frames.to_parquet(input_dir / "frames.parquet", index=False)
    report = run_ultrasound_qa(
        "CELL_TEST", "EXP_TEST", input_dir, tmp_path / "artifacts", UltrasoundQAConfig()
    )
    assert report.status == "FAIL"
    assert "METADATA_ZARR_MISMATCH" in codes(report)


def test_missing_zarr_group_fails(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    input_dir = ultrasound_qa_input_factory()
    root = zarr.open_group(input_dir / "waveforms.zarr", mode="a")
    del root["U_TEST"]
    report = run_ultrasound_qa(
        "CELL_TEST", "EXP_TEST", input_dir, tmp_path / "artifacts", UltrasoundQAConfig()
    )
    assert report.status == "FAIL"
    assert "MISSING_WAVEFORM_GROUP" in codes(report)


def test_missing_required_metadata_column_fails_without_crashing(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    input_dir = ultrasound_qa_input_factory(missing_column="elapsed_time_s")
    report = run_ultrasound_qa(
        "CELL_TEST", "EXP_TEST", input_dir, tmp_path / "artifacts", UltrasoundQAConfig()
    )
    assert report.status == "FAIL"
    assert report.schema_report["missing_required_columns"] == ["elapsed_time_s"]


def test_large_gap_and_non_monotonic_elapsed_are_reported(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    _, gap = run_fixture(
        ultrasound_qa_input_factory,
        tmp_path,
        elapsed_times=[0.0, 10.0, 20.0, 60.0, 70.0],
    )
    _, backwards = run_fixture(
        ultrasound_qa_input_factory,
        tmp_path,
        elapsed_times=[0.0, 10.0, 20.0, 15.0, 30.0],
    )
    assert "LARGE_FRAME_GAP" in codes(gap)
    assert "NON_MONOTONIC_ELAPSED_TIME" in codes(backwards)

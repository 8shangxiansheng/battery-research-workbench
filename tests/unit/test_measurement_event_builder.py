from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.multimodal.builder import build_measurement_events
from battery_workbench.multimodal.schemas import MeasurementEventConfig


def _aligned(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _aligned_row(idx: int, status: str, locator=None, err: float = 0.03) -> dict:
    base = {
        "battery_id": "CELL_X",
        "experiment_id": "EXP_X",
        "ultrasound_asset_id": "U001",
        "frame_index_raw": idx,
        "event_order_index": idx,
        "source_file": "u.txt",
        "source_line_index": idx + 1,
        "waveform_group": "U001/waveform",
        "waveform_row_index": idx,
        "provisional_absolute_timestamp": datetime(2024, 1, 6, 10, 0, 0, 300000),
        "elapsed_time_s": 0.3,
        "timezone_known": False,
        "timezone_name": None,
        "match_status": status,
        "sync_error_s": err,
        "within_tolerance": status == "MATCHED_UNIQUE",
        "candidate_timestamp_count": 1,
        "candidate_record_count": 1,
        "sync_ambiguous": status == "MATCHED_AMBIGUOUS",
        "ambiguity_type": "DUPLICATE_ELECTRICAL_TIMESTAMP"
        if status == "MATCHED_AMBIGUOUS"
        else "NONE",
        "boundary_flag": False,
        "boundary_reason": None,
        "electrical_record_locator": locator,
        "electrical_timestamp": datetime(2024, 1, 6, 10, 0, 0),
        "anchor_id": "U001-manifest",
        "anchor_status": "PROVISIONAL",
        "validated_sync": False,
    }
    return base


def _write_aligned(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _records() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_row_index": [1, 2, 3],
            "record_index_raw": [1, 2, 3],
            "electrical_asset_id": ["E1"] * 3,
            "timestamp": pd.to_datetime(
                [
                    datetime(2024, 1, 6, 10, 0, 0),
                    datetime(2024, 1, 6, 10, 0, 1),
                    datetime(2024, 1, 6, 6, 0, 0),
                ]  # third row has a wildly off timestamp
            ),
            "cycle_index_raw": [1, 1, 1],
            "step_index_raw": [1, 1, 1],
            "voltage_v": [3.0, 3.1, 3.2],
            "current_a": [1.0, 0.0, 1.0],
            "capacity_ah": [0.0, 0.1, 0.0],
        }
    )


def _config() -> MeasurementEventConfig:
    return MeasurementEventConfig()


def _run(aligned_rows, output: Path):
    a = _aligned(aligned_rows)
    p = output / "aligned.parquet"
    _write_aligned(p, a)
    rp = output / "records.parquet"
    _records().to_parquet(rp, index=False)
    cp = output / "candidates.parquet"
    pd.DataFrame(_candidate_for(a)).to_parquet(cp, index=False)
    return build_measurement_events(
        aligned_frames_path=p,
        sync_candidates_path=cp,
        electrical_records_path=rp,
        output_dir=output,
        config=_config(),
    )


def _candidate_for(a: pd.DataFrame):
    rows = []
    for _, r in a.iterrows():
        if r["electrical_record_locator"] is not None:
            rows.append(
                {
                    "frame_index_raw": r["frame_index_raw"],
                    "electrical_record_locator": str(r["electrical_record_locator"]),
                    "sync_error_s": r["sync_error_s"],
                    "within_tolerance": r["within_tolerance"],
                }
            )
    return rows


def test_unique_exact_enrichment_t03(tmp_path: Path) -> None:
    _run([_aligned_row(0, "MATCHED_UNIQUE", locator="1")], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    row = out.iloc[0]
    assert row["voltage_v"] == 3.0
    assert row["current_a"] == 1.0
    assert row["event_quality_status"] == "READY"
    assert bool(row["analysis_eligible"]) is True


def test_oot_event_preserved_t07(tmp_path: Path) -> None:
    _run([_aligned_row(0, "OUT_OF_TOLERANCE", locator=None, err=5.0)], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    row = out.iloc[0]
    assert len(out) == 1
    assert row["event_quality_status"] == "OUT_OF_TOLERANCE"
    assert bool(row["analysis_eligible"]) is False
    assert row["voltage_v"] is None


def test_timestamp_unavailable_preserved_t08(tmp_path: Path) -> None:
    _run([_aligned_row(0, "TIMESTAMP_UNAVAILABLE", locator=None)], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    row = out.iloc[0]
    assert row["event_quality_status"] == "TIMESTAMP_UNAVAILABLE"
    assert bool(row["analysis_eligible"]) is False
    assert row["voltage_v"] is None


def test_sync_error_propagated_exact_t19(tmp_path: Path) -> None:
    """Upstream sync_error_s is propagated verbatim, never recomputed."""
    _run([_aligned_row(0, "MATCHED_UNIQUE", locator="1", err=0.123)], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    assert out["sync_error_s"].iloc[0] == pytest.approx(0.123)


def test_validated_sync_false_and_anchor_provisional_t11(tmp_path: Path) -> None:
    _run([_aligned_row(0, "MATCHED_UNIQUE", locator="1")], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    row = out.iloc[0]
    assert bool(row["validated_sync"]) is False
    assert row["anchor_status"] == "PROVISIONAL"
    assert bool(row["matching_performed"]) is True


def test_event_order_preserved_t14(tmp_path: Path) -> None:
    """Output order follows aligned input order (event_order_index), never sorted."""
    rows = [
        _aligned_row(0, "MATCHED_UNIQUE", locator="1"),
        _aligned_row(1, "MATCHED_UNIQUE", locator="2"),
        _aligned_row(2, "MATCHED_UNIQUE", locator="3"),
    ]
    _run(rows, tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    assert out["frame_index_raw"].tolist() == [0, 1, 2]
    assert out["measurement_event_id"].tolist() == [
        "ME::CELL_X::EXP_X::U001::0",
        "ME::CELL_X::EXP_X::U001::1",
        "ME::CELL_X::EXP_X::U001::2",
    ]


def test_no_timestamp_rematch_selects_by_locator_t15(tmp_path: Path) -> None:
    """Locator points to row 3 (off timestamp), yet row 3 is used — no nearest lookup."""
    _run([_aligned_row(0, "MATCHED_UNIQUE", locator="3")], tmp_path)
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_X" / "EXP_X" / "measurement_events.parquet"
    )
    row = out.iloc[0]
    # Row 3 has voltage 3.2 despite its timestamp being 4h away; locator wins.
    assert row["voltage_v"] == 3.2
    assert row["electrical_row_index"] == 3

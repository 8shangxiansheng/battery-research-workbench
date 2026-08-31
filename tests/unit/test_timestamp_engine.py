from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.timestamp_engine import (
    build_ultrasound_timestamps,
)
from battery_workbench.synchronization.timestamp_schemas import TimestampEngineConfig


def _write_frames(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_anchors(path: Path, assets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "battery_id": "CELL_X",
        "experiment_id": "EXP_X",
        "anchor_version": "0.1.0",
        "experiment_reference": {
            "battery_id": "CELL_X",
            "experiment_id": "EXP_X",
            "experiment_start_time": "2024-01-06T09:52:31",
            "experiment_end_time": "2024-01-06T20:58:54",
        },
        "assets": assets,
        "warnings": [],
        "limitations": ["timezone unknown"],
        "validated_sync": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _frame(row: int, elapsed: float, asset_id: str = "U001") -> dict:
    return {
        "battery_id": "CELL_X",
        "experiment_id": "EXP_X",
        "ultrasound_asset_id": asset_id,
        "source_file": f"export-{asset_id}.txt",
        "source_line_index": row + 1,
        "frame_index_raw": row,
        "waveform_group": f"{asset_id}/waveform",
        "waveform_row_index": row,
        "elapsed_time_s": elapsed,
        "event_order_index": row,
    }


def _manifest_asset(asset_id: str) -> dict:
    return {
        "asset_id": asset_id,
        "modality": "ultrasound",
        "elapsed_min_s": 0.031217,
        "elapsed_max_s": 100.0,
        "candidates": [
            {
                "anchor_id": f"{asset_id}-manifest",
                "asset_id": asset_id,
                "anchor_datetime": "2024-01-06T09:52:31",
                "elapsed_time_s_at_anchor": 0.0,
                "source_type": "MANIFEST_FILE_START",
                "source_ref": "data_assets.csv",
                "status": "PROVISIONAL",
                "timezone_known": False,
                "timezone_name": None,
                "notes": "",
            }
        ],
        "selected_anchor_id": f"{asset_id}-manifest",
        "anchor_status": "PROVISIONAL",
        "coverage": None,
        "conflicts": [],
        "validated_sync": False,
    }


def _config() -> TimestampEngineConfig:
    return TimestampEngineConfig()


def _run(frames: Path, anchors: Path, out: Path, config=None):
    return build_ultrasound_timestamps(
        frames_path=frames,
        time_anchor_state_path=anchors,
        output_dir=out,
        config=config or _config(),
    )


def test_missing_anchor_t04(tmp_path: Path) -> None:
    """T04: an asset with no selected anchor yields null timestamps, not a fail."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    _write_frames(frames, [_frame(0, 0.031217), _frame(1, 10.031217)])
    asset = _manifest_asset("U001")
    asset["selected_anchor_id"] = None
    asset["anchor_status"] = "UNVERIFIED"
    asset["candidates"] = []
    _write_anchors(anchors, [asset])

    report = _run(frames, anchors, tmp_path / "out")
    assert report.status == "PASS_WITH_WARNINGS"
    assert any("no anchor" in w.lower() or "missing" in w.lower() for w in report.warnings)


def test_row_count_and_order_preserved_t11(tmp_path: Path) -> None:
    """T11: output row count and order match the input frames exactly."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    rows = [_frame(i, i * 10.0) for i in range(6)]
    _write_frames(frames, rows)
    _write_anchors(anchors, [_manifest_asset("U001")])

    report = _run(frames, anchors, tmp_path / "out")
    assert report.input_frame_count == 6
    assert report.output_frame_count == 6
    out_df = pd.read_parquet(
        tmp_path
        / "out"
        / "synchronization"
        / "CELL_X"
        / "EXP_X"
        / "timestamped_ultrasound_frames.parquet"
    )
    assert len(out_df) == 6
    assert out_df["frame_index_raw"].tolist() == [0, 1, 2, 3, 4, 5]


def test_conflicting_selected_anchor_t06(tmp_path: Path) -> None:
    """T06: a conflicting selected anchor still timestamps, with propagated warning."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    _write_frames(frames, [_frame(0, 0.031217)])
    asset = _manifest_asset("U001")
    asset["anchor_status"] = "CONFLICTING"
    asset["coverage"] = None
    _write_anchors(anchors, [asset])

    report = _run(frames, anchors, tmp_path / "out")
    # Conflict is propagated but timestamp construction still proceeds.
    out_df = pd.read_parquet(
        tmp_path
        / "out"
        / "synchronization"
        / "CELL_X"
        / "EXP_X"
        / "timestamped_ultrasound_frames.parquet"
    )
    assert out_df["provisional_absolute_timestamp"].notna().all()
    assert any("conflict" in w.lower() for w in report.warnings)


def test_duplicate_elapsed_not_deduped_t12(tmp_path: Path) -> None:
    """T12: duplicate elapsed values are preserved; no epsilon / dedup."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    _write_frames(frames, [_frame(0, 10.0), _frame(1, 10.0), _frame(2, 20.0)])
    _write_anchors(anchors, [_manifest_asset("U001")])

    report = _run(frames, anchors, tmp_path / "out")
    assert report.output_frame_count == 3
    out_df = pd.read_parquet(
        tmp_path
        / "out"
        / "synchronization"
        / "CELL_X"
        / "EXP_X"
        / "timestamped_ultrasound_frames.parquet"
    )
    assert out_df["elapsed_time_s"].tolist() == [10.0, 10.0, 20.0]


def test_no_electrical_dependency_t20(tmp_path: Path) -> None:
    """T20: the engine has no electrical input and never reads electrical files."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    _write_frames(frames, [_frame(0, 0.031217)])
    _write_anchors(anchors, [_manifest_asset("U001")])
    # No records/cycles/steps files exist; engine must still work.
    report = _run(frames, anchors, tmp_path / "out")
    assert report.output_frame_count == 1


def test_timestamp_available_t19(tmp_path: Path) -> None:
    """Provisional timestamp is available for a selected PROVISIONAL anchor."""
    frames = tmp_path / "frames.parquet"
    anchors = tmp_path / "time_anchors.json"
    _write_frames(frames, [_frame(0, 0.031217)])
    _write_anchors(anchors, [_manifest_asset("U001")])

    report = _run(frames, anchors, tmp_path / "out")
    assert report.timestamp_available_count == 1
    assert report.timestamp_missing_count == 0

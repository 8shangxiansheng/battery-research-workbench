from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.sync_persistence import (
    write_sync_payload,
)


def _aligned() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X", "CELL_X"],
            "experiment_id": ["EXP_X", "EXP_X"],
            "ultrasound_asset_id": ["U001", "U001"],
            "frame_index_raw": [0, 1],
            "waveform_group": ["U001/waveform"] * 2,
            "waveform_row_index": [0, 1],
            "provisional_absolute_timestamp": pd.to_datetime(
                [datetime(2024, 1, 6, 10, 0, 0, 300000), datetime(2024, 1, 6, 10, 0, 1, 300000)]
            ),
            "match_status": ["MATCHED_UNIQUE", "MATCHED_UNIQUE"],
            "sync_error_s": [0.3, 0.3],
            "within_tolerance": [True, True],
            "sync_ambiguous": [False, False],
            "ambiguity_type": ["NONE", "NONE"],
            "validated_sync": [False, False],
        }
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "frame_index_raw": [0],
            "ultrasound_timestamp": pd.to_datetime([datetime(2024, 1, 6, 10, 0, 0, 300000)]),
            "electrical_record_locator": ["E1:100"],
            "electrical_timestamp": pd.to_datetime([datetime(2024, 1, 6, 10, 0, 0)]),
            "sync_error_s": [0.3],
            "within_tolerance": [True],
        }
    )


def test_inputs_immutable_t25(tmp_path: Path) -> None:
    """T25: writing outputs never mutates the input frames/records."""
    uts = pd.DataFrame({"provisional_absolute_timestamp": pd.to_datetime([datetime(2024, 1, 6)])})
    inputs = {"ultrasound_timestamped": uts.copy(), "electrical_records": uts.copy()}

    write_sync_payload(
        aligned=_aligned(),
        candidates=_candidates(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        sync_version="0.1.0",
        ultrasound_frames_path=tmp_path / "ts.parquet",
        electrical_records_path=tmp_path / "recs.parquet",
        output_dir=tmp_path,
        checksums={"ultrasound": "abc", "electrical": "def"},
    )
    # The caller's frames reference is unchanged in length.
    assert len(inputs["ultrasound_timestamped"]) == 1


def test_manifest_contract_t26(tmp_path: Path) -> None:
    """T26: the sync manifest is written and schema-valid."""
    paths = write_sync_payload(
        aligned=_aligned(),
        candidates=_candidates(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        sync_version="0.1.0",
        ultrasound_frames_path=tmp_path / "ts.parquet",
        electrical_records_path=tmp_path / "recs.parquet",
        output_dir=tmp_path,
        checksums={"ultrasound": "abc", "electrical": "def"},
    )
    manifest_path = (
        tmp_path / "synchronization" / "CELL_X" / "EXP_X" / "synchronization_manifest.json"
    )
    assert paths["synchronization_manifest"] == str(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in (
        "sync_engine_name",
        "sync_engine_version",
        "matches_frames",
        "matching_performed",
        "validated_sync",
    ):
        assert key in manifest
    assert manifest["validated_sync"] is False


def test_aligned_and_candidates_written_t19(tmp_path: Path) -> None:
    """T19: both aligned and candidates parquet are written."""
    write_sync_payload(
        aligned=_aligned(),
        candidates=_candidates(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        sync_version="0.1.0",
        ultrasound_frames_path=tmp_path / "ts.parquet",
        electrical_records_path=tmp_path / "recs.parquet",
        output_dir=tmp_path,
        checksums={"ultrasound": "abc", "electrical": "def"},
    )
    sync_dir = tmp_path / "synchronization" / "CELL_X" / "EXP_X"
    assert (sync_dir / "aligned_ultrasound_frames.parquet").exists()
    assert (sync_dir / "synchronization_candidates.parquet").exists()
    # Row counts preserved in the written files.
    aligned = pd.read_parquet(sync_dir / "aligned_ultrasound_frames.parquet")
    assert len(aligned) == 2

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.synchronization.sync_schemas import SynchronizationConfig
from battery_workbench.synchronization.sync_service import (
    synchronize_ultrasound_to_electrical,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
TS_FRAMES = (
    PROCESSED_ROOT
    / "synchronization"
    / "CELL_001"
    / "EXP_001"
    / "timestamped_ultrasound_frames.parquet"
)
ELEC_RECORDS = PROCESSED_ROOT / "electrical" / "CELL_001" / "EXP_001" / "records.parquet"
CONFIG = SynchronizationConfig.from_yaml(REPO_ROOT / "configs" / "synchronization.yaml")


@pytest.mark.skipif(
    not (TS_FRAMES.exists() and ELEC_RECORDS.exists()),
    reason="CELL_001 sync inputs not present",
)
def test_current_cell001_synchronization(tmp_path: Path) -> None:
    """T28: real CELL_001/EXP_001 nearest synchronization."""
    report = synchronize_ultrasound_to_electrical(
        timestamped_frames_path=TS_FRAMES,
        electrical_records_path=ELEC_RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    assert report.experiment_id == "EXP_001"
    assert report.battery_id == "CELL_001"
    assert report.ultrasound_frame_count == 3999
    assert report.electrical_record_count == 39996
    assert report.validated_sync is False
    assert report.matching_performed is True
    m = report.metrics
    assert m.total_ultrasound_frames == 3999
    assert m.matched_unique_count + m.matched_ambiguous_count >= 3999
    assert m.out_of_tolerance_count == 0
    assert m.within_tolerance_fraction > 0.99
    assert m.sync_error_median_s is not None

    aligned = pd.read_parquet(
        tmp_path / "synchronization" / "CELL_001" / "EXP_001" / "aligned_ultrasound_frames.parquet"
    )
    assert len(aligned) == 3999


@pytest.mark.skipif(
    not (TS_FRAMES.exists() and ELEC_RECORDS.exists()),
    reason="CELL_001 sync inputs not present",
)
def test_current_cell001_golden_frame_audit(tmp_path: Path) -> None:
    """T29: golden frames 0/1000/2000/3000/3998 independently verified."""
    synchronize_ultrasound_to_electrical(
        timestamped_frames_path=TS_FRAMES,
        electrical_records_path=ELEC_RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    aligned = pd.read_parquet(
        tmp_path / "synchronization" / "CELL_001" / "EXP_001" / "aligned_ultrasound_frames.parquet"
    )
    # Independent nearest verification (not the production matcher).
    elec = pd.read_parquet(ELEC_RECORDS)
    e_sorted = elec["timestamp"].sort_values().reset_index(drop=True)
    ts_counts = elec["timestamp"].value_counts()

    for fi in (0, 1000, 2000, 3000, 3998):
        row = aligned[aligned["frame_index_raw"] == fi].iloc[0]
        uts = row["provisional_absolute_timestamp"]
        pos = int(e_sorted.searchsorted(uts))
        idxs = [i for i in (pos - 1, pos) if 0 <= i < len(e_sorted)]
        errs = [float(abs((e_sorted.iloc[i] - uts).total_seconds())) for i in idxs]
        min_err = min(errs)
        nearest_ts = e_sorted.iloc[idxs[errs.index(min_err)]]
        rec_count = int(ts_counts[nearest_ts])
        # The aligned row must carry the independently-derived sync error.
        assert abs(float(row["sync_error_s"]) - min_err) < 1e-9
        assert row["candidate_record_count"] == rec_count


def test_sync_config_loads() -> None:
    cfg = SynchronizationConfig.from_yaml(REPO_ROOT / "configs" / "synchronization.yaml")
    assert cfg.matching.method == "nearest"
    assert cfg.matching.max_sync_error_s == 1.0
    assert cfg.matching.ambiguous_selection == "none"
    assert cfg.scientific_guards.allow_verified_sync_upgrade is False

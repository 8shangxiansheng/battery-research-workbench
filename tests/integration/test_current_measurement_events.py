from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.multimodal.builder import build_measurement_events
from battery_workbench.multimodal.schemas import MeasurementEventConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"
SYNC_DIR = PROCESSED_ROOT / "synchronization" / "CELL_001" / "EXP_001"
ALIGNED = SYNC_DIR / "aligned_ultrasound_frames.parquet"
CANDIDATES = SYNC_DIR / "synchronization_candidates.parquet"
RECORDS = PROCESSED_ROOT / "electrical" / "CELL_001" / "EXP_001" / "records.parquet"
CONFIG = MeasurementEventConfig()

AMBIG = {691, 1914, 2094, 3998}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.skipif(
    not (ALIGNED.exists() and CANDIDATES.exists() and RECORDS.exists()),
    reason="CELL_001 multimodal inputs not present",
)
def test_current_real_event_count_t29(tmp_path: Path) -> None:
    """T29: canonical event count == aligned frame count (one event per frame)."""
    aligned = pd.read_parquet(ALIGNED)
    build_measurement_events(
        aligned_frames_path=ALIGNED,
        sync_candidates_path=CANDIDATES,
        electrical_records_path=RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_001" / "EXP_001" / "measurement_events.parquet"
    )
    assert len(out) == len(aligned) == 3999
    assert out["measurement_event_id"].is_unique


@pytest.mark.skipif(
    not (ALIGNED.exists() and CANDIDATES.exists() and RECORDS.exists()),
    reason="CELL_001 multimodal inputs not present",
)
def test_current_real_ambiguity_regression_t30(tmp_path: Path) -> None:
    """T30: frames 691/1914/2094/3998 remain AMBIGUOUS_SYNC, null electrical, candidate preserved."""
    aligned = pd.read_parquet(ALIGNED)
    # Snapshot candidate relation count per ambiguous frame from upstream.
    upstream_ambig = aligned[aligned["match_status"] == "MATCHED_AMBIGUOUS"][
        "frame_index_raw"
    ].tolist()
    assert set(upstream_ambig) == AMBIG

    build_measurement_events(
        aligned_frames_path=ALIGNED,
        sync_candidates_path=CANDIDATES,
        electrical_records_path=RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_001" / "EXP_001" / "measurement_events.parquet"
    )
    for fi in sorted(AMBIG):
        row = out[out["frame_index_raw"] == fi].iloc[0]
        assert row["event_quality_status"] == "AMBIGUOUS_SYNC"
        assert bool(row["analysis_eligible"]) is False
        assert row["electrical_record_locator"] is None
        assert pd.isna(row["voltage_v"])
        # Candidate relation preserved for the event.
        rel = pd.read_parquet(
            tmp_path
            / "multimodal"
            / "CELL_001"
            / "EXP_001"
            / "measurement_event_candidates.parquet"
        )
        evt_rel = rel[rel["measurement_event_id"] == row["measurement_event_id"]]
        assert len(evt_rel) == int(row["candidate_record_count"])


@pytest.mark.skipif(
    not (ALIGNED.exists() and CANDIDATES.exists() and RECORDS.exists()),
    reason="CELL_001 multimodal inputs not present",
)
def test_current_real_golden_frames_t31(tmp_path: Path) -> None:
    """T31: frames 0/1000/2000/3000 unique + 3998 ambiguous, exact join verified."""
    build_measurement_events(
        aligned_frames_path=ALIGNED,
        sync_candidates_path=CANDIDATES,
        electrical_records_path=RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path / "multimodal" / "CELL_001" / "EXP_001" / "measurement_events.parquet"
    )
    records = pd.read_parquet(RECORDS)
    for fi in (0, 1000, 2000, 3000):
        row = out[out["frame_index_raw"] == fi].iloc[0]
        assert row["event_quality_status"] == "READY"
        assert bool(row["analysis_eligible"]) is True
        locator = row["electrical_record_locator"]
        rec = records[records["source_row_index"] == int(locator)].iloc[0]
        # Exact join yields rich derived state.
        assert row["cycle_index_raw"] == rec["cycle_index_raw"]
        assert row["step_index_raw"] == rec["step_index_raw"]
        assert row["voltage_v"] == rec["voltage_v"]
        assert row["capacity_ah"] == rec["capacity_ah"]
    # Frame 3998 ambiguous.
    row3998 = out[out["frame_index_raw"] == 3998].iloc[0]
    assert row3998["event_quality_status"] == "AMBIGUOUS_SYNC"
    assert row3998["electrical_record_locator"] is None


@pytest.mark.skipif(
    not (ALIGNED.exists() and CANDIDATES.exists() and RECORDS.exists()),
    reason="CELL_001 multimodal inputs not present",
)
def test_current_real_input_immutability_t32(tmp_path: Path) -> None:
    """T32: aligned/candidates/records SHA256 unchanged after build."""
    before = {p: _sha256(p) for p in (ALIGNED, CANDIDATES, RECORDS)}
    build_measurement_events(
        aligned_frames_path=ALIGNED,
        sync_candidates_path=CANDIDATES,
        electrical_records_path=RECORDS,
        output_dir=tmp_path,
        config=CONFIG,
    )
    after = {p: _sha256(p) for p in (ALIGNED, CANDIDATES, RECORDS)}
    assert before == after


def test_manifest_and_report_contract(tmp_path: Path) -> None:
    """T27-ish: manifest/report schema in a synthetic run (no real data needed)."""
    # Minimal synthetic aligned + records to exercise persistence contract.
    aligned = pd.DataFrame(
        {
            "battery_id": ["CELL_S"],
            "experiment_id": ["EXP_S"],
            "ultrasound_asset_id": ["U001"],
            "frame_index_raw": [0],
            "event_order_index": [0],
            "waveform_group": ["U001/waveform"],
            "waveform_row_index": [0],
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"]),
            "elapsed_time_s": [0.3],
            "timezone_known": [False],
            "timezone_name": [None],
            "match_status": ["MATCHED_UNIQUE"],
            "sync_error_s": [0.03],
            "within_tolerance": [True],
            "candidate_timestamp_count": [1],
            "candidate_record_count": [1],
            "sync_ambiguous": [False],
            "ambiguity_type": ["NONE"],
            "boundary_flag": [False],
            "boundary_reason": [None],
            "electrical_record_locator": ["1"],
            "electrical_timestamp": pd.to_datetime(["2024-01-06T10:00:00"]),
            # new-schema composite selected identity (BRW-010R)
            "electrical_asset_id": ["E1"],
            "anchor_id": ["U001-manifest"],
            "anchor_status": ["PROVISIONAL"],
            "validated_sync": [False],
        }
    )
    aligned.to_parquet(tmp_path / "a.parquet", index=False)
    records = pd.DataFrame(
        {
            "source_row_index": [1],
            "record_index_raw": [1],
            "electrical_asset_id": ["E1"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
            "voltage_v": [3.0],
            "current_a": [1.0],
            "capacity_ah": [0.0],
        }
    )
    records.to_parquet(tmp_path / "r.parquet", index=False)
    pd.DataFrame().to_parquet(tmp_path / "c.parquet", index=False)

    build_measurement_events(
        aligned_frames_path=tmp_path / "a.parquet",
        sync_candidates_path=tmp_path / "c.parquet",
        electrical_records_path=tmp_path / "r.parquet",
        output_dir=tmp_path,
        config=CONFIG,
    )
    manifest = tmp_path / "multimodal" / "CELL_S" / "EXP_S" / "measurement_event_manifest.json"
    assert manifest.exists()
    import json

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload.get("matching_recomputed") is False
    assert payload.get("validated_sync") is False

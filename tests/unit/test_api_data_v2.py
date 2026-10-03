"""BRW-025R API additive tests: data-quality / synchronization / measurement-events / load-demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
REAL = (REPO / "data/processed/CELL_001" if (REPO / "data/processed/multimodal").exists() else None)


@pytest.fixture()
def demo_client() -> TestClient:
    app = create_app(raw_root=REPO / "data/raw", processed_root=REPO / "data/processed")
    return TestClient(app)


def test_data_quality_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/data-quality")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["electrical"]["records"] > 0
    assert data["ultrasound"]["frames"] == 3999
    # cadence reported as cadence, NOT as fs
    assert data["ultrasound"]["sampling_rate_hz"] is None
    assert data["ultrasound"]["sampling_rate_status"] == "UNKNOWN"
    assert "not a waveform sampling rate" in data["ultrasound"]["note"]


def test_synchronization_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/synchronization")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["match_state"] == "PARTIAL"
    assert data["match_counts"]["matched_unique"] == 3995
    assert data["match_counts"]["matched_ambiguous"] == 4
    assert data["total_frames"] == 3999
    assert data["aligned_rows"] == 3999
    assert data["candidate_matched_frames"] == 3999
    assert data["time_anchors"][0]["anchor_status"] == "PROVISIONAL"
    assert data["time_anchors"][0]["timezone_known"] is False
    assert len(data["electrical_assets"]) == 1
    assert data["electrical_assets"][0]["electrical_asset_id"] == "E001"
    assert data["electrical_assets"][0]["timestamp_representation"] == "NAIVE"
    assert data["electrical_assets"][0]["timezone_known"] is False
    assert data["electrical_assets"][0]["source_files"] == [
        "batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
    ]
    assert data["electrical_coverage_overlaps"] == []
    assert data["validated_sync"] is False  # provisional never promoted
    assert data["timebase_status"] == "PROVISIONAL"


def test_synchronization_conflicting_anchor_blocks_apparent_matches(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    sync_dir = tmp_path / "processed/synchronization/CELL_X/EXP_X"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        '{"matches_frames":10,"quality_metrics":{"matched_unique_count":10,'
        '"matched_ambiguous_count":0,"out_of_tolerance_count":0}}',
        encoding="utf-8",
    )
    (sync_dir / "time_anchors.json").write_text(
        '{"validated_sync":false,"assets":[{"asset_id":"U1",'
        '"anchor_status":"CONFLICTING","selected_anchor_id":"candidate-1",'
        '"elapsed_min_s":0.0,"elapsed_max_s":10.0,'
        '"candidates":[{"anchor_id":"candidate-1","anchor_datetime":"2024-01-01T00:00:00",'
        '"source_type":"MANIFEST_FILE_START","timezone_known":false}],'
        '"evidence":[{"source_type":"FILENAME_HINT","source_ref":"export-01012024.txt",'
        '"raw_value":"export-01012024.txt","parsed_value":null,"supports_candidate":false}],'
        '"conflicts":[{"source_type":"M2K_CONFIG_DATE_ACQUIS",'
        '"source_ref":"config.m2k","source_sha256":"abc","raw_value":"02-01-2024 00:00:00",'
        '"parsed_value":"2024-01-02T00:00:00","message":"time disagreement"}]}]}',
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw, processed_root=tmp_path / "processed")
    )
    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["match_state"] == "BLOCKED_TIMEBASE"
    assert data["matches_frames"] == 10  # retained as a diagnostic, not promoted
    assert data["aligned_rows"] == 10
    assert data["candidate_matched_frames"] == 10
    assert data["timebase_conflicts"] == ["U1"]
    assert data["time_anchors"][0]["conflicts"][0]["source_ref"] == "config.m2k"
    assert data["time_anchors"][0]["conflicts"][0]["parsed_value"] == "2024-01-02T00:00:00"
    assert data["time_anchors"][0]["candidates"][0]["anchor_datetime"] == "2024-01-01T00:00:00"
    assert data["time_anchors"][0]["evidence"][0]["supports_candidate"] is False
    assert data["time_anchors"][0]["evidence"][0]["parsed_value"] is None


def test_synchronization_legacy_manifest_does_not_imply_unique_match(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    sync_dir = tmp_path / "processed/synchronization/CELL_X/EXP_X"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        '{"matches_frames":10}', encoding="utf-8"
    )
    (sync_dir / "time_anchors.json").write_text(
        '{"assets":[{"asset_id":"U1","anchor_status":"PROVISIONAL",'
        '"selected_anchor_id":"A1","candidates":[],"evidence":[],"conflicts":[]}]}',
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw, processed_root=tmp_path / "processed")
    )
    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["match_state"] == "UNKNOWN"
    assert data["match_counts"]["matched_unique"] is None
    assert data["time_anchors"][0]["anchor_status"] == "PROVISIONAL"


def test_synchronization_missing_anchor_blocks_even_legacy_manifest(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    sync_dir = tmp_path / "processed/synchronization/CELL_X/EXP_X"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        '{"matches_frames":10}', encoding="utf-8"
    )
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))
    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["match_state"] == "BLOCKED_TIMEBASE"
    assert data["time_anchors"] == []
    assert data["match_counts"]["matched_unique"] is None


def test_synchronization_reports_electrical_asset_time_coverage_overlap(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    sync_dir = tmp_path / "processed/synchronization/CELL_X/EXP_X"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        '{"matches_frames":1,"ultrasound_row_count":1,"quality_metrics":{'
        '"total_ultrasound_frames":1,"matched_unique_count":1,"matched_ambiguous_count":0}}',
        encoding="utf-8",
    )
    (sync_dir / "time_anchors.json").write_text(
        '{"assets":[{"asset_id":"U1","anchor_status":"PROVISIONAL",'
        '"selected_anchor_id":"A1","candidates":[],"evidence":[],"conflicts":[]}]}',
        encoding="utf-8",
    )
    records_dir = tmp_path / "processed/electrical/CELL_X/EXP_X"
    records_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "electrical_asset_id": ["E1", "E1", "E2", "E2"],
            "timestamp": pd.to_datetime(
                ["2024-01-01 00:00:00", "2024-01-01 00:00:10", "2024-01-01 00:00:05", "2024-01-01 00:00:20"]
            ),
            "source_file": ["one.xlsx", "one.xlsx", "two.xlsx", "two.xlsx"],
            "source_row_index": [1, 2, 1, 2],
        }
    ).to_parquet(records_dir / "records.parquet", index=False)
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))

    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["electrical_coverage_overlaps"] == [
        {"asset_ids": ["E1", "E2"], "overlap_seconds": 5.0, "basis": "NAIVE_WALL_CLOCK"}
    ]
    assert data["electrical_incompatible_clock_pairs"] == []
    assert data["electrical_assets"][0]["source_files"] == ["one.xlsx"]


def test_synchronization_reports_mixed_clock_asset_without_a_pair(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    sync_dir = tmp_path / "processed/synchronization/CELL_X/EXP_X"
    sync_dir.mkdir(parents=True)
    (sync_dir / "synchronization_manifest.json").write_text(
        '{"matches_frames":1,"quality_metrics":{"total_ultrasound_frames":1, '
        '"matched_unique_count":0,"matched_ambiguous_count":0}}',
        encoding="utf-8",
    )
    (sync_dir / "time_anchors.json").write_text(
        '{"assets":[{"asset_id":"U1","anchor_status":"PROVISIONAL",'
        '"selected_anchor_id":"A1","candidates":[],"evidence":[],"conflicts":[]}]}',
        encoding="utf-8",
    )
    records_dir = tmp_path / "processed/electrical/CELL_X/EXP_X"
    records_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "electrical_asset_id": ["E1", "E1"],
            "timestamp": ["2024-01-01T00:00:00", "2024-01-01T00:00:01+00:00"],
            "source_file": ["one.xlsx", "one.xlsx"],
            "source_row_index": [1, 2],
        }
    ).to_parquet(records_dir / "records.parquet", index=False)
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))

    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["electrical_mixed_clock_assets"] == ["E1"]
    assert data["electrical_assets"][0]["timestamp_representation"] == "MIXED"
    assert data["electrical_incompatible_clock_pairs"] == []


def test_measurement_events_paginated(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] >= 10
    assert len(body["data"]["events"]) == 10
    assert body["meta"]["next_cursor"] is not None
    page2 = demo_client.get(
        "/api/v1/experiments/CELL_001/EXP_001/measurement-events",
        params={"limit": 10, "cursor": body["meta"]["next_cursor"]},
    )
    assert page2.status_code == 200
    assert page2.json()["data"]["events"] != body["data"]["events"]


def test_load_demo_idempotent(demo_client: TestClient) -> None:
    resp = demo_client.post("/api/v1/experiments/CELL_001/EXP_001/load-demo")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_demo"] is True
    again = demo_client.post("/api/v1/experiments/CELL_001/EXP_001/load-demo")
    assert again.status_code == 200
    assert again.json()["data"]["is_demo"] is True


def test_load_demo_not_found(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "manifests").mkdir(parents=True)
    (raw / "manifests/experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))
    resp = client.post("/api/v1/experiments/NOPE/NOPE/load-demo")
    assert resp.status_code == 404

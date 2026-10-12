"""BRW-025R API additive tests: data-quality / synchronization / measurement-events / load-demo."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
REAL = (REPO / "data/processed/CELL_001" if (REPO / "data/processed/multimodal").exists() else None)


def _write_electrical_parser_manifest(processed_root: Path, battery_id: str, experiment_id: str) -> None:
    from battery_workbench.provenance.processed_manifest import content_sha256

    directory = processed_root / "electrical" / battery_id / experiment_id
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("cycles", "steps"):
        path = directory / f"{name}.parquet"
        if not path.exists():
            pd.DataFrame({"id": [1]}).to_parquet(path, index=False)
    outputs = {name: f"{name}.parquet" for name in ("records", "cycles", "steps")}
    (directory / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "output_files": outputs,
            "output_checksums": {
                name: content_sha256(directory / filename)
                for name, filename in outputs.items()
            },
        }),
        encoding="utf-8",
    )


@pytest.fixture()
def demo_client() -> TestClient:
    app = create_app(raw_root=REPO / "data/raw", processed_root=REPO / "data/processed")
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolate_sync_summary_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy serialization tests independent of the explicit freshness gate."""
    from battery_workbench.api.routes import data as data_routes

    monkeypatch.setattr(
        data_routes,
        "_assert_current_timebase_chain",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        data_routes,
        "_assert_processed_artifact_integrity",
        lambda _root, path, **_kwargs: json.loads(Path(path).read_text(encoding="utf-8")),
    )


def test_data_quality_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/data-quality")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["electrical"]["status"] == "AVAILABLE"
    assert data["electrical"]["records"] == 39996
    assert data["electrical"]["duplicate_timestamps"] == 12
    assert data["ultrasound"]["status"] == "AVAILABLE"
    assert data["ultrasound"]["frames"] == 3999
    # cadence reported as cadence, NOT as fs
    assert data["ultrasound"]["sampling_rate_status"] == "UNKNOWN"


def test_synchronization_blocks_tampered_parser_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import data as data_routes

    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    for modality, outputs in {
        "electrical": {"records": "records.parquet", "cycles": "cycles.parquet", "steps": "steps.parquet"},
        "ultrasound": {"frames": "frames.parquet", "waveforms": "waveforms.zarr"},
    }.items():
        directory = processed / modality / "CELL_T" / "EXP_T"
        directory.mkdir(parents=True)
        for filename in outputs.values():
            target = directory / filename
            if filename.endswith(".zarr"):
                target.mkdir()
            else:
                pd.DataFrame({"id": [1]}).to_parquet(target, index=False)
        (directory / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": "CELL_T",
                    "experiment_id": "EXP_T",
                    "output_files": outputs,
                    "output_checksums": {key: "0" * 64 for key in outputs},
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(data_routes, "invalid_parser_source_modalities", lambda *_: [])
    client = TestClient(create_app(raw_root=raw, processed_root=processed))

    response = client.get("/api/v1/experiments/CELL_T/EXP_T/synchronization")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:frames" in response.text


def test_data_quality_blocks_tampered_parser_output_only_for_affected_modality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import data as data_routes

    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    raw.mkdir()
    electrical_dir = processed / "electrical" / "CELL_A" / "EXP_A"
    ultrasound_dir = processed / "ultrasound" / "CELL_A" / "EXP_A"
    electrical_dir.mkdir(parents=True)
    ultrasound_dir.mkdir(parents=True)
    electrical_files = {
        "records": "records.parquet",
        "cycles": "cycles.parquet",
        "steps": "steps.parquet",
    }
    ultrasound_files = {"frames": "frames.parquet", "waveforms": "waveforms.zarr"}
    pd.DataFrame(
        {"timestamp": ["2024-01-01", "2024-01-02"], "cycle_index_raw": [1, 1], "step_index_raw": [1, 1]}
    ).to_parquet(electrical_dir / electrical_files["records"], index=False)
    for key, filename in electrical_files.items():
        if key != "records":
            pd.DataFrame({"id": [1]}).to_parquet(electrical_dir / filename, index=False)
    pd.DataFrame({"elapsed_time_s": [1.0, 2.0]}).to_parquet(
        ultrasound_dir / ultrasound_files["frames"], index=False
    )
    (ultrasound_dir / ultrasound_files["waveforms"]).mkdir()
    (ultrasound_dir / ultrasound_files["waveforms"] / "chunk.bin").write_bytes(b"waveform")

    def parser_manifest(directory: Path, outputs: dict[str, str]) -> dict[str, object]:
        checksums = {}
        for key, filename in outputs.items():
            path = directory / filename
            if path.is_dir():
                digest = hashlib.sha256()
                for item in sorted(path.rglob("*")):
                    if item.is_file():
                        digest.update(item.relative_to(path).as_posix().encode())
                        digest.update(item.read_bytes())
                checksums[key] = digest.hexdigest()
            else:
                checksums[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "output_files": {**outputs, "parser_manifest": "parser_manifest.json"},
            "output_checksums": checksums,
        }

    (electrical_dir / "parser_manifest.json").write_text(
        json.dumps(parser_manifest(electrical_dir, electrical_files)), encoding="utf-8"
    )
    (ultrasound_dir / "parser_manifest.json").write_text(
        json.dumps(parser_manifest(ultrasound_dir, ultrasound_files)), encoding="utf-8"
    )
    (electrical_dir / "records.parquet").write_bytes(b"tampered parquet")
    monkeypatch.setattr(data_routes, "invalid_parser_source_modalities", lambda *_: [])

    response = TestClient(create_app(raw_root=raw, processed_root=processed)).get(
        "/api/v1/experiments/CELL_A/EXP_A/data-quality"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "INTEGRITY_BLOCKED"
    assert data["electrical"]["status"] == "INTEGRITY_BLOCKED"
    assert "OUTPUT_CHECKSUM_MISMATCH:records" in data["electrical"]["integrity_reasons"]
    assert data["ultrasound"]["status"] == "AVAILABLE"
    assert data["ultrasound"]["frames"] == 2


def test_synchronization_blocks_legacy_timebase_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.integrity import assert_current_timebase_chain
    from battery_workbench.api.routes import data as data_routes

    raw = tmp_path / "raw"
    raw.mkdir()
    processed = tmp_path / "processed"
    monkeypatch.setattr(
        data_routes,
        "_assert_current_timebase_chain",
        assert_current_timebase_chain,
    )
    client = TestClient(create_app(raw_root=raw, processed_root=processed))

    response = client.get("/api/v1/experiments/CELL_A/EXP_A/synchronization")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INTEGRITY_ERROR"
    assert "TIME_ANCHOR_STATE_MISSING" in error["details"]["integrity_reasons"]
    assert (
        error["details"]["recovery_action"]
        == "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT"
    )


def test_synchronization_demo(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/synchronization")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["timebase_status"] == "PROVISIONAL"
    assert data["validated_sync"] is False
    assert data["match_counts"]["matched_unique"] == 3995
    assert data["match_counts"]["matched_ambiguous"] == 4


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


def test_synchronization_reports_electrical_asset_time_coverage_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import data as data_routes

    monkeypatch.setattr(data_routes, "invalid_parser_source_modalities", lambda *_: [])
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
    _write_electrical_parser_manifest(tmp_path / "processed", "CELL_X", "EXP_X")
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))

    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["electrical_coverage_overlaps"] == [
        {"asset_ids": ["E1", "E2"], "overlap_seconds": 5.0, "basis": "NAIVE_WALL_CLOCK"}
    ]
    assert data["electrical_incompatible_clock_pairs"] == []
    assert data["electrical_assets"][0]["source_files"] == ["one.xlsx"]


def test_synchronization_reports_mixed_clock_asset_without_a_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import data as data_routes

    monkeypatch.setattr(data_routes, "invalid_parser_source_modalities", lambda *_: [])
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
    _write_electrical_parser_manifest(tmp_path / "processed", "CELL_X", "EXP_X")
    client = TestClient(create_app(raw_root=raw, processed_root=tmp_path / "processed"))

    data = client.get("/api/v1/experiments/CELL_X/EXP_X/synchronization").json()["data"]
    assert data["electrical_mixed_clock_assets"] == ["E1"]
    assert data["electrical_assets"][0]["timestamp_representation"] == "MIXED"
    assert data["electrical_incompatible_clock_pairs"] == []


def test_measurement_events_paginated(demo_client: TestClient) -> None:
    resp = demo_client.get("/api/v1/experiments/CELL_001/EXP_001/measurement-events?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["events"]) == 10
    assert data["total"] == 3999
    assert all(event["anchor_status"] == "PROVISIONAL" for event in data["events"])


@pytest.mark.parametrize(
    ("identity_columns", "query"),
    [
        ({"measurement_event_id": ["EV::1"], "frame_index_raw": [1]}, "asset_id=U1"),
        ({"measurement_event_id": ["EV::1"], "ultrasound_asset_id": ["U1"]}, "frame_index=1"),
    ],
)
def test_measurement_event_identity_filter_fails_closed_when_column_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_columns: dict[str, list[object]],
    query: str,
) -> None:
    from battery_workbench.api.routes import data as data_routes

    processed = tmp_path / "processed"
    events_dir = processed / "multimodal/CELL_X/EXP_X"
    events_dir.mkdir(parents=True)
    (events_dir / "measurement_event_manifest.json").write_text("{}", encoding="utf-8")
    pd.DataFrame(identity_columns).to_parquet(events_dir / "measurement_events.parquet", index=False)
    monkeypatch.setattr(data_routes, "_assert_cross_modal_source_integrity", lambda *_args: None)
    client = TestClient(create_app(raw_root=tmp_path / "raw", processed_root=processed))

    response = client.get(f"/api/v1/experiments/CELL_X/EXP_X/measurement-events?{query}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "requested identity filter cannot be applied" in response.text


def test_measurement_event_identity_filter_returns_only_requested_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.api.routes import data as data_routes

    processed = tmp_path / "processed"
    events_dir = processed / "multimodal/CELL_X/EXP_X"
    events_dir.mkdir(parents=True)
    (events_dir / "measurement_event_manifest.json").write_text("{}", encoding="utf-8")
    pd.DataFrame(
        {
            "measurement_event_id": ["EV::1", "EV::2"],
            "ultrasound_asset_id": ["U1", "U2"],
            "frame_index_raw": [1, 1],
            "electrical_asset_id": ["E1", "E2"],
        }
    ).to_parquet(events_dir / "measurement_events.parquet", index=False)
    monkeypatch.setattr(data_routes, "_assert_cross_modal_source_integrity", lambda *_args: None)
    client = TestClient(create_app(raw_root=tmp_path / "raw", processed_root=processed))

    response = client.get(
        "/api/v1/experiments/CELL_X/EXP_X/measurement-events?asset_id=U2&frame_index=1"
    )

    assert response.status_code == 200
    items = response.json()["data"]["events"]
    assert [item["measurement_event_id"] for item in items] == ["EV::2"]
    assert items[0]["electrical_asset_id"] == "E2"


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

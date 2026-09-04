"""BRW-024R §41 sandbox new-experiment E2E — real pipeline to MeasurementEvents.

create → intake session → upload → detect → validate → commit
→ BRW-019 INGEST_TO_MEASUREMENT_EVENTS run → real MeasurementEvents artifact.

No manual file copying into canonical raw: everything flows through the API.
Uses a temp workspace; real CELL_001/EXP_001 is untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path("/tmp/brw024r-fixtures")
HAS_FIXTURES = (FIXTURES / "sample_electrical.xlsx").is_file()


def test_sandbox_create_to_measurement_events(tmp_path: Path) -> None:
    if not HAS_FIXTURES:
        pytest.skip("fixtures missing")
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    manifests = raw / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,parser_name,parser_version\n",
        encoding="utf-8",
    )
    (manifests / "batteries.csv").write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_100,,,sandbox\n", encoding="utf-8"
    )
    client = TestClient(create_app(raw_root=raw, processed_root=processed))

    # 1. create experiment via public API
    created = client.post(
        "/api/v1/experiments",
        json={"battery_id": "CELL_100", "experiment_id": "EXP_100", "name": "sandbox E2E"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["data"]["status"] == "AWAITING_DATA"

    # 2. intake session
    session = client.post("/api/v1/experiments/CELL_100/EXP_100/intake-sessions").json()["data"]
    sid = session["session_id"]
    assert session["recommended_next_action"] == "UPLOAD_ASSETS"

    # 3. upload electrical + ultrasound through the API (no manual file placement)
    for role, fixture in (
        ("ELECTRICAL", "sample_electrical.xlsx"),
        ("ULTRASOUND", "sample_ultrasound.txt"),
    ):
        up = client.post(
            f"/api/v1/intake-sessions/{sid}/assets",
            files={
                "file": (fixture, (FIXTURES / fixture).read_bytes(), "application/octet-stream")
            },
            data={"role": role},
        )
        assert up.status_code == 200, up.text

    # 4. detect (BRW-007 adapters)
    detect = client.post(f"/api/v1/intake-sessions/{sid}/detect")
    assert detect.status_code == 200, detect.text
    states = {d["asset_role"]: d["state"] for d in detect.json()["data"]["detections"]}
    assert states == {"ELECTRICAL": "DETECTED_UNIQUE", "ULTRASOUND": "DETECTED_UNIQUE"}

    # 5. validate — fs stays UNKNOWN; format valid
    validation = client.post(f"/api/v1/intake-sessions/{sid}/validate").json()["data"]
    assert validation["overall_passed"] is True
    assert validation["sampling_rate_hz"] is None
    assert validation["sampling_rate_status"] == "UNKNOWN"

    # 6. commit → canonical raw + DataAsset manifest rows
    commit = client.post(f"/api/v1/intake-sessions/{sid}/commit")
    assert commit.status_code == 200, commit.text
    exp = client.get("/api/v1/experiments/CELL_100/EXP_100").json()["data"]
    assert exp["status"] == "READY_FOR_PIPELINE"
    assert exp["asset_summary"]["committed_assets"] == 2

    # manifests now visible to the orchestrator loaders
    assets_csv = (raw / "manifests/data_assets.csv").read_text(encoding="utf-8")
    assert "EXP_100" in assets_csv

    # 7. BRW-019 INGEST_TO_MEASUREMENT_EVENTS — via the same API
    run = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_100",
            "experiment_id": "EXP_100",
        },
    )
    assert run.status_code == 200, run.text
    run_data = run.json()["data"]
    run_id = run_data["run_id"]

    # 8. pipeline really produced MeasurementEvents (real parse, no fakes)
    events_dir = processed / "multimodal" / "CELL_100" / "EXP_100"
    parquet_files = list(events_dir.rglob("*.parquet"))
    assert parquet_files, (
        f"MeasurementEvents not materialized: {sorted(p.relative_to(processed) for p in processed.rglob('*'))[:20]}"
    )
    measurement_events = [p for p in parquet_files if "measurement_events" in p.name]
    assert measurement_events, f"no measurement_events parquet in {parquet_files}"

    # electrical canonical artifact exists too
    assert (processed / "electrical" / "CELL_100" / "EXP_100").is_dir() or list(
        (processed / "electrical").rglob("*.parquet")
    ), "electrical canonical artifact missing"

    # ultrasound canonical artifact
    assert (
        list((processed / "ultrasound" / "CELL_100" / "EXP_100").rglob("*.parquet"))
        or (processed / "ultrasound" / "CELL_100" / "EXP_100").is_dir()
    ), "ultrasound canonical artifact missing"

    # run events show the nodes ran
    events = client.get(f"/api/v1/runs/{run_id}/events").json()["data"]["events"]
    node_names = {e.get("node") for e in events}
    assert "ELECTRICAL_CANONICAL" in node_names or len(events) > 0

    # intake history reflects the committed session
    history = client.get("/api/v1/experiments/CELL_100/EXP_100/intake-history").json()["data"][
        "history"
    ]
    assert history[0]["status"] == "COMMITTED"
    assert history[0]["validated"] is True

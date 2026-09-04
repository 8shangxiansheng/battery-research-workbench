"""BRW-025 T07/T08 backend support: waveform preview API (sample-index axis).

UI reads waveform frames only through this endpoint; no zarr access in UI.
Frames are downsampled to a bounded number of points per response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROCESSED = REPO / "data" / "processed"
has_waveforms = (PROCESSED / "ultrasound/CELL_001/EXP_001/waveforms.zarr").exists()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


def test_frame_list_metadata(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/waveform-frames")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frame_count"] > 0
    assert data["waveform_length"] == 1250
    # frame list is bounded metadata only, no waveforms
    assert len(data["frames"]) == data["frame_count"]
    for f in data["frames"][:3]:
        assert "frame_index" in f
        assert "waveform" not in f


def test_single_frame_preview_bounded(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/waveform-frames/0",
        params={"max_points": 200},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frame_index"] == 0
    assert data["waveform_length"] == 1250
    # downsampled: bounded payload, not full 1250 samples
    assert len(data["samples"]) <= 200
    assert data["x_axis"] == "SAMPLE_INDEX"  # no verified fs → sample index only
    assert "time_axis_us" not in data or data["time_axis_us"] is None


def test_preview_points_cap(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/waveform-frames/0",
        params={"max_points": 5000},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_frame_out_of_range(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/waveform-frames/99999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_runs_list_endpoint(client: TestClient, tmp_path: Path) -> None:
    # empty runs root → empty list, not error
    resp = client.get("/api/v1/runs")
    assert resp.status_code == 200
    assert resp.json()["data"]["runs"] == []


def test_runs_list_after_start(client: TestClient) -> None:
    start = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    if start.status_code != 200:
        pytest.skip("real run could not start in this environment")
    resp = client.get("/api/v1/runs")
    assert resp.status_code == 200
    runs = resp.json()["data"]["runs"]
    assert len(runs) >= 1
    assert all(r["run_id"].startswith("RUN::") for r in runs)

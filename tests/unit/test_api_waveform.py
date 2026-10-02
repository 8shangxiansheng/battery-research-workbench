"""BRW-025 T07/T08 backend support: waveform preview API (sample-index axis).

UI reads waveform frames only through this endpoint; no zarr access in UI.
Frames are downsampled to a bounded number of points per response.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr
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


def multi_asset_client(tmp_path: Path) -> TestClient:
    processed = tmp_path / "processed"
    base = processed / "ultrasound" / "CELL_TEST" / "EXP_TEST"
    base.mkdir(parents=True)
    pd.DataFrame(
        {
            "ultrasound_asset_id": ["U001", "U002"],
            "frame_index_raw": [0, 0],
            "waveform_group": ["U001/waveform", "U002/waveform"],
            "waveform_row_index": [0, 0],
            "waveform_sample_count": [4, 4],
        }
    ).to_parquet(base / "frames.parquet", index=False)
    root = zarr.open_group(str(base / "waveforms.zarr"), mode="w")
    waveform = np.sin(np.linspace(0, 30, 1250))
    root.create_array("U001/waveform", data=np.asarray([waveform], dtype=np.float32))
    root.create_array("U002/waveform", data=np.asarray([waveform * 5,], dtype=np.float32))
    app = create_app(raw_root=tmp_path / "raw", processed_root=processed, runs_root=tmp_path / "runs")
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


def test_multi_asset_frame_ids_are_listed_and_previewed_by_composite_identity(
    tmp_path: Path,
) -> None:
    client = multi_asset_client(tmp_path)
    listed = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/waveform-frames")
    assert listed.status_code == 200
    frames = listed.json()["data"]["frames"]
    assert [(frame["ultrasound_asset_id"], frame["frame_index_raw"]) for frame in frames] == [
        ("U001", 0), ("U002", 0)
    ]

    previews = [
        client.get(
            "/api/v1/experiments/CELL_TEST/EXP_TEST/waveform-frames/0",
            params={"ultrasound_asset_id": asset_id, "max_points": 4},
        )
        for asset_id in ("U001", "U002")
    ]
    assert [response.status_code for response in previews] == [200, 200]
    assert [response.json()["data"]["samples"][1]["amplitude_a_u"] for response in previews] == pytest.approx(
        [response.json()["data"]["samples"][1]["amplitude_a_u"] for response in previews[:1]]
        + [response.json()["data"]["samples"][1]["amplitude_a_u"] * 5 for response in previews[:1]]
    )
    assert [response.json()["data"]["ultrasound_asset_id"] for response in previews] == [
        "U001", "U002"
    ]

    physical = [
        client.get(
            "/api/v1/experiments/CELL_TEST/EXP_TEST/physical-features",
            params={"ultrasound_asset_id": asset_id, "frame_index_raw": 0},
        )
        for asset_id in ("U001", "U002")
    ]
    assert [response.status_code for response in physical] == [200, 200]
    bottom_amplitudes = [response.json()["data"]["features"][0]["values"][0] for response in physical]
    assert bottom_amplitudes[1] == pytest.approx(bottom_amplitudes[0] * 5)
    for response, asset_id in zip(physical, ("U001", "U002"), strict=True):
        data = response.json()["data"]
        assert data["frame_count"] == 1
        assert data["features"][0]["frame_locators"] == [
            {"ultrasound_asset_id": asset_id, "frame_index_raw": 0}
        ]


def test_ambiguous_legacy_frame_lookup_requires_asset_id(tmp_path: Path) -> None:
    client = multi_asset_client(tmp_path)
    response = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/waveform-frames/0")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_agent_waveform_inspection_blocks_ambiguous_local_frame(tmp_path: Path) -> None:
    from battery_workbench.agent_tools.gateway import ToolGateway
    from battery_workbench.agent_tools.models import AgentScientificContext

    processed = tmp_path / "processed"
    base = processed / "ultrasound" / "CELL_TEST" / "EXP_TEST"
    base.mkdir(parents=True)
    pd.DataFrame(
        {
            "ultrasound_asset_id": ["U001", "U002"],
            "frame_index_raw": [0, 0],
            "waveform_group": ["U001/waveform", "U002/waveform"],
            "waveform_row_index": [0, 0],
        }
    ).to_parquet(base / "frames.parquet", index=False)
    root = zarr.open_group(str(base / "waveforms.zarr"), mode="w")
    root.create_array("U001/waveform", data=np.array([[1.0, 2.0]], dtype=np.float32))
    root.create_array("U002/waveform", data=np.array([[3.0, 4.0]], dtype=np.float32))

    service = create_app(
        raw_root=tmp_path / "raw", processed_root=processed, runs_root=tmp_path / "runs"
    ).state.workbench_service
    gateway = ToolGateway(service=service)
    context = AgentScientificContext(battery_id="CELL_TEST", experiment_id="EXP_TEST")
    result = gateway._tool_inspect_waveform_frame(context, {"frame_index": 0})

    assert result.status == "BLOCKED"
    assert result.error["code"] == "AMBIGUOUS_FRAME_IDENTITY"


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

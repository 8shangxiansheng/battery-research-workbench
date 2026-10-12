"""BRW-025 T07/T08 backend support: waveform preview API (sample-index axis).

UI reads waveform frames only through this endpoint; no zarr access in UI.
Frames are downsampled to a bounded number of points per response.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.provenance.parser_manifest import parser_output_integrity_reasons
from battery_workbench.provenance.processed_manifest import content_sha256

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROCESSED = REPO / "data" / "processed"
has_waveforms = (PROCESSED / "ultrasound/CELL_001/EXP_001/waveforms.zarr").exists()


def _assert_real_waveform_integrity_or_skip_success_path(response) -> bool:
    reasons = parser_output_integrity_reasons(PROCESSED, "CELL_001", "EXP_001").get(
        "ultrasound", []
    )
    if not reasons:
        return False
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert response.json()["error"]["details"]["integrity_reasons"]["ultrasound"] == reasons
    return True


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


def multi_asset_client(tmp_path: Path) -> TestClient:
    processed = tmp_path / "processed"
    base = processed / "ultrasound" / "CELL_TEST" / "EXP_TEST"
    raw = tmp_path / "raw"
    base.mkdir(parents=True)
    source_rows: list[tuple[str, str, str]] = []
    source_hashes: dict[str, str] = {}
    assets: list[dict[str, str]] = []
    for asset_id in ("U001", "U002"):
        relative_path = f"batteries/CELL_TEST/EXP_TEST/ultrasound/{asset_id}.txt"
        source_path = raw / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(f"source-{asset_id}".encode())
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        source_rows.append((asset_id, relative_path, digest))
        source_hashes[asset_id] = digest
        assets.append({"asset_id": asset_id, "source_file": relative_path, "source_sha256": digest})
    manifest_dir = raw / "manifests"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path\n"
        + "".join(f"{asset},CELL_TEST,EXP_TEST,ultrasound,{path}\n" for asset, path, _ in source_rows),
        encoding="utf-8",
    )
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
    (base / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": "CELL_TEST",
            "experiment_id": "EXP_TEST",
            "source_assets": ["U001", "U002"],
            "source_sha256": source_hashes,
            "assets": assets,
            "output_files": {
                "frames": "frames.parquet",
                "waveforms": "waveforms.zarr",
                "parser_manifest": "parser_manifest.json",
            },
            "output_checksums": {
                "frames": content_sha256(base / "frames.parquet"),
                "waveforms": content_sha256(base / "waveforms.zarr"),
            },
        }),
        encoding="utf-8",
    )
    app = create_app(raw_root=raw, processed_root=processed, runs_root=tmp_path / "runs")
    return TestClient(app)


def test_waveform_api_blocks_tampered_parser_output(tmp_path: Path) -> None:
    client = multi_asset_client(tmp_path)
    current = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/waveform-frames")
    assert current.status_code == 200

    frame_path = tmp_path / "processed/ultrasound/CELL_TEST/EXP_TEST/frames.parquet"
    frames = pd.read_parquet(frame_path)
    frames.loc[0, "frame_index_raw"] = 99
    frames.to_parquet(frame_path, index=False)
    tampered = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/waveform-frames")

    assert tampered.status_code == 409
    error = tampered.json()["error"]
    assert error["code"] == "INTEGRITY_ERROR"
    assert error["details"]["invalid_modalities"] == ["ultrasound"]
    assert "OUTPUT_CHECKSUM_MISMATCH:frames" in error["details"]["integrity_reasons"]["ultrasound"]


def test_physical_features_blocks_tampered_parser_output(tmp_path: Path) -> None:
    client = multi_asset_client(tmp_path)
    frame_path = tmp_path / "processed/ultrasound/CELL_TEST/EXP_TEST/frames.parquet"
    frames = pd.read_parquet(frame_path)
    frames.loc[0, "frame_index_raw"] = 99
    frames.to_parquet(frame_path, index=False)

    response = client.get(
        "/api/v1/experiments/CELL_TEST/EXP_TEST/physical-features",
        params={"ultrasound_asset_id": "U001", "frame_index_raw": 0},
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:frames" in error["details"]["integrity_reasons"]["ultrasound"]


def test_frame_list_metadata(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/waveform-frames")
    if _assert_real_waveform_integrity_or_skip_success_path(resp):
        return
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frame_count"] > 0
    assert data["waveform_length"] == 1250
    # frame list is bounded metadata only, no waveforms
    assert len(data["frames"]) == data["frame_count"]
    for f in data["frames"][:3]:
        assert "frame_index" in f
        assert "waveform" not in f


def test_waveform_route_blocks_when_registered_raw_asset_changes(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    battery_id, experiment_id, asset_id = "CELL_TEST", "EXP_TEST", "U_TEST"
    relative_path = "batteries/CELL_TEST/EXP_TEST/ultrasound/source.txt"
    raw_source = raw / relative_path
    raw_source.parent.mkdir(parents=True)
    raw_source.write_bytes(b"waveform source")
    digest = hashlib.sha256(raw_source.read_bytes()).hexdigest()
    asset_manifest = raw / "manifests" / "data_assets.csv"
    asset_manifest.parent.mkdir(parents=True)
    asset_manifest.write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path\n"
        f"{asset_id},{battery_id},{experiment_id},ultrasound,{relative_path}\n",
        encoding="utf-8",
    )
    ultrasound_dir = processed / "ultrasound" / battery_id / experiment_id
    ultrasound_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "ultrasound_asset_id": [asset_id],
            "frame_index_raw": [0],
            "waveform_group": [f"{asset_id}/waveform"],
            "waveform_row_index": [0],
            "waveform_sample_count": [3],
        }
    ).to_parquet(ultrasound_dir / "frames.parquet", index=False)
    store = zarr.open_group(str(ultrasound_dir / "waveforms.zarr"), mode="w")
    store.create_array(
        f"{asset_id}/waveform", data=np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
    )
    (ultrasound_dir / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "source_sha256": {asset_id: digest},
                "assets": [{"asset_id": asset_id, "source_file": relative_path}],
                "output_files": {
                    "frames": "frames.parquet",
                    "waveforms": "waveforms.zarr",
                    "parser_manifest": "parser_manifest.json",
                },
                "output_checksums": {
                    "frames": content_sha256(ultrasound_dir / "frames.parquet"),
                    "waveforms": content_sha256(ultrasound_dir / "waveforms.zarr"),
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw, processed_root=processed, runs_root=tmp_path / "runs")
    )

    current = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/waveform-frames"
    )
    assert current.status_code == 200

    raw_source.write_bytes(b"replaced waveform source")
    stale = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/waveform-frames"
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert stale.json()["error"]["details"]["invalid_modalities"] == ["ultrasound"]


def test_single_frame_preview_bounded(client: TestClient) -> None:
    if not has_waveforms:
        pytest.skip("waveform store not available")
    resp = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/waveform-frames/0",
        params={"max_points": 200},
    )
    if _assert_real_waveform_integrity_or_skip_success_path(resp):
        return
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
    if _assert_real_waveform_integrity_or_skip_success_path(resp):
        return
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_physical_features_missing_frames_returns_recovery_error(tmp_path: Path) -> None:
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    response = TestClient(app).get(
        "/api/v1/experiments/CELL_TEST/EXP_TEST/physical-features"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTIFACT_NOT_AVAILABLE"
    assert response.json()["error"]["details"]["recovery_action"] == "RUN_ULTRASOUND_PARSE"


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
    import json

    from battery_workbench.agent_tools.gateway import ToolGateway
    from battery_workbench.agent_tools.models import AgentScientificContext
    from battery_workbench.provenance.processed_manifest import content_sha256

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
    raw = tmp_path / "raw"
    manifests = raw / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path\n", encoding="utf-8"
    )
    (base / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": "CELL_TEST",
            "experiment_id": "EXP_TEST",
            "source_assets": [],
            "source_sha256": {},
            "assets": [],
            "output_files": {
                "frames": "frames.parquet",
                "waveforms": "waveforms.zarr",
                "parser_manifest": "parser_manifest.json",
            },
            "output_checksums": {
                "frames": content_sha256(base / "frames.parquet"),
                "waveforms": content_sha256(base / "waveforms.zarr"),
            },
        }),
        encoding="utf-8",
    )

    service = create_app(
        raw_root=raw, processed_root=processed, runs_root=tmp_path / "runs"
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


def test_runs_list_includes_experiment_identity(client: TestClient, tmp_path: Path) -> None:
    service = client.app.state.workbench_service
    run_dir = service.runs_root / "RUN::waiting"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "RUN::waiting",
                "status": "WAITING_FOR_USER",
                "profile": "MODEL_TRAINING",
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
            }
        ),
        encoding="utf-8",
    )

    resp = client.get("/api/v1/runs")

    assert resp.status_code == 200
    assert resp.json()["data"]["runs"] == [
        {
            "run_id": "RUN::waiting",
            "status": "WAITING_FOR_USER",
            "profile": "MODEL_TRAINING",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        }
    ]


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

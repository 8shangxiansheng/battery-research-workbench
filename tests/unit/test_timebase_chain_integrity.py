from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.api.app import create_app
from battery_workbench.api.errors import APIError
from battery_workbench.api.integrity import assert_current_timebase_chain
from battery_workbench.provenance.time_anchor import time_anchor_input_fingerprint


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_current_chain(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n",
        encoding="utf-8",
    )
    (manifest_root / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    sync_dir = processed_root / "synchronization/CELL_A/EXP_A"
    sync_dir.mkdir(parents=True)
    frames_path = processed_root / "ultrasound/CELL_A/EXP_A/frames.parquet"
    frames_path.parent.mkdir(parents=True)
    frames_path.write_bytes(b"frames-v1")
    state_path = sync_dir / "time_anchors.json"
    state_path.write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "anchor_version": "0.1.0",
                "timebase_validation_id": None,
                "assets": [],
            }
        ),
        encoding="utf-8",
    )
    config_path = Path(__file__).resolve().parents[2] / "configs/time_anchor.yaml"
    fingerprint = time_anchor_input_fingerprint(
        raw_root=raw_root,
        processed_root=processed_root,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        config_path=config_path,
        validation_id=None,
    )
    (sync_dir / "time_anchor_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "anchor_version": "0.1.0",
                "timebase_validation_id": None,
                "input_fingerprint": fingerprint,
                "output_checksums": {"time_anchors": _sha256(state_path)},
            }
        ),
        encoding="utf-8",
    )
    timestamped_path = sync_dir / "timestamped_ultrasound_frames.parquet"
    timestamped_path.write_bytes(b"timestamped-v1")
    (sync_dir / "timestamp_engine_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "input_paths": {
                    "frames": str(frames_path),
                    "time_anchor_state": str(state_path),
                },
                "input_checksums": {
                    "frames": _sha256(frames_path),
                    "time_anchor_state": _sha256(state_path),
                },
                "output_path": str(timestamped_path),
                "output_checksum": _sha256(timestamped_path),
            }
        ),
        encoding="utf-8",
    )
    return raw_root, processed_root, frames_path, sync_dir


def test_current_timebase_chain_passes_integrity_check(tmp_path: Path) -> None:
    raw_root, processed_root, _, _ = _write_current_chain(tmp_path)

    assert_current_timebase_chain(
        processed_root,
        raw_root,
        battery_id="CELL_A",
        experiment_id="EXP_A",
    )


def test_timebase_chain_rejects_changed_frames_source(tmp_path: Path) -> None:
    raw_root, processed_root, frames_path, _ = _write_current_chain(tmp_path)
    frames_path.write_bytes(b"frames-v2")

    with pytest.raises(APIError) as raised:
        assert_current_timebase_chain(
            processed_root,
            raw_root,
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )

    reasons = raised.value.details["integrity_reasons"]
    assert "TIME_ANCHOR_SOURCE_STALE" in reasons
    assert "TIMESTAMP_CURRENT_INPUT_MISMATCH:frames" in reasons
    assert (
        raised.value.details["recovery_action"]
        == "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT"
    )


def test_timebase_chain_rejects_legacy_anchor_without_provenance(tmp_path: Path) -> None:
    raw_root, processed_root, _, sync_dir = _write_current_chain(tmp_path)
    (sync_dir / "time_anchor_manifest.json").unlink()

    with pytest.raises(APIError) as raised:
        assert_current_timebase_chain(
            processed_root,
            raw_root,
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )

    assert "TIME_ANCHOR_MANIFEST_MISSING" in raised.value.details["integrity_reasons"]


def test_timebase_chain_rejects_timestamp_manifest_missing_required_input_hash(
    tmp_path: Path,
) -> None:
    raw_root, processed_root, _, sync_dir = _write_current_chain(tmp_path)
    timestamp_manifest_path = sync_dir / "timestamp_engine_manifest.json"
    manifest = json.loads(timestamp_manifest_path.read_text(encoding="utf-8"))
    manifest["input_checksums"].pop("time_anchor_state")
    timestamp_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(APIError) as raised:
        assert_current_timebase_chain(
            processed_root,
            raw_root,
            battery_id="CELL_A",
            experiment_id="EXP_A",
        )

    assert "INPUT_CHECKSUM_MISSING:time_anchor_state" in raised.value.details[
        "integrity_reasons"
    ]


def test_alignment_api_fails_closed_for_legacy_time_anchor(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n",
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw_root, processed_root=tmp_path / "processed")
    )

    response = client.get("/api/v1/experiments/CELL_A/EXP_A/alignment-summary")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INTEGRITY_ERROR"
    assert "TIME_ANCHOR_STATE_MISSING" in error["details"]["integrity_reasons"]
    assert (
        error["details"]["recovery_action"]
        == "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT"
    )

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.routes import data as data_routes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_electrical_parser_manifest(root: Path) -> None:
    directory = root / "electrical" / "CELL_A" / "EXP_A"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("cycles", "steps"):
        path = directory / f"{name}.parquet"
        if not path.exists():
            pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    outputs = {name: f"{name}.parquet" for name in ("records", "cycles", "steps")}
    _write_manifest(
        directory / "parser_manifest.json",
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "output_files": outputs,
            "output_checksums": {
                name: _sha256(directory / filename)
                for name, filename in outputs.items()
            },
        },
    )


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    processed.mkdir()
    raw.mkdir()
    # Isolate these tests to the derived-artifact verifier; source parser
    # and timebase-chain validators have separate coverage and are checked
    # before the derived-artifact verifier by production routes.
    monkeypatch.setattr(data_routes, "invalid_parser_source_modalities", lambda *_: [])
    monkeypatch.setattr(data_routes, "_assert_current_timebase_chain", lambda *_args, **_kwargs: None)
    app = create_app(raw_root=raw, processed_root=processed, runs_root=tmp_path / "runs")
    return TestClient(app)


def _write_sync_artifact(root: Path) -> tuple[Path, Path]:
    directory = root / "synchronization" / "CELL_A" / "EXP_A"
    directory.mkdir(parents=True)
    input_ultrasound = directory / "timestamped.parquet"
    electrical_dir = root / "electrical" / "CELL_A" / "EXP_A"
    input_electrical = electrical_dir / "records.parquet"
    electrical_dir.mkdir(parents=True)
    aligned = directory / "aligned_ultrasound_frames.parquet"
    candidates = directory / "synchronization_candidates.parquet"
    for path in (input_ultrasound, input_electrical, aligned, candidates):
        pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    cycles = electrical_dir / "cycles.parquet"
    steps = electrical_dir / "steps.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(cycles, index=False)
    pd.DataFrame({"value": [1]}).to_parquet(steps, index=False)
    _write_manifest(
        electrical_dir / "parser_manifest.json",
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "output_files": {
                "records": "records.parquet",
                "cycles": "cycles.parquet",
                "steps": "steps.parquet",
            },
            "output_checksums": {
                "records": _sha256(input_electrical),
                "cycles": _sha256(cycles),
                "steps": _sha256(steps),
            },
        },
    )
    _write_manifest(
        directory / "synchronization_manifest.json",
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "input_paths": {
                "ultrasound_timestamped": str(input_ultrasound),
                "electrical_records": str(input_electrical),
            },
            "input_checksums": {
                "ultrasound_timestamped": _sha256(input_ultrasound),
                "electrical_records": _sha256(input_electrical),
            },
            "output_paths": {"aligned": str(aligned), "candidates": str(candidates)},
            "output_checksums": {
                "aligned": _sha256(aligned),
                "candidates": _sha256(candidates),
            },
            "quality_metrics": {},
        },
    )
    _write_electrical_parser_manifest(root)
    (directory / "time_anchors.json").write_text(
        json.dumps({"assets": [], "warnings": [], "limitations": []}), encoding="utf-8"
    )
    return aligned, input_electrical


def _write_events_artifact(root: Path) -> Path:
    directory = root / "multimodal" / "CELL_A" / "EXP_A"
    directory.mkdir(parents=True)
    inputs = {
        "aligned": root / "synchronization/CELL_A/EXP_A/aligned_ultrasound_frames.parquet",
        "sync_candidates": root / "synchronization/CELL_A/EXP_A/synchronization_candidates.parquet",
        "electrical_records": root / "electrical/CELL_A/EXP_A/records.parquet",
    }
    for path in inputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    events = directory / "measurement_events.parquet"
    candidates = directory / "measurement_event_candidates.parquet"
    columns = [
        "measurement_event_id", "frame_index_raw", "timestamp",
        "provisional_absolute_timestamp", "cycle_index_raw", "step_index_raw",
        "voltage_v", "current_a", "soc_reference_percent", "step_type",
        "temperature_c", "sync_error_s", "match_status", "sync_ambiguous",
        "anchor_status", "source_file", "ultrasound_asset_id", "electrical_asset_id",
        "electrical_timestamp",
    ]
    pd.DataFrame(columns=columns).to_parquet(events, index=False)
    pd.DataFrame({"value": [1]}).to_parquet(candidates, index=False)
    _write_manifest(
        directory / "measurement_event_manifest.json",
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "input_paths": {key: str(path) for key, path in inputs.items()},
            "input_checksums": {key: _sha256(path) for key, path in inputs.items()},
            "output_paths": {"events": str(events), "candidates": str(candidates)},
            "output_checksums": {
                "events": _sha256(events),
                "candidates": _sha256(candidates),
            },
        },
    )
    _write_electrical_parser_manifest(root)
    return events


def _write_label_artifact(root: Path, events_path: Path) -> tuple[Path, Path]:
    directory = root / "labels" / "CELL_A" / "EXP_A"
    directory.mkdir(parents=True)
    input_paths = {
        "measurement_events": events_path,
        "records": root / "electrical/CELL_A/EXP_A/records.parquet",
        "cycles": root / "electrical/CELL_A/EXP_A/cycles.parquet",
        "steps": root / "electrical/CELL_A/EXP_A/steps.parquet",
    }
    for path in input_paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            pd.DataFrame({"value": [1]}).to_parquet(path, index=False)
    event_labels = directory / "event_labels.parquet"
    cycle_labels = directory / "cycle_labels.parquet"
    pd.DataFrame(
        {"measurement_event_id": pd.Series(dtype="str"), "soc_reference_percent": pd.Series(dtype="float64")}
    ).to_parquet(event_labels, index=False)
    pd.DataFrame({"cycle_index_raw": pd.Series(dtype="int64")}).to_parquet(
        cycle_labels, index=False
    )
    _write_manifest(
        directory / "label_manifest.json",
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "label_set_id": "LS::fixture",
            "input_paths": {key: str(path) for key, path in input_paths.items()},
            "input_checksums": {key: _sha256(path) for key, path in input_paths.items()},
            "output_paths": {
                "event_labels": str(event_labels),
                "cycle_labels": str(cycle_labels),
            },
            "output_checksums": {
                "event_labels": _sha256(event_labels),
                "cycle_labels": _sha256(cycle_labels),
            },
        },
    )
    return event_labels, input_paths["cycles"]


def test_synchronization_api_rejects_tampered_derived_output(
    client: TestClient, tmp_path: Path
) -> None:
    processed = tmp_path / "processed"
    aligned, _ = _write_sync_artifact(processed)
    route = "/api/v1/experiments/CELL_A/EXP_A/synchronization"

    assert client.get(route).status_code == 200
    aligned.write_bytes(b"tampered")
    response = client.get(route)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:aligned" in response.text


def test_measurement_event_api_rejects_tampered_event_table(
    client: TestClient, tmp_path: Path
) -> None:
    events = _write_events_artifact(tmp_path / "processed")
    route = "/api/v1/experiments/CELL_A/EXP_A/measurement-events"

    assert client.get(route).status_code == 200
    events.write_bytes(b"tampered")
    response = client.get(route)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:events" in response.text


def test_measurement_event_api_rejects_tampered_reference_soc_labels(
    client: TestClient, tmp_path: Path
) -> None:
    processed = tmp_path / "processed"
    _write_sync_artifact(processed)
    events = _write_events_artifact(processed)
    event_labels, _ = _write_label_artifact(processed, events)
    route = "/api/v1/experiments/CELL_A/EXP_A/measurement-events"

    assert client.get(route).status_code == 200
    event_labels.write_bytes(b"tampered")
    response = client.get(route)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:event_labels" in response.text


def test_measurement_event_api_rejects_changed_label_source(
    client: TestClient, tmp_path: Path
) -> None:
    processed = tmp_path / "processed"
    _write_sync_artifact(processed)
    events = _write_events_artifact(processed)
    _, cycles = _write_label_artifact(processed, events)
    route = "/api/v1/experiments/CELL_A/EXP_A/measurement-events"
    cycles.write_bytes(b"changed")

    response = client.get(route)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:cycles" in response.text


@pytest.mark.parametrize("input_key", ["electrical_records", "aligned"])
def test_downstream_manifest_rejects_changed_processed_input(
    client: TestClient, tmp_path: Path, input_key: str
) -> None:
    processed = tmp_path / "processed"
    if input_key == "electrical_records":
        _, changed_input = _write_sync_artifact(processed)
        route = "/api/v1/experiments/CELL_A/EXP_A/synchronization"
    else:
        _write_sync_artifact(processed)
        _write_events_artifact(processed)
        changed_input = processed / "synchronization/CELL_A/EXP_A/aligned_ultrasound_frames.parquet"
        route = "/api/v1/experiments/CELL_A/EXP_A/measurement-events"
    changed_input.write_bytes(b"changed")

    response = client.get(route)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    if input_key == "electrical_records":
        assert "OUTPUT_CHECKSUM_MISMATCH:records" in response.text
    else:
        assert "INPUT_CHECKSUM_MISMATCH" in response.text

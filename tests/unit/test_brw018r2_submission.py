"""BRW-018R2 — sampling-parameter submission service tests.

Contract: WAITING_FOR_USER → submit fs → SAVED → pending resolved → same-run
resume → readiness refresh. Idempotent replays never re-write the parameter
set; resume failure after a successful save is explicit partial success with
a Retry-Resume path that never duplicates the parameter set.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"
B, E = "CELL_001", "EXP_001"

has_real = (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet").exists()


def _sandbox(tmp_path: Path, raw_root: Path) -> Path:
    """Real measurement events + provenance (same pattern as resume tests)."""
    sandbox = tmp_path / "processed"
    events_rel = "multimodal/CELL_001/EXP_001"
    (sandbox / events_rel).mkdir(parents=True)
    src = PROCESSED / events_rel
    for name in (
        "measurement_events.parquet",
        "measurement_event_manifest.json",
        "measurement_event_candidates.parquet",
    ):
        shutil.copy(src / name, sandbox / events_rel / name)
    for rel in (
        "synchronization/CELL_001/EXP_001",
        "electrical/CELL_001/EXP_001",
        "labels/CELL_001/EXP_001",
        "ultrasound/CELL_001/EXP_001",
    ):
        (sandbox / rel).mkdir(parents=True)
        for f in (PROCESSED / rel).iterdir():
                if f.is_file():
                    shutil.copy(f, sandbox / rel / f.name)
    _write_sandbox_parser_manifests(sandbox, raw_root)
    return sandbox


def _raw_sandbox(tmp_path: Path) -> Path:
    raw_root = tmp_path / "raw"
    manifests = raw_root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    assets = []
    for asset_id, modality, filename in (
        ("E001", "electrical", "synthetic.xlsx"),
        ("U001", "ultrasound", "synthetic.txt"),
    ):
        relative_path = Path("batteries") / B / E / modality / filename
        source = raw_root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"synthetic {modality} source".encode())
        assets.append(
            {
                "asset_id": asset_id,
                "battery_id": B,
                "experiment_id": E,
                "modality": modality,
                "relative_path": relative_path.as_posix(),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    pd.DataFrame(assets).to_csv(manifests / "data_assets.csv", index=False)
    pd.DataFrame([{"battery_id": B}]).to_csv(manifests / "batteries.csv", index=False)
    pd.DataFrame([{"experiment_id": E, "battery_id": B}]).to_csv(
        manifests / "experiments.csv", index=False
    )
    return raw_root


def _write_sandbox_parser_manifests(processed_root: Path, raw_root: Path) -> None:
    """Use synthetic, source-addressable outputs independent of legacy artifacts."""
    electrical_directory = processed_root / "electrical" / B / E
    electrical_directory.mkdir(parents=True, exist_ok=True)
    electrical_outputs = {}
    for key in ("records", "cycles", "steps"):
        path = electrical_directory / f"{key}.parquet"
        if not path.exists():
            pd.DataFrame({"id": [1]}).to_parquet(path, index=False)
        electrical_outputs[key] = path
    electrical_source = raw_root / "batteries" / B / E / "electrical/synthetic.xlsx"
    (electrical_directory / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": B,
                "experiment_id": E,
                "output_files": {key: path.name for key, path in electrical_outputs.items()},
                "output_checksums": {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in electrical_outputs.items()
                },
                "source_sha256": {
                    "E001": hashlib.sha256(electrical_source.read_bytes()).hexdigest()
                },
                "source_asset_details": [
                    {
                        "asset_id": "E001",
                        "relative_path": f"batteries/{B}/{E}/electrical/synthetic.xlsx",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    directory = processed_root / "ultrasound" / B / E
    directory.mkdir(parents=True, exist_ok=True)
    frames_path = directory / "frames.parquet"
    pd.DataFrame(
        {
            "ultrasound_asset_id": ["U001"],
            "frame_index_raw": [0],
            "elapsed_time_s": [0.0],
            "waveform_group": ["waveforms"],
            "waveform_row_index": [0],
        }
    ).to_parquet(frames_path, index=False)
    waveform_path = directory / "waveforms.zarr"
    if not waveform_path.exists():
        group = zarr.open_group(str(waveform_path), mode="w")
        group.create_array("waveforms", data=np.asarray([[0.0, 1.0, 0.0]]))
    outputs = {"frames": frames_path, "waveforms": waveform_path}

    def tree_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        for item in sorted(path.rglob("*")):
            if item.is_file():
                digest.update(item.relative_to(path).as_posix().encode())
                digest.update(item.read_bytes())
        return digest.hexdigest()

    checksums = {
        key: tree_sha256(path) if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in outputs.items()
    }
    source_hash = hashlib.sha256(
        (raw_root / "batteries" / B / E / "ultrasound/synthetic.txt").read_bytes()
    ).hexdigest()
    (directory / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": B,
                "experiment_id": E,
                "output_files": {key: path.name for key, path in outputs.items()},
                "output_checksums": checksums,
                "source_sha256": {"U001": source_hash},
                "assets": [
                    {
                        "asset_id": "U001",
                        "source_file": f"batteries/{B}/{E}/ultrasound/synthetic.txt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _client(tmp_path: Path):
    from fastapi.testclient import TestClient

    raw_root = _raw_sandbox(tmp_path)
    sandbox = _sandbox(tmp_path, raw_root)
    app = create_app(
        raw_root=raw_root, processed_root=sandbox, runs_root=tmp_path / "runs"
    )
    return TestClient(app), sandbox, tmp_path / "runs"


def _start_waiting_run(client, tmp_runs: Path) -> dict:
    """Start a SCIENTIFIC_ANALYSIS PARAMETER_SET run with fs required."""
    r = client.post(
        "/api/v1/runs",
        json={
            "profile": "SCIENTIFIC_ANALYSIS",
            "battery_id": B,
            "experiment_id": E,
            "stages": ["MEASUREMENT_EVENTS", "PARAMETER_SET"],
            "parameters": {"require_sampling_rate": True},
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.skipif(not has_real, reason="real CELL_001/EXP_001 artifacts not available")
class TestSamplingParameterSubmission:
    def test_full_loop_waiting_to_resume(self, tmp_path: Path) -> None:
        client, _sandbox, tmp_runs = _client(tmp_path)
        run = _start_waiting_run(client, tmp_runs)
        assert run["status"] == "WAITING_FOR_USER"
        run_id = run["run_id"]

        # submit fs through the shared submission service (MHz in, Hz stored)
        r = client.post(
            f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission",
            json={
                "values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}},
                "source": "test:instrument-record",
                "verified": True,
                "run_id": run_id,
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["save_status"] == "SAVED"
        assert d["parameter_set_id"]
        assert d["resume_status"] == "RESUMED"
        assert d["run_id"] == run_id
        assert d["pending_action_resolved"] is True
        assert d["run_state"] in ("SUCCEEDED", "PARTIAL")

        # the SAME run resumed (no new run id) and its PS carries Hz
        got = client.get(f"/api/v1/runs/{run_id}").json()["data"]
        assert got["run_id"] == run_id
        ps_node = next(n for n in got["nodes"] if n["node_id"] == "PARAMETER_SET")
        assert ps_node["state"] in ("SUCCEEDED", "REUSED")
        eff = json.loads(
            (Path(ps_node["outputs"][0]["path"]) / "effective_parameters.json").read_text()
        )
        fs = eff["ultrasound.sampling_rate_hz"]
        assert fs["value"] == 50_000_000.0
        assert fs["unit"] == "Hz"
        assert fs["verification_status"] == "VERIFIED"

    def test_hz_and_khz_units_normalize_to_hz(self, tmp_path: Path) -> None:
        client, _sandbox, tmp_runs = _client(tmp_path)
        for unit, value, expected in (("Hz", 50_000_000, 50_000_000.0), ("kHz", 50_000, 50_000_000.0)):
            run = _start_waiting_run(client, tmp_runs)
            r = client.post(
                f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission",
                json={
                    "values": {"ultrasound.sampling_rate_hz": {"value": value, "unit": unit}},
                    "source": "test:unit-check",
                    "verified": True,
                    "run_id": run["run_id"],
                },
            )
            assert r.status_code == 200, r.text
            d = r.json()["data"]
            assert d["save_status"] == "SAVED"
            # read the persisted PS via list_parameters on the sandbox root
            listing = client.get(f"/api/v1/experiments/{B}/{E}/parameters").json()["data"]
            match = next(
                p for p in listing
                if p["parameter_set_id"] == d["parameter_set_id"]
            )
            fs = match["effective"]["ultrasound.sampling_rate_hz"]
            assert fs["value"] == expected, (unit, fs["value"])
            assert fs["unit"] == "Hz"

    def test_idempotent_replay_no_duplicate_ps(self, tmp_path: Path) -> None:
        client, _sandbox, tmp_runs = _client(tmp_path)
        run = _start_waiting_run(client, tmp_runs)
        body = {
            "values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}},
            "source": "test:idem",
            "verified": True,
            "run_id": run["run_id"],
            "submission_id": "SUB::idem0000000001",
        }
        r1 = client.post(f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission", json=body)
        assert r1.status_code == 200
        d1 = r1.json()["data"]
        assert d1["save_status"] == "SAVED"
        r2 = client.post(f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission", json=body)
        d2 = r2.json()["data"]
        assert d2["replayed"] is True
        assert d2["parameter_set_id"] == d1["parameter_set_id"]
        # exactly one parameter set was created by this submission id
        listing = client.get(f"/api/v1/experiments/{B}/{E}/parameters").json()["data"]
        fs_verified_ids = [
            p["parameter_set_id"]
            for p in listing
            if (p["effective"].get("ultrasound.sampling_rate_hz") or {}).get("value") == 50_000_000.0
        ]
        assert fs_verified_ids.count(d1["parameter_set_id"]) == 1

    def test_missing_source_rejected(self, tmp_path: Path) -> None:
        client, _sandbox, _tmp_runs = _client(tmp_path)
        r = client.post(
            f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission",
            json={"values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}}},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_partial_success_resume_failure_retry_resume(self, tmp_path: Path) -> None:
        client, _sandbox, tmp_runs = _client(tmp_path)
        run = _start_waiting_run(client, tmp_runs)
        run_id = run["run_id"]
        # sabotage the run manifest (corrupt plan) so resume fails AFTER save
        run_dir = tmp_runs / run_id.replace("RUN::", "")
        (run_dir / "analysis_plan.json").write_text("{corrupt", encoding="utf-8")
        r = client.post(
            f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission",
            json={
                "values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}},
                "source": "test:partial",
                "verified": True,
                "run_id": run_id,
            },
        )
        d = r.json()["data"]
        assert d["save_status"] == "SAVED", d
        assert d["resume_status"] == "FAILED", d
        assert d["resume_error"]
        # retry-resume also fails (plan still corrupt) but never re-writes the PS
        ps_before = d["parameter_set_id"]
        r2 = client.post(
            f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission/{d['submission_id']}/retry-resume"
        )
        assert r2.status_code in (409, 500)
        listing = client.get(f"/api/v1/experiments/{B}/{E}/parameters").json()["data"]
        assert any(p["parameter_set_id"] == ps_before for p in listing)

    def test_no_waiting_run_save_only(self, tmp_path: Path) -> None:
        client, _sandbox, _tmp_runs = _client(tmp_path)
        r = client.post(
            f"/api/v1/experiments/{B}/{E}/sampling-parameter-submission",
            json={
                "values": {"ultrasound.sampling_rate_hz": {"value": 50, "unit": "MHz"}},
                "source": "test:no-run",
                "verified": True,
            },
        )
        d = r.json()["data"]
        assert d["save_status"] == "SAVED"
        assert d["resume_status"] == "NOT_ATTEMPTED"
        assert d["run_id"] is None

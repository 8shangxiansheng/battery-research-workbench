"""BRW-018R2 — sampling-parameter submission service tests.

Contract: WAITING_FOR_USER → submit fs → SAVED → pending resolved → same-run
resume → readiness refresh. Idempotent replays never re-write the parameter
set; resume failure after a successful save is explicit partial success with
a Retry-Resume path that never duplicates the parameter set.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"
B, E = "CELL_001", "EXP_001"

has_real = (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet").exists()


def _sandbox(tmp_path: Path) -> Path:
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
    return sandbox


def _client(tmp_path: Path):
    from fastapi.testclient import TestClient

    sandbox = _sandbox(tmp_path)
    app = create_app(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
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

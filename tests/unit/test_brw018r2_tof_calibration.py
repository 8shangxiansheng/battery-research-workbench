"""BRW-018R2 — per-experiment TOF gate calibration record tests.

Contract: 24–40 target-blind frames; immutable versioned records (modified
bounds → new version linked to prior); confirmed experiment record takes
priority over SOURCE_TEMPLATE_FROZEN_V1; save failure never silently falls
back to the source template.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.features.gate_calibration import (
    SOURCE_TEMPLATE_FROZEN,
    TOFGateCalibrationRecord,
    TOFPeakDiagnostics,
    resolve_tof_gate_calibration,
    tof_calibration_fingerprint,
    tof_calibration_id_from_fingerprint,
)

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
B, E = "CELL_001", "EXP_001"


def _record(version: int, s_start: int = 59, s_end: int = 260, b_start: int = 749, b_end: int = 1200) -> TOFGateCalibrationRecord:
    diag = TOFPeakDiagnostics(
        gate_id="X", peak_global_indices=[100], peak_local_indices=[41],
        peak_amplitudes_a_u=[1.0], peak_containment_fractions=[0.9],
        edge_hit_count=0, spread_samples=0,
    )
    return TOFGateCalibrationRecord(
        gate_calibration_id="GC-TOF::test" + str(version),
        battery_id=B,
        experiment_id=E,
        calibration_frame_ids=list(range(24)),
        calibration_basis="PREDECLARED_PROTOCOL_GATE",
        surface_gate_id="TOF_SURFACE_PEAK_GATE",
        surface_start_sample=s_start,
        surface_end_sample_exclusive=s_end,
        bottom_gate_id="TOF_BOTTOM_PEAK_GATE",
        bottom_start_sample=b_start,
        bottom_end_sample_exclusive=b_end,
        surface_diagnostics=diag,
        bottom_diagnostics=diag,
        version=version,
    ).freeze(confirmed_at="test-time")


class TestTofGateCalibrationRecord:
    def test_freeze_sets_status_and_timestamp(self) -> None:
        r = _record(1)
        assert r.status == "FROZEN" and r.confirmed_at == "test-time"
        with pytest.raises(ValueError, match="already frozen"):
            r.freeze("again")

    def test_fingerprint_deterministic_and_bound_sensitive(self) -> None:
        kwargs = {
            "battery_id": B, "experiment_id": E, "frame_ids": [1, 2, 3],
            "surface_start": 59, "surface_end": 260, "bottom_start": 749, "bottom_end": 1200,
            "basis": "PREDECLARED_PROTOCOL_GATE",
        }
        f1 = tof_calibration_fingerprint(**kwargs)
        f2 = tof_calibration_fingerprint(**kwargs)
        assert f1 == f2
        changed = tof_calibration_fingerprint(**{**kwargs, "surface_start": 60})
        assert changed != f1

    def test_version_change_yields_new_id(self) -> None:
        fp = "same-identity"
        id_v1 = tof_calibration_id_from_fingerprint(fp, 1)
        id_v2 = tof_calibration_id_from_fingerprint(fp, 2)
        assert id_v1 != id_v2
        assert id_v1.startswith("GC-TOF::")


class TestResolveTofGateCalibration:
    def test_no_record_falls_back_to_source_template(self, tmp_path: Path) -> None:
        r = resolve_tof_gate_calibration(B, E, tmp_path)
        assert r["source"] == "SOURCE_TEMPLATE"
        assert r["gate_calibration_id"] == SOURCE_TEMPLATE_FROZEN
        assert (r["surface_start"], r["surface_end_exclusive"]) == (59, 260)
        assert (r["bottom_start"], r["bottom_end_exclusive"]) == (749, 1200)

    def test_confirmed_record_wins_over_template(self, tmp_path: Path) -> None:
        root = tmp_path / "gate_calibrations" / B / E
        root.mkdir(parents=True)
        rec = _record(1)
        (root / f"{rec.gate_calibration_id}.json").write_text(
            json.dumps(rec.model_dump(mode="json")), encoding="utf-8"
        )
        r = resolve_tof_gate_calibration(B, E, tmp_path)
        assert r["source"] == "EXPERIMENT_CONFIRMED"
        assert r["gate_calibration_id"] == rec.gate_calibration_id
        assert r["version"] == 1

    def test_newest_version_wins(self, tmp_path: Path) -> None:
        root = tmp_path / "gate_calibrations" / B / E
        root.mkdir(parents=True)
        for v, s in ((1, 59), (3, 61), (2, 60)):
            rec = _record(v, s_start=s)
            (root / f"{rec.gate_calibration_id}.json").write_text(
                json.dumps(rec.model_dump(mode="json")), encoding="utf-8"
            )
        r = resolve_tof_gate_calibration(B, E, tmp_path)
        assert r["version"] == 3
        assert r["surface_start"] == 61

    def test_draft_records_ignored(self, tmp_path: Path) -> None:
        root = tmp_path / "gate_calibrations" / B / E
        root.mkdir(parents=True)
        rec = _record(1)
        draft = rec.model_copy(update={"status": "DRAFT", "confirmed_at": None})
        (root / f"{draft.gate_calibration_id}.json").write_text(
            json.dumps(draft.model_dump(mode="json")), encoding="utf-8"
        )
        r = resolve_tof_gate_calibration(B, E, tmp_path)
        assert r["source"] == "SOURCE_TEMPLATE"


class TestRealExperimentPriority:
    def test_api_freeze_then_priority(self) -> None:
        """End-to-end on the real repo: freeze → resolve prefers the record."""
        if not (PROCESSED / "ultrasound/CELL_001/EXP_001/frames.parquet").exists():
            pytest.skip("real artifacts not available")
        from fastapi.testclient import TestClient

        from battery_workbench.api.serve import app

        client = TestClient(app)
        url = f"/api/v1/experiments/{B}/{E}/tof-gate-calibration"
        r1 = client.post(
            url,
            json={"surface": {"start": 59, "end": 260}, "bottom": {"start": 749, "end": 1200}},
        )
        assert r1.status_code == 200
        d1 = r1.json()["data"]
        # re-freeze identical identity → REUSED (idempotent, no version bump)
        r2 = client.post(
            url,
            json={"surface": {"start": 59, "end": 260}, "bottom": {"start": 749, "end": 1200}},
        )
        d2 = r2.json()["data"]
        assert d2["reuse_status"] == "REUSED"
        assert d2["version"] == d1["version"]
        # changed bounds → new version linked to prior
        r3 = client.post(
            url,
            json={"surface": {"start": 60, "end": 260}, "bottom": {"start": 749, "end": 1200}},
        )
        d3 = r3.json()["data"]
        assert d3["reuse_status"] == "CREATED"
        assert d3["version"] == d1["version"] + 1
        assert d3["prior_gate_calibration_id"] == d1["gate_calibration_id"]
        # resolve now prefers the confirmed record (highest version)
        res = resolve_tof_gate_calibration(B, E, PROCESSED)
        assert res["source"] == "EXPERIMENT_CONFIRMED"
        assert res["version"] == d3["version"]
        # canonical-tof endpoint reports the confirmed calibration
        rc = client.get(f"/api/v1/experiments/{B}/{E}/canonical-tof?limit=5")
        assert rc.json()["data"]["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"

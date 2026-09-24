"""Gate bound persistence: GateCalibrationRecord.gate_bounds round-trip and
resolve_gate_calibration (latest FROZEN GC record, provenance-safe reads)."""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.features.gate_calibration import (
    GateBoundPair,
    GateCalibrationRecord,
    resolve_gate_calibration,
)

B, E = "CELL_001", "EXP_001"


def _record(tmp_path: Path, cid: str, confirmed_at: str, bounds: dict[str, GateBoundPair]) -> Path:
    rec = GateCalibrationRecord(
        gate_calibration_id=cid,
        gate_template_id="SWA_SURFACE_GATE",
        battery_id=B,
        experiment_id=E,
        probe_config_id="p", acquisition_config_id="a", source_formula_id="f",
        calibration_frame_ids=[0, 1, 2],
        calibration_basis="PREDECLARED_PROTOCOL_GATE",
        start_frame=0, end_frame=2,
        gate_bounds=bounds,
        confirmed_by="user",
    ).freeze(confirmed_at=confirmed_at)
    out = tmp_path / "gate_calibrations" / B / E
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{cid}.json"
    p.write_text(json.dumps(rec.model_dump(mode="json")), encoding="utf-8")
    return p


def test_empty_bounds_roundtrip_and_resolve_none(tmp_path: Path) -> None:
    p = _record(tmp_path, "GC::aaa", "t1", {})
    loaded = json.loads(p.read_text())
    assert loaded["gate_bounds"] == {}
    assert loaded["status"] == "FROZEN"
    assert resolve_gate_calibration(B, E, tmp_path) is not None


def test_latest_frozen_record_wins_with_bounds(tmp_path: Path) -> None:
    _record(tmp_path, "GC::older", "2026-01-01", {"SWA_SURFACE_GATE": GateBoundPair(start=90, end_exclusive=200)})
    _record(tmp_path, "GC::newer", "2026-06-01", {"SWA_SURFACE_GATE": GateBoundPair(start=95, end_exclusive=205)})
    # TOF records and non-frozen files must not be picked up
    out = tmp_path / "gate_calibrations" / B / E
    (out / "GC-TOF::x.json").write_text(json.dumps({"status": "FROZEN"}))
    (out / "GC::draft.json").write_text(json.dumps({"status": "DRAFT", "confirmed_at": "2099"}))
    resolved = resolve_gate_calibration(B, E, tmp_path)
    assert resolved is not None
    assert resolved["gate_calibration_id"] == "GC::newer"
    assert resolved["gate_bounds"]["SWA_SURFACE_GATE"] == {"start": 95, "end_exclusive": 205}

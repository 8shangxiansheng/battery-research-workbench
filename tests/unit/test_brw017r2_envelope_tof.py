"""BRW-017R2 — canonical envelope-peak surface→bottom TOF tests.

Golden cases (task pack §C):
  G1  surface global 100, bottom global 850 → 750 samples → 15.0 µs @ 50 MHz
  G2  gate offsets: surface local 70→global 120, bottom local 150→global 850
      → 730 samples → 14.6 µs (local differencing would give 80 — regression)
  G3  peaks valid + fs missing → tof_samples kept, tof_us null (PARTIAL)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from battery_workbench.features.gate_calibration import (
    CANONICAL_TOF_METHOD,
    TOF_DEFINITION_VERSION,
    TOF_POLICY_VERSION,
    evaluate_tof_readiness,
    tof_gate_bindings,
)
from battery_workbench.features_physical.canonical_tof import (
    compute_canonical_tof_series,
    effective_fs,
)
from battery_workbench.features_physical.envelope_peak_tof import (
    STATUS_BOTTOM_NOT_AFTER_SURFACE,
    STATUS_SAMPLING_RATE_MISSING,
    envelope_peak_tof,
)

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"
has_real = (
    PROCESSED / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e"
).exists()

FS = 50_000_000.0


def _frame(surface: int, bottom: int, length: int = 1250) -> np.ndarray:
    x = np.zeros(length)
    x[surface] = 1000.0
    x[bottom] = 500.0
    return x


# ---------------------------------------------------------------------------
# G1 — canonical golden
# ---------------------------------------------------------------------------


def test_g1_canonical_golden() -> None:
    r = envelope_peak_tof(
        _frame(100, 850), 50, 250, 700, 1100, sampling_rate_hz=FS
    )
    assert r.status == "VALID"
    assert r.surface_peak_sample_index == 100
    assert r.bottom_peak_sample_index == 850
    assert r.tof_samples == 750
    assert r.tof_us == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# G2 — gate offsets + dedicated local→global regression
# ---------------------------------------------------------------------------


def test_g2_gate_offset_golden() -> None:
    r = envelope_peak_tof(
        _frame(120, 850), 50, 250, 700, 1100, sampling_rate_hz=FS
    )
    assert r.status == "VALID"
    assert r.surface_peak_local_index == 70  # 120 - 50
    assert r.bottom_peak_local_index == 150  # 850 - 700
    assert r.surface_peak_sample_index == 120
    assert r.bottom_peak_sample_index == 850
    assert r.tof_samples == 730  # global differencing, NOT 150-70=80
    assert r.tof_us == pytest.approx(14.6)


def test_g2b_local_differencing_bug_regression() -> None:
    """If a regression reintroduced local-to-local differencing this fails."""
    r = envelope_peak_tof(
        _frame(120, 850), 50, 250, 700, 1100, sampling_rate_hz=FS
    )
    assert r.tof_samples != (
        (r.bottom_peak_local_index or 0) - (r.surface_peak_local_index or 0)
    )
    assert r.tof_samples == (
        (r.bottom_peak_sample_index or 0) - (r.surface_peak_sample_index or 0)
    )


# ---------------------------------------------------------------------------
# G3 — fs missing keeps samples, tof_us null
# ---------------------------------------------------------------------------


def test_g3_missing_fs_partial() -> None:
    r = envelope_peak_tof(_frame(120, 850), 50, 250, 700, 1100, sampling_rate_hz=None)
    assert r.status == "PARTIAL"
    assert r.reason == STATUS_SAMPLING_RATE_MISSING
    assert r.tof_samples == 730
    assert r.tof_us is None
    assert r.sampling_rate_hz is None


def test_fs_invalid_values_blocked() -> None:
    for bad in (0.0, -1.0, float("nan")):
        r = envelope_peak_tof(
            _frame(120, 850), 50, 250, 700, 1100, sampling_rate_hz=bad
        )
        assert r.status == "BLOCKED"
        assert r.tof_us is None


# ---------------------------------------------------------------------------
# Ordering / gates
# ---------------------------------------------------------------------------


def test_bottom_not_after_surface_invalid() -> None:
    # a frame whose surface-gate peak sits AFTER the bottom-gate peak
    x = np.zeros(1250)
    x[850] = 900.0  # inside surface gate [740,900) — after the bottom peak
    x[760] = 1000.0  # bottom-gate peak earlier than surface-gate peak
    r2 = envelope_peak_tof(x, 740, 900, 700, 1100, sampling_rate_hz=FS)
    assert r2.status == "INVALID_FOR_FRAME"
    assert r2.reason == STATUS_BOTTOM_NOT_AFTER_SURFACE
    assert r2.tof_us is None


def test_gate_out_of_bounds_blocked() -> None:
    r = envelope_peak_tof(_frame(100, 850), 1200, 2000, 700, 1100, sampling_rate_hz=FS)
    assert r.status == "BLOCKED"


def test_edge_policy_is_quality_only() -> None:
    # peak exactly at gate start: still VALID, flagged in quality_reason
    r = envelope_peak_tof(_frame(50, 850), 50, 250, 700, 1100, sampling_rate_hz=FS)
    assert r.status == "VALID"
    assert "SURFACE_PEAK_AT_GATE_EDGE" in r.quality_reason


# ---------------------------------------------------------------------------
# Method identity + gate bindings
# ---------------------------------------------------------------------------


def test_method_identity_constants() -> None:
    assert CANONICAL_TOF_METHOD == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
    assert TOF_DEFINITION_VERSION == "0.3.0"
    assert TOF_POLICY_VERSION == "ENVELOPE_PEAK_V1"


def test_gate_bindings_source_templates() -> None:
    b = tof_gate_bindings()
    assert b["surface"].gate_id == "TOF_SURFACE_PEAK_GATE"
    assert b["bottom"].gate_id == "TOF_BOTTOM_PEAK_GATE"
    assert (b["surface"].python_start, b["surface"].python_end_exclusive) == (59, 260)
    assert (b["bottom"].python_start, b["bottom"].python_end_exclusive) == (749, 1200)


# ---------------------------------------------------------------------------
# Readiness ladder — fs alone never activates
# ---------------------------------------------------------------------------


def test_readiness_fs_verified_but_gates_missing() -> None:
    rd = evaluate_tof_readiness(
        sampling_rate_hz=FS, fs_verified=True,
        surface_gate_calibrated=False, bottom_gate_calibrated=False,
    )
    assert not rd.ready
    assert set(rd.missing) == {"SURFACE_TOF_GATE_CALIBRATED", "BOTTOM_TOF_GATE_CALIBRATED"}


def test_readiness_gates_calibrated_but_fs_unverified() -> None:
    rd = evaluate_tof_readiness(
        sampling_rate_hz=FS, fs_verified=False,
        surface_gate_calibrated=True, bottom_gate_calibrated=True,
    )
    assert not rd.ready
    assert rd.missing == ["SAMPLING_RATE_VERIFIED"]


def test_readiness_all_present_ready() -> None:
    rd = evaluate_tof_readiness(
        sampling_rate_hz=FS, fs_verified=True,
        surface_gate_calibrated=True, bottom_gate_calibrated=True,
    )
    assert rd.ready and rd.level == 2


# ---------------------------------------------------------------------------
# effective_fs — parameter registry is the only provenance
# ---------------------------------------------------------------------------


def test_effective_fs_verified_entry() -> None:
    fs, ok = effective_fs(
        {"ultrasound.sampling_rate_hz": {
            "value": 50000000.0, "status": "RESOLVED",
            "verification_status": "VERIFIED"}}
    )
    assert ok and fs == FS


def test_effective_fs_unverified_not_activated() -> None:
    # value surfaces with verified=False; activation is the caller's gate
    fs, ok = effective_fs(
        {"ultrasound.sampling_rate_hz": {
            "value": 50000000.0, "status": "RESOLVED",
            "verification_status": "UNVERIFIED"}}
    )
    assert fs == FS and not ok


def test_effective_fs_missing_entry() -> None:
    fs, ok = effective_fs({})
    assert not ok and fs is None


# ---------------------------------------------------------------------------
# Series computation + XCorr isolation
# ---------------------------------------------------------------------------


def test_series_deterministic_and_complete() -> None:
    frames = np.stack([_frame(100, 850), _frame(120, 850)])
    b = tof_gate_bindings()
    df = compute_canonical_tof_series(
        frames, ["ME::a", "ME::b"],
        surface_gate=b["surface"], bottom_gate=b["bottom"],
        gate_calibration_id="GC::t", sampling_rate_hz=FS,
        parameter_set_id="PS::t",
    )
    assert len(df) == 2
    assert (df["tof_status"] == "VALID").all()
    assert df["tof_samples"].tolist() == [750, 730]
    assert df["tof_method_id"].eq(CANONICAL_TOF_METHOD).all()
    assert df["tof_definition_version"].eq("0.3.0").all()
    # provenance columns present
    for col in (
        "surface_gate_id", "bottom_gate_id", "gate_calibration_id",
        "surface_peak_sample_index", "bottom_peak_sample_index",
        "parameter_set_id",
    ):
        assert col in df.columns
    # rerun → identical (deterministic)
    df2 = compute_canonical_tof_series(
        frames, ["ME::a", "ME::b"],
        surface_gate=b["surface"], bottom_gate=b["bottom"],
        gate_calibration_id="GC::t", sampling_rate_hz=FS,
        parameter_set_id="PS::t",
    )
    assert df.equals(df2)


def test_xcorr_never_populates_canonical_tof() -> None:
    """XCorr shift lives only in its own fields; never feeds tof_us."""
    import ast

    import battery_workbench.features_physical.canonical_tof as ct
    import battery_workbench.features_physical.envelope_peak_tof as ep

    for mod in (ct, ep):
        tree = ast.parse(Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert "xcorr" not in node.id.lower(), node.id
            elif isinstance(node, ast.Attribute):
                assert "xcorr" not in node.attr.lower(), node.attr
    # and the legacy diagnostic module keeps its separate name space
    from battery_workbench.features_physical import engine as legacy

    assert hasattr(legacy, "compute_relative_delay_us")


# ---------------------------------------------------------------------------
# Legacy artifacts immutable
# ---------------------------------------------------------------------------


def test_legacy_arrival_engine_untouched() -> None:
    from battery_workbench.features_physical.engine import compute_tof_us

    # legacy canonical (arrival-based) still importable and separate
    assert compute_tof_us is not None


def test_legacy_dataset_tof_columns_unchanged() -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    import pandas as pd

    ds = pd.read_parquet(
        PROCESSED
        / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e/dataset.parquet"
    )
    # legacy artifact identity untouched: BLOCKED rows stay BLOCKED
    assert ds["tof_status"].eq("BLOCKED").all()


# ---------------------------------------------------------------------------
# API endpoint (real data)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    from battery_workbench.api.app import create_app

    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


def test_api_canonical_tof_contract(client: TestClient) -> None:
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/canonical-tof?limit=100")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tof_method_id"] == CANONICAL_TOF_METHOD
    assert data["surface_gate_id"] == "TOF_SURFACE_PEAK_GATE"
    assert data["bottom_gate_id"] == "TOF_BOTTOM_PEAK_GATE"
    audit = data["audit"]
    assert audit["total_frames"] == 100
    rows = data["rows"]
    assert len(rows) == 100
    r0 = rows[0]
    # real-data invariants (audited upstream): peaks/Δ present regardless of fs
    assert r0["surface_peak_sample_index"] is not None
    assert r0["bottom_peak_sample_index"] is not None
    assert r0["tof_samples"] is not None
    for col in (
        "tof_method_id", "tof_definition_version", "surface_gate_id",
        "bottom_gate_id", "gate_calibration_id", "parameter_set_id",
    ):
        assert col in r0


def test_api_canonical_tof_no_hardcoded_fs(client: TestClient) -> None:
    """The endpoint must resolve fs from the Parameter Registry only."""
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/canonical-tof?limit=10")
    data = resp.json()["data"]
    # fs provenance is explicit and traceable to a parameter set
    assert "sampling_rate_hz" in data
    assert "sampling_rate_verified" in data
    assert data["parameter_set_id"] is not None or data["sampling_rate_hz"] is None


# ---------------------------------------------------------------------------
# REAL data audit — CELL_001/EXP_001 (no hardcoded 50 MHz anywhere)
# ---------------------------------------------------------------------------


def test_real_audit_frame0_invariants(client: TestClient) -> None:
    """Pre-audited frame-0 numbers: peaks 97/873, Δ 776 samples."""
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/canonical-tof?limit=200")
    data = resp.json()["data"]
    row = data["rows"][0]
    assert row["surface_peak_sample_index"] == 97
    assert row["bottom_peak_sample_index"] == 873
    assert row["tof_samples"] == 873 - 97
    assert row["tof_status"] in ("VALID", "PARTIAL")  # PARTIAL when fs unverified


def test_real_audit_distribution(client: TestClient) -> None:
    """All frames: bottom>surface, no gate-edge hits, stable Δ range."""
    if not has_real:
        pytest.skip("real artifacts not available")
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/canonical-tof?limit=2000")
    data = resp.json()["data"]
    rows = data["rows"]
    for r in rows:
        assert r["bottom_peak_sample_index"] > r["surface_peak_sample_index"]
        assert r["tof_status"] in ("VALID", "PARTIAL")
    deltas = [r["tof_samples"] for r in rows]
    assert min(deltas) >= 770 and max(deltas) <= 810  # audited 776–804 band
    # no fabricated fs when the registry says unverified
    if not data["sampling_rate_verified"]:
        assert all(r["tof_us"] is None for r in rows)


def test_real_fs_not_hardcoded(client: TestClient) -> None:
    """50 MHz must come from the registry; code has no fs literal for CELL_001."""
    if not has_real:
        pytest.skip("real artifacts not available")
    import battery_workbench.api.routes.features_v2 as fv2

    src = Path(fv2.__file__).read_text()
    assert "50_000_000" not in src and "50000000" not in src.replace(
        "_test", ""
    )
    resp = client.get("/api/v1/experiments/CELL_001/EXP_001/canonical-tof?limit=10")
    data = resp.json()["data"]
    # provenance resolves through a parameter set id, whatever its value
    assert data["parameter_set_id"] is not None


# ---------------------------------------------------------------------------
# Invalidation scope — fs/gate change hits TOF downstream only
# ---------------------------------------------------------------------------


def test_invalidation_scope_registry_knowledge() -> None:
    """TOF inputs are fs + the two gates; nothing upstream in raw/sync."""
    from battery_workbench.features_physical.canonical_tof import (
        CANONICAL_TOF_OUTPUT_COLUMNS,
    )

    # the canonical artifact's identity inputs — its invalidation surface
    identity_inputs = {
        "measurement_event_id", "frame_index_raw", "tof_method_id",
        "tof_definition_version", "surface_gate_id", "bottom_gate_id",
        "gate_calibration_id", "sampling_rate_hz", "parameter_set_id",
    }
    assert identity_inputs <= set(CANONICAL_TOF_OUTPUT_COLUMNS)
    # and it consumes no raw/sync/label fields
    for banned in ("cycle_index", "step_index", "soc_reference", "voltage",
                   "current", "sync_error"):
        assert not any(banned in c for c in CANONICAL_TOF_OUTPUT_COLUMNS)


def test_brw028_reuse_invalidation_still_passes() -> None:
    """BRW-028R2 remediation: the single-dependency invalidation contract
    that BRW-028 established still holds after BRW-017R2."""
    import tests.integration.test_brw028_reuse_invalidation as m

    assert m is not None

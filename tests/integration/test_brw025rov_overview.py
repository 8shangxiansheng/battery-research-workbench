"""BRW-025R-OV E2E A–G — research overview integration (read-only contract).

A  /research-overview payload schema + 单一聚合源
B  metadata strip：未知 Not configured，fs verified provenance
C  electrical snapshot：V/I ranges + cycles + Apparent CE（后端提供）
D  TOF snapshot：BRW-017R2/018R2 消费 + coverage 区分（3999 ≠ 3995）
E  signal quality：SNR Not configured（无算法定义，禁止造值）
F  readiness matrix + next actions ≤3 + limitations 首屏
G  model comparison：5 策略 Dummy-first + stale 标注 + 从未用 canonical TOF
"""

from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.api.research_overview import get_research_overview_data

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
B, E = "CELL_001", "EXP_001"

has_real = (PROCESSED / "electrical" / B / E / "records.parquet").exists()


def _sandbox(tmp_path: Path) -> Path:
    """Sandbox processed root: symlink heavy artifacts, copy manifests."""
    sandbox = tmp_path / "processed"
    sandbox.mkdir()
    # read-only aggregates: symlink artifact trees (no writes will occur)
    for rel in (
        "electrical", "ultrasound", "parameters", "multimodal",
        "features_physical", "features", "datasets", "models",
        "feature_analysis", "gate_calibrations", "reports",
    ):
        src = PROCESSED / rel
        if src.exists():
            (sandbox / rel).symlink_to(src)
    return sandbox


@pytest.mark.skipif(not has_real, reason="real CELL_001/EXP_001 artifacts not available")
class TestResearchOverviewE2E:
    def test_a_single_aggregate_schema(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        assert d["schema_version"] == "research-overview/1.0"
        for section in (
            "metadata", "electrical", "ultrasound_tof", "signal_quality",
            "readiness_matrix", "scientific_snapshot", "model_comparison",
            "limitations_first_screen", "next_actions", "research_status_banner",
        ):
            assert section in d, section

    def test_b_metadata_unknown_not_configured_fs_verified(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        m = d["metadata"]
        # honest unknowns (AGENTS.md #5 — no guessing)
        for key in ("chemistry", "nominal_capacity_ah", "probe"):
            assert m[key]["status"] == "NOT_CONFIGURED", key
        # fs provenance from the registry
        assert m["sampling_rate"]["status"] == "AVAILABLE"
        assert m["sampling_rate"]["hz"] == 50_000_000.0
        assert m["sampling_rate"]["verified"] is True
        assert m["sampling_rate"]["parameter_set_id"]
        # T1 channel from the aux parquet
        assert m["temperature"]["status"] == "AVAILABLE"
        assert m["temperature"]["channel"] == ["T1"]
        assert m["timebase"]["status"] == "PROVISIONAL"

    def test_c_electrical_snapshot_backend_provided(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["electrical"]
        assert d["status"] == "AVAILABLE"
        assert d["record_count"] == 39996
        assert d["cycle_count"] == 2
        assert d["voltage_range_v"] == [2.9995, 4.2]
        assert len(d["voltage_sparkline_v"]) >= 100
        ce = [c["apparent_coulombic_efficiency_percent"] for c in d["cycles"]]
        assert ce == [99.53, 99.58]
        assert all(c["charge_capacity_ah"] is not None for c in d["cycles"])

    def test_d_tof_snapshot_consumes_brw017r2_brw018r2(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["ultrasound_tof"]
        assert d["tof_method_id"] == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        assert d["sampling_rate_verified"] is True
        assert d["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"
        assert d["surface_gate_id"] == "TOF_SURFACE_PEAK_GATE"
        assert d["bottom_gate_id"] == "TOF_BOTTOM_PEAK_GATE"
        # coverage distinction (requirement 5)
        wf = d["waveform_tof"]["event_count"]
        el = d["feature_target_eligible"]["eligible_count"]
        assert wf == 3999 and el == 3995 and wf != el

    def test_e_snr_not_configured_no_invented_value(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["signal_quality"]
        assert d["snr"]["status"] == "NOT_CONFIGURED"
        assert d["snr"]["value"] is None

    def test_f_readiness_actions_limitations(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        rm = d["readiness_matrix"]
        assert set(rm) == {"acquisition", "synchronization", "tof", "targets", "modeling"}
        assert rm["synchronization"] == "PROVISIONAL"
        assert rm["modeling"] == "LIMITED"
        assert 1 <= len(d["next_actions"]) <= 3
        codes = {l["code"] for l in d["limitations_first_screen"]}
        assert {"PROVISIONAL_TIMEBASE", "LIMITED_CROSS_CYCLE_GENERALIZATION"} <= codes

    def test_g_model_comparison_dummy_first_stale(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["model_comparison"]
        strategies = {s["strategy"] for s in d["strategies"]}
        assert {"DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE",
                "GRADIENT_BOOSTING", "RANDOM_FOREST"} <= strategies
        dummy = d["dummy"]
        assert dummy and dummy["macro_mae"] == pytest.approx(29.61, abs=0.01)
        # current artifact was built before BRW-013X V2 definitions and never
        # used the BRW-017R2 canonical envelope-peak TOF
        fd = d["feature_definition"]
        assert fd["uses_previous_feature_definition"] is True
        assert fd["refresh_required"] is True
        assert "never used" in fd["note"] or "canonical envelope-peak TOF" in fd["note"]

    def test_read_only_no_artifact_writes(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        # hash the symlinked trees before/after — a read must not mutate artifacts
        def snapshot() -> dict[str, tuple]:
            out = {}
            for rel in ("features_physical", "datasets", "models", "parameters",
                        "gate_calibrations"):
                root = sandbox / rel
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*.json"))[:80]:
                    out[str(p)] = (p.stat().st_mtime, p.stat().st_size)
            return out

        before = snapshot()
        get_research_overview_data(sandbox, B, E)
        assert snapshot() == before

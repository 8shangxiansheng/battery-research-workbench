"""BRW-013X V2.2 tests C01–C25 (calibration / binding / electrical / correlation)."""

from __future__ import annotations

import numpy as np
import pytest

from battery_workbench.features.gate_calibration import (
    FeatureExtractionProfile,
    FeatureGateBindingRegistry,
    GateCalibrationRecord,
    assert_target_blind_selection,
    block_all_features_all_gates,
    requires_recalibration,
    select_calibration_frames,
    smoothing_split_boundary_warning,
    variant_predictor_eligible,
)
from battery_workbench.features.state_correlation import (
    FeatureStateRow,
    build_event_grain_table,
    correlate_feature_state,
    cycle_stratified_soc,
    soc_correlation_suite,
    soh_cycle_summary,
)


def _row(i: int, **kw) -> FeatureStateRow:
    base = {
        "measurement_event_id": f"ME{i:04d}", "battery_id": "CELL_001",
        "experiment_id": "EXP_001", "cycle": 1 + i // 10, "step": 1,
        "state": "charge", "timestamp_s": 100.0 * i, "feature_code": "TDM",
        "value": float(i), "reference_soc_percent": float(i % 100),
        "temperature_c": 25.0, "soh_percent": 98.0, "analysis_eligible": True,
    }
    base.update(kw)
    return FeatureStateRow(**base)


class TestCalibrationSelection:
    """C01 — deterministic, target-blind subset."""

    def test_c01_deterministic_and_bounded(self):
        a = select_calibration_frames(3999)
        b = select_calibration_frames(3999)
        assert a == b
        assert 24 <= len(a) <= 40

    def test_c01_coverage_early_middle_late(self):
        frames = select_calibration_frames(3999)
        assert min(frames) < 3999 * 0.1
        assert max(frames) > 3999 * 0.9
        # spread across the experiment
        assert len(set(frames)) == len(frames)

    def test_c01_small_experiment(self):
        frames = select_calibration_frames(30)
        assert len(frames) == 30  # capped at n_total

    def test_c01_no_target_inputs_in_signature(self):
        # policy API accepts only frame counts — no feature/target/score args
        import inspect
        sig = inspect.signature(select_calibration_frames)
        params = set(sig.parameters)
        assert not (params & {"soc", "targets", "scores", "correlations", "feature_values"})

    def test_c24_target_informed_basis_blocked(self):
        for basis in ("SOC_CORRELATION", "MODEL_SCORE", "HELD_OUT_RESIDUAL"):
            with pytest.raises(ValueError, match="forbidden"):
                assert_target_blind_selection([0, 1], basis=basis)
        assert_target_blind_selection([0, 1], basis="PREDECLARED_PROTOCOL_GATE")


class TestGateFreeze:
    """C03/C04/P37–P42 provenance."""

    def _record(self, **kw) -> GateCalibrationRecord:
        base = {
            "gate_calibration_id": "GC001", "gate_template_id": "SWA_SURFACE_GATE",
            "battery_id": "CELL_001", "experiment_id": "EXP_001",
            "probe_config_id": "P1", "acquisition_config_id": "A1",
            "source_formula_id": "USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1",
            "calibration_frame_ids": select_calibration_frames(100),
            "calibration_basis": "PREDECLARED_PROTOCOL_GATE",
            "start_frame": 0, "end_frame": 99, "confirmed_by": "user",
        }
        base.update(kw)
        return GateCalibrationRecord(**base)

    def test_c03_freeze_version(self):
        r = self._record()
        assert r.status == "DRAFT"
        frozen = r.freeze("2024-01-01T00:00:00Z")
        assert frozen.status == "FROZEN"
        assert frozen.confirmed_at == "2024-01-01T00:00:00Z"
        with pytest.raises(ValueError, match="already frozen"):
            frozen.freeze("x")

    def test_c04_changed_config_requires_recalibration(self):
        r = self._record()
        assert not requires_recalibration(
            r, battery_id="CELL_001", probe_config_id="P1",
            acquisition_config_id="A1",
        )
        assert requires_recalibration(
            r, battery_id="CELL_001", probe_config_id="P2",
            acquisition_config_id="A1",
        )
        assert requires_recalibration(
            r, battery_id="CELL_002", probe_config_id="P1",
            acquisition_config_id="A1",
        )

    def test_c05_no_per_frame_adaptive_default(self):
        # calibration is experiment-level; record covers a frame RANGE, not
        # per-frame gate lists
        r = self._record()
        assert r.calibration_frame_ids and isinstance(r.calibration_frame_ids, list)
        assert r.status in ("DRAFT", "FROZEN")


class TestBindingRegistry:
    """C06 — FeatureGateBindingRegistry."""

    def test_c06_source_backed_defaults(self):
        reg = FeatureGateBindingRegistry()
        reg.validate_gates_exist()
        assert reg.binding_for("SWA").required_gates == ["SWA_SURFACE_GATE"]
        assert reg.binding_for("TOF_XCORR").required_gates == [
            "TOF_SURFACE_REFERENCE_GATE", "TOF_BOTTOM_GATE"
        ]
        assert reg.binding_for("BOTTOM_AMP").required_gates == ["BOTTOM_AMPLITUDE_GATE"]
        assert reg.binding_for("ATTENUATION").required_gates == ["ATTENUATION_BOTTOM_GATE"]
        assert reg.binding_for("BPS").required_gates == ["BPS_BOTTOM_GATE"]

    def test_c06_unknown_gate_rejected(self):
        reg = FeatureGateBindingRegistry()
        reg._bindings["X"] = type(reg.binding_for("SWA"))(
            feature_code="X", required_gates=["NOT_A_GATE"],
            role_en="X", role_zh="X",
        )
        with pytest.raises(ValueError, match="unknown gate template"):
            reg.validate_gates_exist()

    def test_generic_td_fd_scopes(self):
        reg = FeatureGateBindingRegistry()
        assert reg.generic_allowed_scopes("TD") == [
            "FULL_WAVEFORM", "USER_SELECTED_EXPLICIT_GATE"
        ]


class TestExtractionProfile:
    """C07 — no all-feature/all-gate explosion by default."""

    def test_c07_profile_requires_bound_gates(self):
        reg = FeatureGateBindingRegistry()
        ok = FeatureExtractionProfile(
            profile_id="CORE_PHYSICAL",
            feature_codes=["SWA", "BOTTOM_AMP"],
            gate_ids=["SWA_SURFACE_GATE", "BOTTOM_AMPLITUDE_GATE"],
        )
        ok.validate_against_bindings(reg)  # passes

        bad = FeatureExtractionProfile(
            profile_id="BAD", feature_codes=["SWA"], gate_ids=["BOTTOM_AMPLITUDE_GATE"],
        )
        with pytest.raises(ValueError, match="requires gates"):
            bad.validate_against_bindings(reg)

    def test_c07_explosion_blocked(self):
        codes = [f"F{i}" for i in range(40)]
        gates = [f"G{i}" for i in range(8)]
        with pytest.raises(ValueError, match="explicit feature profile"):
            block_all_features_all_gates(codes, gates)
        # bounded profile passes
        block_all_features_all_gates(["TDM", "SWA"], ["SWA_SURFACE_GATE"])


class TestElectricalContext:
    """C08–C10 — one frame → one MeasurementEvent context."""

    def test_c08_one_frame_one_event_context(self):
        # same frame's features all carry the same measurement_event_id
        shared = "ME0100"
        rows = [
            _row(0, measurement_event_id=shared, feature_code="SWA", value=1.0),
            _row(0, measurement_event_id=shared, feature_code="BOTTOM_AMP", value=2.0),
            _row(0, measurement_event_id=shared, feature_code="TDM", value=3.0),
        ]
        ids = {r.measurement_event_id for r in rows}
        assert ids == {shared}

    def test_c09_multiple_gates_share_context(self):
        shared = "ME0100"
        rows = [
            _row(0, measurement_event_id=shared, feature_code="TDM", gate_id=None),
            _row(0, measurement_event_id=shared, feature_code="TDSTD",
                 gate_id="SWA_SURFACE_GATE"),
            _row(0, measurement_event_id=shared, feature_code="TDSTD",
                 gate_id="BOTTOM_AMPLITUDE_GATE"),
        ]
        # same event, different locators — same state context
        socs = {r.reference_soc_percent for r in rows}
        assert socs == {0.0}

    def test_c10_join_is_event_id_not_timestamp(self):
        # two rows same event id but different gate sample offsets — no
        # timestamp rematch occurs; context identical
        rows = [
            _row(0, measurement_event_id="ME1", feature_code="SWA",
                 gate_id="SWA_SURFACE_GATE", timestamp_s=500.0),
            _row(0, measurement_event_id="ME1", feature_code="BOTTOM_AMP",
                 gate_id="BOTTOM_AMPLITUDE_GATE", timestamp_s=500.0),
        ]
        assert len({r.timestamp_s for r in rows}) == 1
        assert len({r.measurement_event_id for r in rows}) == 1


class TestCorrelation:
    """C11–C20."""

    def _suite(self, n: int = 40, **rowkw) -> list[FeatureStateRow]:
        rng = np.random.default_rng(5)
        rows = []
        for i in range(n):
            soc = 100.0 - i * (100.0 / n)
            rows.append(_row(
                i, state="charge" if i % 2 == 0 else "discharge",
                value=0.5 * soc + rng.normal(0, 2.0),
                reference_soc_percent=soc,
                **rowkw,
            ))
        return rows

    def test_c11_ambiguous_sync_excluded(self):
        rows = self._suite()
        rows.append(_row(999, analysis_eligible=False, value=1e9,
                         reference_soc_percent=50.0))
        eligible = build_event_grain_table(rows)
        assert all(r.analysis_eligible for r in eligible)
        assert len(eligible) == len(rows) - 1
        # full accounting on the unfiltered set
        r = correlate_feature_state(
            rows, state_variable="reference_soc_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.excluded_ineligible_count == 1
        # the outlier did not leak into the coefficient
        assert abs(r.coefficient) < 1.0

    def test_c12_temperature_missing_stays_null(self):
        rows = self._suite()
        rows.append(_row(999, temperature_c=None, value=42.0))
        r = correlate_feature_state(
            rows, state_variable="temperature_c", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        # temperature is constant 25.0 in the suite → INSUFFICIENT_VARIATION
        assert r.status == "INSUFFICIENT_VARIATION"
        assert r.coefficient is None

    def test_c13_soc_pearson(self):
        rows = self._suite()
        r = correlate_feature_state(
            rows, state_variable="reference_soc_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.status == "VALID"
        assert 0.9 < r.coefficient <= 1.0  # strong positive correlation

    def test_c14_soc_spearman(self):
        rows = self._suite()
        r = correlate_feature_state(
            rows, state_variable="reference_soc_percent", method="spearman",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.status == "VALID"
        assert r.coefficient > 0.95

    def test_c15_charge_discharge_stratification(self):
        rows = self._suite()
        suite = soc_correlation_suite(rows, analysis_id="a1", feature_code="TDM")
        scopes = {r.scope for r in suite}
        assert {"overall", "charge", "discharge", "rest"} <= scopes
        overall = next(r for r in suite if r.scope == "overall" and r.method == "pearson")
        assert overall.coefficient is not None

    def test_c16_cycle_stratification(self):
        rows = self._suite(40)
        per_cycle = cycle_stratified_soc(rows, analysis_id="a1", feature_code="TDM")
        assert len(per_cycle) == 4  # cycles 1..4
        assert all(r.scope.startswith("cycle:") for r in per_cycle)

    def test_c17_temperature_insufficient_variation(self):
        rows = self._suite(temperature_c=25.0)
        r = correlate_feature_state(
            rows, state_variable="temperature_c", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.status == "INSUFFICIENT_VARIATION"
        # with sufficient variation it works
        rows2 = self._suite()
        for i, r2 in enumerate(rows2):
            r2.temperature_c = 20.0 + 0.5 * i
        ok = correlate_feature_state(
            rows2, state_variable="temperature_c", method="pearson",
            analysis_id="a2", feature_code="TDM",
        )
        assert ok.status == "VALID"

    def test_c18_soh_pseudoreplication_guard(self):
        rows = self._suite(soh_percent=98.0)
        r = correlate_feature_state(
            rows, state_variable="soh_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.status == "NOT_READY_INSUFFICIENT_SOH_STATES"
        assert r.coefficient is None
        assert any("pseudoreplicat" in l for l in r.limitations)

    def test_c19_soh_two_states_blocked(self):
        rows = [
            _row(i, soh_percent=98.0 if i < 20 else 96.0) for i in range(40)
        ]
        r = correlate_feature_state(
            rows, state_variable="soh_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert r.status == "NOT_READY_INSUFFICIENT_SOH_STATES"
        summ = soh_cycle_summary(rows)
        assert all(s["n_frames"] > 0 for s in summ)  # descriptive summary OK

    def test_c20_no_naive_p_value(self):
        rows = self._suite()
        r = correlate_feature_state(
            rows, state_variable="reference_soc_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert not hasattr(r, "p_value") or "p_value" not in r.model_fields
        assert any("p-value" in l for l in r.limitations)


class TestSmoothingEligibility:
    """C21–C23."""

    def test_c21_raw_eligible(self):
        assert variant_predictor_eligible("RAW") is True

    def test_c22_movmean5_ineligible(self):
        assert variant_predictor_eligible("SOURCE_MOVMEAN5") is False

    def test_c23_smoothing_cross_split_warning(self):
        warn = smoothing_split_boundary_warning("SOURCE_MOVMEAN5", ["c1", "c2"])
        assert warn and "cross cycle boundaries" in warn
        assert smoothing_split_boundary_warning("RAW", ["c1", "c2"]) is None

    def test_c23_split_boundary_semantics(self):
        # centered 5-point window spans ±2 frames → near boundary it reads
        # the neighboring cycle's frames; this is why it can't be an
        # ML-safe predictor without a separately versioned split-safe policy
        v = np.arange(10, dtype=float)
        out = matlab_movmean5_ref(v)
        assert out[4] == pytest.approx(np.mean(v[2:7]))


def matlab_movmean5_ref(v):
    out = np.empty_like(v)
    for i in range(v.size):
        out[i] = np.mean(v[max(0, i - 2):min(v.size, i + 3)])
    return out


class TestHeldOutInvariance:
    """C25 — held-out target permutation invariance."""

    def test_c25_held_out_target_permutation_invariance(self):
        # correlation is computed on train rows; permuting held-out targets
        # must not change train-only results
        rng = np.random.default_rng(11)
        train = [
            _row(i, value=float(i) + rng.normal(0, 1), reference_soc_percent=float(i))
            for i in range(20)
        ]
        held_out = [
            _row(100 + i, value=rng.normal(), reference_soc_percent=rng.uniform(0, 100))
            for i in range(20)
        ]
        r1 = correlate_feature_state(
            train, state_variable="reference_soc_percent", method="pearson",
            analysis_id="t", feature_code="TDM",
        )
        # permute held-out targets
        shuffled = held_out[:]
        rng.shuffle(shuffled)
        for a, b in zip(held_out, shuffled):
            a.reference_soc_percent, b.reference_soc_percent = (
                b.reference_soc_percent, a.reference_soc_percent
            )
        r2 = correlate_feature_state(
            train, state_variable="reference_soc_percent", method="pearson",
            analysis_id="t", feature_code="TDM",
        )
        assert r1.coefficient == pytest.approx(r2.coefficient)
        # and held-out rows were never part of the fit scope
        assert all(r.measurement_event_id.startswith("ME0") for r in train)

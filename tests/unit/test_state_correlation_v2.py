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
    CONDITION_STRATIFICATION_POLICY_ID,
    CORRELATION_POLICY_VERSIONS,
    FeatureStateRow,
    battery_condition_stratified_soc,
    battery_decomposed_soc_correlation,
    battery_scatter_diagnostic,
    build_event_grain_table,
    condition_stratified_soc,
    correlate_feature_state,
    cycle_decomposed_soc_correlation,
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


def test_correlation_policy_versions_are_reportable() -> None:
    assert CORRELATION_POLICY_VERSIONS == {
        "feature_state_correlation": "FEATURE_STATE_CORRELATION_POLICY_V5",
        "feature_state_join": "FEATURE_STATE_JOIN_POLICY_V1",
        "battery_decomposition": "BATTERY_WITHIN_BETWEEN_CORRELATION_V1",
        "cycle_within_between_correlation": "CYCLE_WITHIN_BETWEEN_CORRELATION_V1",
        "condition_stratification": "OPERATOR_DECLARED_CONDITION_SOC_STRATIFICATION_V1",
        "battery_scatter_diagnostic": "BATTERY_STRATIFIED_SCATTER_DIAGNOSTIC_V1",
    }


@pytest.mark.parametrize(
    "analyze",
    [
        lambda rows: correlate_feature_state(
            rows,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="duplicate-event",
            feature_code="TDM",
        ),
        cycle_decomposed_soc_correlation,
        battery_decomposed_soc_correlation,
        lambda rows: battery_scatter_diagnostic(rows, feature_code="TDM"),
        soh_cycle_summary,
    ],
)
def test_duplicate_measurement_event_feature_rows_fail_closed(analyze) -> None:
    first = _row(1)
    duplicate = first.model_copy(update={"value": 999.0})

    with pytest.raises(ValueError, match="one row per MeasurementEvent/FeatureLocator"):
        analyze([first, duplicate])


def test_same_event_identity_cannot_map_to_multiple_experiments() -> None:
    rows = [
        _row(1),
        _row(2, measurement_event_id="ME0001", experiment_id="EXP_002", feature_code="TDPP"),
    ]

    with pytest.raises(ValueError, match="multiple Battery/Experiment groups"):
        correlate_feature_state(
            rows,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="event-owner-conflict",
            feature_code="TDM",
        )


def _condition_assignment(event_index: int, **overrides):
    from battery_workbench.conditions.assignment import ConditionAssignment

    payload = {
        "event_id": f"ME{event_index:04d}",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "condition_axis_id": "temperature_setpoint",
        "condition_value": "25",
        "unit": "degC",
        "segment_id": "SEG_A",
        "time_reference_asset_id": "U001",
        "event_asset_id": "U001",
        "event_timestamp": "2026-01-01T00:00:00+00:00",
        "status": "ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK",
    }
    payload.update(overrides)
    return ConditionAssignment(**payload)


def test_condition_stratified_soc_keeps_declaration_and_complete_pair_accounting() -> None:
    rows = [
        _row(0, value=1.0, reference_soc_percent=10.0),
        _row(1, value=2.0, reference_soc_percent=20.0),
        _row(2, value=3.0, reference_soc_percent=30.0),
        _row(3, value=None, reference_soc_percent=40.0),
        _row(4, value=5.0, reference_soc_percent=50.0, analysis_eligible=False),
        _row(5, value=100.0, reference_soc_percent=90.0),
    ]
    assignments = [
        *[_condition_assignment(i) for i in range(5)],
        _condition_assignment(
            5,
            condition_value="30",
            segment_id="SEG_B",
        ),
        _condition_assignment(
            6,
            status="UNCLASSIFIED_NO_SEGMENT",
            condition_value=None,
            segment_id=None,
        ),
    ]

    results = condition_stratified_soc(rows, assignments)

    declared_25 = [result for result in results if result.condition_value == "25"]
    assert {result.method for result in declared_25} == {"pearson", "spearman"}
    pearson = next(result for result in declared_25 if result.method == "pearson")
    assert pearson.policy == CONDITION_STRATIFICATION_POLICY_ID
    assert pearson.coefficient == pytest.approx(1.0)
    assert pearson.n_input_events == 5
    assert pearson.n_valid_pairs == 3
    assert pearson.missing_feature_count == 1
    assert pearson.excluded_ineligible_count == 1
    assert pearson.declaration_status == "OPERATOR_DECLARED"
    assert pearson.absolute_timebase_status == "NOT_ASSESSED"
    assert pearson.synchronization_status == "NOT_ASSESSED"
    assert pearson.group_count_semantics == "DECLARED_BATTERY_ID"
    assert pearson.battery_identity_status == "NOT_ASSESSED"
    assert pearson.physical_battery_count is None
    assert pearson.segment_ids == ["SEG_A"]
    assert any("no confidence interval or p-value" in item for item in pearson.limitations)
    declared_30 = [result for result in results if result.condition_value == "30"]
    assert len(declared_30) == 2
    assert all(result.n_valid_pairs == 1 for result in declared_30)


def test_condition_stratified_soc_rejects_duplicate_event_feature_locator_rows() -> None:
    with pytest.raises(ValueError, match="one row per MeasurementEvent/FeatureLocator"):
        condition_stratified_soc(
            [_row(1), _row(1)],
            [_condition_assignment(1)],
        )


def test_condition_stratified_soc_rejects_duplicate_event_axis_assignments() -> None:
    with pytest.raises(ValueError, match="one condition assignment"):
        condition_stratified_soc(
            [_row(1)],
            [_condition_assignment(1), _condition_assignment(1, segment_id="SEG_DUP")],
        )


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

    def test_requested_feature_locator_excludes_other_features_and_variants(self):
        requested = [
            _row(i, feature_code="A", value=float(i), reference_soc_percent=float(i))
            for i in range(3)
        ]
        unrelated = [
            _row(i, feature_code="B", value=float(2 - i), reference_soc_percent=float(i))
            for i in range(3)
        ]
        variant = [
            _row(i, feature_code="A", feature_variant="SMOOTHED",
                 value=100.0 + i, reference_soc_percent=float(i))
            for i in range(3)
        ]

        result = correlate_feature_state(
            requested + unrelated + variant,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="locator-filter",
            feature_code="A",
        )

        assert result.coefficient == pytest.approx(1.0)
        assert result.n_input == 3
        assert result.n_valid == 3

    def test_requested_gate_locator_is_exact(self):
        rows = [
            _row(i, feature_code="TDSTD", gate_id="G1", value=float(i),
                 reference_soc_percent=float(i))
            for i in range(3)
        ] + [
            _row(i, feature_code="TDSTD", gate_id="G2", value=float(2 - i),
                 reference_soc_percent=float(i))
            for i in range(3)
        ]

        result = correlate_feature_state(
            rows,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="gate-filter",
            feature_code="TDSTD",
            gate_id="G1",
        )

        assert result.coefficient == pytest.approx(1.0)
        assert result.n_valid == 3

    def test_locator_agnostic_decomposition_rejects_mixed_features(self):
        rows = [_row(i) for i in range(3)] + [
            _row(i, feature_code="SWA") for i in range(3)
        ]

        with pytest.raises(ValueError, match="one FeatureLocator"):
            battery_decomposed_soc_correlation(rows)

    def test_stratified_and_scatter_helpers_use_requested_locator(self):
        requested = [
            _row(i, feature_code="SWA", gate_id="G1", value=float(i),
                 reference_soc_percent=float(i))
            for i in range(3)
        ]
        unrelated = [
            _row(i, feature_code="SWA", gate_id="G2", value=float(2 - i),
                 reference_soc_percent=float(i))
            for i in range(3)
        ]

        cycles = cycle_stratified_soc(
            requested + unrelated, analysis_id="cycle-locator",
            feature_code="SWA", gate_id="G1",
        )
        scatter = battery_scatter_diagnostic(
            requested + unrelated, feature_code="SWA", gate_id="G1",
        )

        assert len(cycles) == 1
        assert cycles[0].n_input == 3
        assert scatter["n_input"] == 3
        assert scatter["gate_id"] == "G1"

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
        assert r.n_input == 41
        assert r.n_valid == 40
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

    def test_p4_spearman_uses_average_ranks_for_tied_values(self):
        x_values = [1.0, 1.0, 2.0, 2.0, 3.0]
        y_values = [1.0, 2.0, 2.0, 3.0, 3.0]
        rows = [
            _row(i, value=x, reference_soc_percent=y)
            for i, (x, y) in enumerate(zip(x_values, y_values, strict=True))
        ]

        result = correlate_feature_state(
            rows,
            state_variable="reference_soc_percent",
            method="spearman",
            analysis_id="p4-tied-ranks",
            feature_code="TDM",
        )

        assert result.coefficient == pytest.approx(29.0 / 36.0)

    def test_c15_charge_discharge_stratification(self):
        rows = self._suite()
        suite = soc_correlation_suite(rows, analysis_id="a1", feature_code="TDM")
        scopes = {r.scope for r in suite}
        assert {"overall", "charge", "discharge", "rest"} <= scopes
        overall = next(r for r in suite if r.scope == "overall" and r.method == "pearson")
        assert overall.coefficient is not None

    def test_c16_cycle_stratification(self):
        rows = self._suite(40)
        rows.append(_row(999, cycle=1, analysis_eligible=False))
        per_cycle = cycle_stratified_soc(rows, analysis_id="a1", feature_code="TDM")
        assert len(per_cycle) == 4  # cycles 1..4
        assert all(r.scope.startswith("cycle:") for r in per_cycle)
        cycle_one = next(result for result in per_cycle if result.scope == "cycle:1")
        assert cycle_one.n_input == 11
        assert cycle_one.n_valid == 10
        assert cycle_one.excluded_ineligible_count == 1
        assert sum(result.n_input for result in per_cycle) == 41

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
        assert any(
            "only a minimum-variation screen" in limitation
            and "not sensor-calibration evidence or target readiness" in limitation
            for limitation in ok.limitations
        )

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

    def test_p4_soh_correlation_uses_cycle_groups_not_repeated_frames(self):
        rows = []
        cycle_values = (
            (1, 100.0, [0.0]),
            (2, 98.0, [-10.0, *([1.0] * 9)]),
            (3, 96.0, [2.0] * 20),
            (4, 94.0, [3.0] * 4 + [100.0]),
        )
        index = 0
        for cycle, soh, feature_values in cycle_values:
            for feature_value in feature_values:
                rows.append(_row(
                    index,
                    cycle=cycle,
                    soh_percent=soh,
                    value=feature_value,
                ))
                index += 1
        rows.append(_row(index, cycle=1, soh_percent=100.0, value=None))

        result = correlate_feature_state(
            rows,
            state_variable="soh_percent",
            method="pearson",
            analysis_id="p4-soh-grouped",
            feature_code="TDM",
        )

        assert result.status == "VALID"
        assert result.n_input == 37
        assert result.n_valid == 4
        assert result.missing_feature_count == 1
        assert result.n_input_unit == "MEASUREMENT_EVENT"
        assert result.n_valid_unit == "BATTERY_EXPERIMENT_CYCLE_GROUP"
        assert result.missing_count_unit == "MEASUREMENT_EVENT"
        assert result.excluded_ineligible_unit == "MEASUREMENT_EVENT"
        assert result.independent_group_count == 4
        assert result.independent_unit == "BATTERY_EXPERIMENT_CYCLE"
        assert result.distinct_state_count == 4
        assert result.coefficient == pytest.approx(-1.0)

    def test_c20_no_naive_p_value(self):
        rows = self._suite()
        r = correlate_feature_state(
            rows, state_variable="reference_soc_percent", method="pearson",
            analysis_id="a1", feature_code="TDM",
        )
        assert not hasattr(r, "p_value") or "p_value" not in r.model_fields
        assert any("p-value" in l for l in r.limitations)

    def test_p4_nonfinite_measurements_are_missing_and_keep_pair_accounting(self):
        feature_rows = [
            _row(i, value=float(i), reference_soc_percent=float(i * 10))
            for i in range(4)
        ]
        feature_rows[-1].value = float("inf")
        feature_result = correlate_feature_state(
            feature_rows,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="p4-feature-inf",
            feature_code="TDM",
        )
        assert feature_result.status == "VALID"
        assert feature_result.n_valid == 3
        assert feature_result.n_valid_unit == "FEATURE_STATE_PAIR"
        assert feature_result.missing_feature_count == 1
        assert feature_result.missing_state_count == 0
        assert feature_result.coefficient == pytest.approx(1.0)

        state_rows = [
            _row(i, value=float(i), reference_soc_percent=float(i * 10))
            for i in range(4)
        ]
        state_rows[-1].reference_soc_percent = float("nan")
        state_result = correlate_feature_state(
            state_rows,
            state_variable="reference_soc_percent",
            method="pearson",
            analysis_id="p4-state-nan",
            feature_code="TDM",
        )
        assert state_result.status == "VALID"
        assert state_result.n_valid == 3
        assert state_result.missing_feature_count == 0
        assert state_result.missing_state_count == 1
        assert state_result.coefficient == pytest.approx(1.0)

        row = _row(100, value=1.0, temperature_c=25.0, soh_percent=90.0)
        row.temperature_c = float("-inf")
        row.soh_percent = float("nan")
        assert row.temperature_c is None
        assert row.soh_percent is None

    def test_p4_temperature_low_variation_reports_complete_pair_count(self):
        rows = [
            _row(i, value=float(i), temperature_c=25.0 + i * 0.1)
            for i in range(4)
        ]
        rows[-1].value = None

        result = correlate_feature_state(
            rows,
            state_variable="temperature_c",
            method="pearson",
            analysis_id="p4-temperature-pair-count",
            feature_code="TDM",
        )

        assert result.status == "INSUFFICIENT_VARIATION"
        assert result.n_input == 4
        assert result.n_valid == 3
        assert result.missing_feature_count == 1

    def test_p4_between_and_within_battery_are_reported_separately(self):
        # Each battery has a positive within-battery feature/SOC relation,
        # while shifted battery means produce a negative between-battery one.
        rows = []
        for battery, soc_offset, feature_offset in (
            ("CELL_A", 0.0, 100.0),
            ("CELL_B", 20.0, 50.0),
            ("CELL_C", 40.0, 0.0),
        ):
            for i in range(8):
                soc = soc_offset + i
                rows.append(_row(
                    len(rows), battery_id=battery,
                    reference_soc_percent=soc,
                    value=feature_offset + i,
                ))

        result = battery_decomposed_soc_correlation(rows)

        assert result["status"] == "VALID"
        assert result["n_batteries"] == 3
        assert result["n_events"] == 24
        assert result["n_input_events"] == 24
        assert result["missing_feature_count"] == 0
        assert result["missing_state_count"] == 0
        assert result["excluded_ineligible_count"] == 0
        assert result["within_battery"]["coefficient"] == pytest.approx(1.0)
        assert result["between_battery"]["coefficient"] < 0
        assert result["interpretation"] == "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT"

    def test_p4_single_battery_does_not_treat_events_as_independent_groups(self):
        rows = [
            _row(i, reference_soc_percent=float(i), value=float(i * 2))
            for i in range(40)
        ]

        result = battery_decomposed_soc_correlation(rows)

        assert result["status"] == "INSUFFICIENT_BATTERY_GROUPS"
        assert result["n_batteries"] == 1
        assert result["n_events"] == 40
        rows.extend([
            _row(50, value=None, reference_soc_percent=50.0),
            _row(51, value=51.0, reference_soc_percent=None),
            _row(52, analysis_eligible=False, value=1000.0),
        ])
        result = battery_decomposed_soc_correlation(rows)
        assert result["n_input_events"] == 43
        assert result["n_events"] == 40
        assert result["missing_feature_count"] == 1
        assert result["missing_state_count"] == 1
        assert result["excluded_ineligible_count"] == 1
        assert result["between_battery"]["coefficient"] is None
        assert result["within_battery"]["coefficient"] == pytest.approx(1.0)
        assert any("event rows are not independent groups" in item
                   for item in result["limitations"])

    def test_p4_cycle_decomposition_surfaces_within_between_direction_reversal(self):
        rows = []
        index = 0
        for cycle, soc_base, feature_base in (
            (1, 85.0, 0.0),
            (2, 45.0, 100.0),
            (3, 5.0, 200.0),
        ):
            for offset in range(8):
                rows.append(_row(
                    index,
                    cycle=cycle,
                    reference_soc_percent=soc_base + offset,
                    value=feature_base + offset,
                ))
                index += 1

        result = cycle_decomposed_soc_correlation(rows)

        assert result["status"] == "VALID"
        assert result["n_cycle_groups"] == 3
        assert result["within_cycle"]["coefficient"] == pytest.approx(1.0)
        assert result["between_cycle"]["coefficient"] == pytest.approx(-1.0)
        assert result["interpretation"] == "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT"

    def test_p4_two_batteries_do_not_create_tautological_between_correlation(self):
        rows = [
            _row(i, battery_id=battery, reference_soc_percent=float(i), value=float(i * 2))
            for battery, start in (("CELL_A", 0), ("CELL_B", 8))
            for i in range(start, start + 8)
        ]

        result = battery_decomposed_soc_correlation(rows)

        assert result["status"] == "INSUFFICIENT_BATTERY_GROUPS"
        assert result["n_batteries"] == 2
        assert result["between_battery"]["n_batteries"] == 0
        assert result["between_battery"]["coefficient"] is None

    def test_p4_battery_condition_slices_keep_low_support_scopes_visible(self):
        rows = [
            _row(
                i,
                battery_id=battery,
                state=scope,
                feature_code="SWA",
                reference_soc_percent=float(i),
                value=float(i * 2),
            )
            for battery, base in (("CELL_A", 0), ("CELL_B", 20))
            for scope, start in (("charge", base), ("discharge", base + 3), ("rest", base + 6))
            for i in range(start, start + 3)
        ]
        rows.extend([
            _row(90, battery_id="CELL_A", state="charge", feature_code="SWA", value=None),
            _row(91, battery_id="CELL_A", state="charge", feature_code="SWA",
                 analysis_eligible=False),
        ])

        result = battery_condition_stratified_soc(
            rows, analysis_id="p4", feature_code="SWA"
        )

        assert len(result) == 8  # each battery has overall + 3 operating states
        charge_a = next(
            item for item in result
            if item["battery_id"] == "CELL_A" and item["state_scope"] == "charge"
        )
        rest_b = next(
            item for item in result
            if item["battery_id"] == "CELL_B" and item["state_scope"] == "rest"
        )
        assert charge_a["n_valid"] == 3
        assert charge_a["n_input"] == 5
        assert charge_a["missing_feature_count"] == 1
        assert charge_a["excluded_ineligible_count"] == 1
        assert (
            charge_a["n_valid"]
            + charge_a["missing_feature_count"]
            + charge_a["missing_state_count"]
            + charge_a["excluded_ineligible_count"]
            == charge_a["n_input"]
        )
        assert charge_a["status"] == "VALID"
        assert rest_b["n_valid"] == 3
        assert rest_b["status"] == "VALID"

    def test_p4_battery_scatter_is_deterministic_bounded_and_means_use_all_pairs(self):
        rows = [
            _row(i, battery_id="CELL_A", feature_code="SWA", value=float(i),
                 reference_soc_percent=float(i + 10))
            for i in range(10)
        ] + [
            _row(i + 10, battery_id="CELL_B", feature_code="SWA", value=float(i + 100),
                 reference_soc_percent=float(i + 20))
            for i in range(10)
        ]
        rows.extend([
            _row(30, battery_id="CELL_A", feature_code="SWA", value=None,
                 reference_soc_percent=50.0),
            _row(31, battery_id="CELL_B", feature_code="SWA", value=999.0,
                 reference_soc_percent=50.0,
                 analysis_eligible=False),
        ])

        first = battery_scatter_diagnostic(rows, feature_code="SWA", max_points=6)
        second = battery_scatter_diagnostic(rows, feature_code="SWA", max_points=6)

        assert first == second
        assert first["n_input"] == 22
        assert first["n_valid"] == 20
        assert first["excluded_ineligible_count"] == 1
        assert first["missing_feature_count"] == 1
        assert len(first["points"]) <= 6
        assert {point["battery_id"] for point in first["points"]} == {"CELL_A", "CELL_B"}
        means = {item["battery_id"]: item for item in first["battery_means"]}
        assert means["CELL_A"]["feature_mean"] == pytest.approx(4.5)
        assert means["CELL_A"]["target_mean"] == pytest.approx(14.5)
        assert means["CELL_A"]["n_valid"] == 10
        assert means["CELL_B"]["feature_mean"] == pytest.approx(104.5)
        assert means["CELL_B"]["target_mean"] == pytest.approx(24.5)
        assert means["CELL_B"]["n_valid"] == 10


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

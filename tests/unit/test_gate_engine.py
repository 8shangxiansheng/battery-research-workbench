"""BRW-018: Waveform Gate / Window scientific analysis engine tests (T01-T20)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.datasets.test_helpers import make_inputs
from battery_workbench.gates.analysis import (
    build_gated_feature_label_analysis,
    gated_locator,
)
from battery_workbench.gates.engine import (
    between_gate_delay,
    compute_gate_delay_column,
    extract_gated_features,
    gate_time_us,
    promote_tof_column,
)
from battery_workbench.gates.persistence import write_gated_feature_payload
from battery_workbench.gates.schemas import (
    GateScope,
    GateSpec,
    TOFDefinitionSpec,
)


def _wave(length: int = 100, pulse_at: int | None = None, amp: float = 50.0) -> np.ndarray:
    x = np.linspace(0.1, 0.3, length)  # quiet baseline (nonzero, avoids all-zero edge cases)
    wave = 5 * np.sin(x * 40)
    if pulse_at is not None:
        wave[pulse_at] = amp
        wave[pulse_at + 1] = -amp * 0.5
    return wave


def _gate(**overrides) -> GateSpec:
    values = {
        "gate_name": "demo",
        "start_sample": 10,
        "end_sample": 40,
        "scope": GateScope.ANALYSIS_SLICE_GATE,
        "waveform_length": 100,
    }
    values.update(overrides)
    return GateSpec(**values)


# --- T01-T05: GateSpec ---


def test_t01_bounds_must_be_inside_waveform() -> None:
    with pytest.raises(ValueError):
        _gate(end_sample=101)  # end > waveform_length
    with pytest.raises(ValueError):
        _gate(start_sample=-1)


def test_t02_start_must_be_before_end() -> None:
    with pytest.raises(ValueError):
        _gate(start_sample=40, end_sample=40)
    with pytest.raises(ValueError):
        _gate(start_sample=50, end_sample=10)


def test_t03_gate_inside_length_ok() -> None:
    g = _gate(start_sample=0, end_sample=100)
    assert g.start_sample == 0 and g.end_sample == 100


def test_t04_deterministic_gate_id() -> None:
    assert _gate().gate_id == _gate().gate_id
    assert _gate().gate_id.startswith("GATE::")


def test_t05_changed_bounds_change_gate_id() -> None:
    assert _gate().gate_id != _gate(end_sample=41).gate_id
    assert _gate().gate_id != _gate(gate_name="other").gate_id


# --- T06-T09: gated feature extraction ---


def test_t06_amplitude_only_inside_gate() -> None:
    wave = _wave(pulse_at=80)  # pulse OUTSIDE gate 10..40
    feats = extract_gated_features(wave, _gate())
    wave_full = _wave(pulse_at=None)
    # amplitude must match gate-restricted signal, not the outside pulse
    assert feats["amplitude_a_u"] == pytest.approx(np.abs(wave_full[10:40]).max())
    assert feats["amplitude_a_u"] < 10.0  # far below the outside pulse (50)


def test_t07_rms_only_inside_gate() -> None:
    wave = _wave(pulse_at=80)
    feats = extract_gated_features(wave, _gate())
    seg = wave[10:40].astype(np.float64)
    assert feats["waveform_rms_a_u"] == pytest.approx(np.sqrt(np.mean(seg**2)))


def test_t08_p2p_only_inside_gate() -> None:
    wave = _wave(pulse_at=80)
    feats = extract_gated_features(wave, _gate())
    seg = wave[10:40].astype(np.float64)
    assert feats["waveform_p2p_a_u"] == pytest.approx(seg.max() - seg.min())


def test_t09_feature_carries_gate_id() -> None:
    g = _gate()
    feats = extract_gated_features(_wave(), g)
    assert feats["gate_id"] == g.gate_id
    assert feats["gate_name"] == g.gate_name


# --- T10-T11: sample/time display ---


def test_t10_fs_converts_gate_samples_to_us() -> None:
    g = _gate()
    times = gate_time_us(g, sampling_rate_hz=50e6)
    assert times["start_time_us"] == pytest.approx(10 / 50e6 * 1e6)  # 0.2 us
    assert times["end_time_us"] == pytest.approx(40 / 50e6 * 1e6)  # 0.8 us


def test_t11_no_fs_still_permits_sample_domain_gate() -> None:
    g = _gate()
    times = gate_time_us(g, sampling_rate_hz=None)
    assert times["start_time_us"] is None
    assert times["end_time_us"] is None
    feats = extract_gated_features(_wave(), g)  # sample domain works
    assert feats["amplitude_a_u"] is not None


# --- T12-T14: two-gate delay / TOF modes ---


def _two_burst_wave(shift: int, length: int = 200) -> np.ndarray:
    """Reference burst peaking at 18; received burst = pure delayed copy."""
    t = np.arange(length, dtype=float)
    ref = 30.0 * np.exp(-((t - 17) ** 2) / 8.0) * np.sin(t * 1.3)
    rcv = np.zeros_like(ref)
    rcv[shift:] = 0.8 * ref[: length - shift] if shift else 0.8 * ref
    return ref + rcv + 0.5 * np.sin(t * 0.4)


def test_t12_synthetic_two_gate_delay_exact() -> None:
    shift = 12
    wave = _two_burst_wave(shift)
    # Gates must each contain only their own burst's |max| (18 vs 30).
    ref = _gate(gate_name="ref", start_sample=8, end_sample=25, waveform_length=200)
    rcv = _gate(gate_name="rcv", start_sample=25, end_sample=42, waveform_length=200)
    assert between_gate_delay(wave, ref, rcv) == shift


def test_t13_delay_is_not_automatically_tof() -> None:
    """confirmed=False → column is delay_us; no tof_us is produced."""
    col_name, values, tof_def = compute_gate_delay_column(
        waveform=_two_burst_wave(12),
        reference_gate=_gate(gate_name="ref", start_sample=8, end_sample=25, waveform_length=200),
        received_gate=_gate(gate_name="rcv", start_sample=25, end_sample=42, waveform_length=200),
        sampling_rate_hz=50e6,
        physical_interpretation_confirmed=False,
    )
    assert col_name == "delay_us"
    assert tof_def is None
    assert values[0] == pytest.approx(12 / 50e6 * 1e6)


def test_t14_tof_promotion_requires_physical_confirmation() -> None:
    """confirmed=True → the SAME measurement may be named canonical tof_us."""
    wave = _two_burst_wave(12)
    ref = _gate(gate_name="ref", start_sample=5, end_sample=36)
    rcv = _gate(gate_name="rcv", start_sample=17, end_sample=48)
    spec = TOFDefinitionSpec(
        mode="BETWEEN_GATES",
        reference_gate_id=ref.gate_id,
        received_gate_id=rcv.gate_id,
        physical_interpretation_confirmed=True,
    )
    col_name, values = promote_tof_column(
        waveform=wave,
        reference_gate=_gate(gate_name="ref", start_sample=8, end_sample=25, waveform_length=200),
        received_gate=_gate(gate_name="rcv", start_sample=25, end_sample=42, waveform_length=200),
        sampling_rate_hz=50e6,
        tof_definition=spec,
    )
    assert col_name == "tof_us"
    assert values[0] == pytest.approx(12 / 50e6 * 1e6)  # 0.24 us

    # Unconfirmed definition must NOT promote.
    spec_unconfirmed = spec.model_copy(update={"physical_interpretation_confirmed": False})
    with pytest.raises(ValueError):
        promote_tof_column(
            waveform=wave,
            reference_gate=_gate(
                gate_name="ref", start_sample=8, end_sample=25, waveform_length=200
            ),
            received_gate=_gate(
                gate_name="rcv", start_sample=25, end_sample=42, waveform_length=200
            ),
            sampling_rate_hz=50e6,
            tof_definition=spec_unconfirmed,
        )


# --- T15-T18: integration semantics ---


def _event_frame(n: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
        }
    )


def test_t15_no_label_fields_enter_predictors(tmp_path) -> None:
    from battery_workbench.datasets.builder import build_soc_dataset
    from battery_workbench.datasets.schemas import DatasetConfig
    from battery_workbench.datasets.test_helpers import make_inputs

    feats, lbls, cyc = make_inputs()
    g = _gate()
    # gated locator columns on the feature frame
    loc = f"amplitude_a_u@{g.gate_id}"
    feats[loc] = feats["waveform_abs_peak_a_u"]
    cfg = DatasetConfig()
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=[loc],
    )
    assert report.predictor_columns == [loc]
    # selecting a label field stays forbidden even in locator form
    with pytest.raises(AssertionError, match="target-leakage"):
        build_soc_dataset(
            features=feats,
            event_labels=lbls,
            cycle_labels=cyc,
            config=cfg,
            selected_features=["soc_dod_percent"],
        )


def test_t16_measurement_event_exact_join() -> None:
    feats, lbls, cyc = make_inputs()
    g = _gate()
    gated = _event_frame(len(feats))
    gated["gate_id"] = g.gate_id
    gated["amplitude_a_u"] = np.arange(len(feats), dtype=float)
    result = build_gated_feature_label_analysis(
        gated_features=gated, event_labels=lbls, cycle_labels=cyc, event_grain=True
    )
    assert len(result) == len(feats)
    assert gated_locator("amplitude_a_u", g.gate_id) in result.columns
    assert "soc_reference_percent" in result.columns


def test_t17_exploratory_frame_gate_not_ml_ready() -> None:
    from battery_workbench.gates.schemas import gate_set_ml_ready

    frame_gate = _gate(scope=GateScope.EXPLORATORY_FRAME_GATE)
    assert gate_set_ml_ready([frame_gate]) is False
    slice_gate = _gate()
    assert gate_set_ml_ready([slice_gate]) is True
    assert gate_set_ml_ready([slice_gate, frame_gate]) is False


def test_t18_gate_selection_basis_persisted(tmp_path) -> None:
    g = _gate()
    gated = _event_frame(3)
    gated["gate_id"] = g.gate_id
    gated["amplitude_a_u"] = [1.0, 2.0, 3.0]
    paths = write_gated_feature_payload(
        gated_features=gated,
        gate_specs=[g],
        tof_definitions=[],
        gate_selection_basis="SIGNAL_ONLY",
        battery_id="CELL_X",
        experiment_id="EXP_X",
        output_root=tmp_path,
    )
    manifest = (tmp_path / paths["gated_feature_manifest"]).read_text()
    assert "SIGNAL_ONLY" in manifest
    assert "gate_selection_basis" in manifest


# --- T21-T28: task-pack test plan additions ---


def test_t21_end_sample_exclusive_documented() -> None:
    """Half-open [start_sample, end_sample) semantics, fixed and documented."""
    wave = _wave(100)
    wave[40] = 999.0  # exactly at end boundary
    feats = extract_gated_features(wave, _gate())  # gate 10..40
    assert feats["amplitude_a_u"] < 100.0  # sample 40 excluded
    from battery_workbench.gates.schemas import GATE_SLICING_SEMANTICS

    assert GATE_SLICING_SEMANTICS == "[start_sample:end_sample)"


def test_t22_nan_inside_gate_returns_none_features() -> None:
    wave = _wave(100)
    wave[15] = np.nan
    feats = extract_gated_features(wave, _gate())
    assert feats["amplitude_a_u"] is None
    assert feats["waveform_rms_a_u"] is None
    assert feats["envelope_peak_a_u"] is None
    assert feats["gate_id"] == _gate().gate_id  # row still carries provenance


def test_t23_saturated_waveform_handling() -> None:
    from battery_workbench.gates.engine import SATURATION_LIMIT, gate_stability_audit

    n = 5
    waves = np.stack([_wave(100, pulse_at=30 + i) for i in range(n)])
    waves[0, 35] = SATURATION_LIMIT  # one saturated sample inside gate
    gate = _gate()
    report = gate_stability_audit(gate, waves=waves)
    assert report["saturation_rate"] == pytest.approx(1 / n)
    assert report["peak_inside_gate_rate"] == pytest.approx(1.0)


def test_t23b_narrow_gate_warns() -> None:
    from battery_workbench.gates.engine import gate_stability_audit

    waves = np.stack([_wave(100, pulse_at=60) for _ in range(5)])
    narrow = _gate(start_sample=55, end_sample=62)  # peak at edge
    report = gate_stability_audit(narrow, waves=waves)
    assert "GATE_MAY_BE_TOO_NARROW" in report["warnings"]


def test_t24_duplicate_gate_name_warning() -> None:
    from battery_workbench.gates.schemas import gate_set_warnings

    g1 = _gate(gate_name="same")
    g2 = _gate(gate_name="same", start_sample=50, end_sample=60)
    warnings = gate_set_warnings([g1, g2])
    assert any("DUPLICATE_GATE_NAME" in w for w in warnings)
    assert gate_set_warnings([_gate()]) == []


def test_t25_gate_set_id_deterministic() -> None:
    from battery_workbench.gates.persistence import build_gate_set_id

    g = _gate()
    assert build_gate_set_id([g]) == build_gate_set_id([g.model_copy()])
    assert build_gate_set_id([g]).startswith("GATESET::")


def test_t26_changed_gate_set_changes_gate_set_id() -> None:
    from battery_workbench.gates.persistence import build_gate_set_id

    g1 = _gate()
    g2 = _gate(end_sample=41)
    assert build_gate_set_id([g1]) != build_gate_set_id([g2])
    assert build_gate_set_id([g1]) != build_gate_set_id([g1, g2])


def test_t27_gate_locator_changes_dataset_id() -> None:
    from battery_workbench.datasets.builder import build_soc_dataset
    from battery_workbench.datasets.schemas import DatasetConfig
    from battery_workbench.datasets.test_helpers import make_inputs

    feats, lbls, cyc = make_inputs()
    g = _gate()
    loc = f"amplitude_a_u@{g.gate_id}"
    feats[loc] = feats["waveform_abs_peak_a_u"]
    cfg = DatasetConfig()
    r1, _ = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=["waveform_abs_peak_a_u"],
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        feature_set_path=None,
        label_set_path=None,
    )
    r2, _ = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=[loc],
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        feature_set_path=None,
        label_set_path=None,
    )
    assert r1.dataset_id != r2.dataset_id


def test_t28_full_wave_and_gated_provenance_distinct() -> None:
    """Locator column and plain column coexist without name collision."""
    g = _gate()
    wave = _wave(100, pulse_at=80)  # pulse outside the gate
    feats = extract_gated_features(wave, g)
    df = pd.DataFrame({"amplitude_a_u": [np.abs(wave).max()]})
    df[f"amplitude_a_u@{g.gate_id}"] = feats["amplitude_a_u"]
    assert "amplitude_a_u" in df.columns
    assert f"amplitude_a_u@{g.gate_id}" in df.columns
    assert df.loc[0, "amplitude_a_u"] != df.loc[0, f"amplitude_a_u@{g.gate_id}"]


def test_t29_gate_config_loader() -> None:
    """Example-YAML-shaped config loads into specs (service contract)."""
    from battery_workbench.gates.schemas import gate_set_from_config

    config = {
        "gate_set": {
            "name": "exploratory_dual_window",
            "selection_basis": "SIGNAL_ONLY",
            "gates": [
                {
                    "gate_name": "primary_signal",
                    "start_sample": 0,
                    "end_sample": 200,
                    "semantic_role": "ANALYSIS_WINDOW",
                    "scope": "GLOBAL_EXPERIMENT_GATE",
                },
                {
                    "gate_name": "secondary_signal",
                    "start_sample": 700,
                    "end_sample": 1000,
                    "semantic_role": "ANALYSIS_WINDOW",
                    "scope": "GLOBAL_EXPERIMENT_GATE",
                },
            ],
        },
        "features": ["amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"],
        "tof_definition": {
            "mode": "BETWEEN_GATES",
            "physical_interpretation_confirmed": False,
        },
    }
    gates, tof_def, basis, features = gate_set_from_config(config, waveform_length=1250)
    assert len(gates) == 2
    assert all(g.gate_id.startswith("GATE::") for g in gates)
    assert tof_def is not None and tof_def.mode == "BETWEEN_GATES"
    assert tof_def.physical_interpretation_confirmed is False
    assert basis == "SIGNAL_ONLY"
    assert features == ["amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"]


def test_t30_feature_analysis_output_contract(tmp_path) -> None:
    """Output contract: feature_analysis/ + artifacts/ layout."""
    from battery_workbench.gates.persistence import (
        write_gate_report_artifacts,
        write_gated_analysis_payload,
    )

    analysis = _event_frame(3)
    paths = write_gated_analysis_payload(
        analysis_df=analysis,
        manifest={"gate_set_id": "GATESET::x"},
        report={"summary": "ok"},
        battery_id="CELL_X",
        experiment_id="EXP_X",
        gate_set_id="GATESET::x",
        output_root=tmp_path,
    )
    assert (tmp_path / paths["analysis_parquet"]).exists()
    assert (tmp_path / paths["analysis_manifest"]).exists()
    assert (tmp_path / paths["analysis_report"]).exists()
    assert "feature_analysis/CELL_X/EXP_X/GATESET::x/" in paths["analysis_parquet"]

    art_paths = write_gate_report_artifacts(
        report={"gates": 2},
        plots={"rep_first": b"png-bytes"},
        battery_id="CELL_X",
        experiment_id="EXP_X",
        gate_set_id="GATESET::x",
        output_root=tmp_path,
    )
    assert (tmp_path / art_paths["report_json"]).exists()
    assert (tmp_path / art_paths["report_html"]).exists()
    assert (tmp_path / art_paths["representative_waveforms"]).exists()
    assert "artifacts/CELL_X/EXP_X/gates/GATESET::x" in art_paths["report_json"]

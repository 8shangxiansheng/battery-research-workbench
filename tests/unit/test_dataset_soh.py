"""T19-T28: SOH dataset builder contract."""

from __future__ import annotations

import pandas as pd

from battery_workbench.datasets.builder import build_soh_dataset


def _make_inputs(n: int = 6, n_cycles: int = 2):
    cyc = [1.0 if i < n // 2 else 2.0 for i in range(n)]
    feats = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "event_order_index": list(range(n)),
            "cycle_index_raw": cyc,
            "step_index_raw": [4.0] * n,
            "step_type": ["恒流放电"] * n,
            "voltage_v": [3.5] * n,
            "current_a": [1.0] * n,
            "capacity_ah": [0.5] * n,
            "temperature_c": [25.0] * n,
            "elapsed_time_s": [10.0] * n,
            "sync_error_s": [0.03] * n,
            "event_quality_status": ["READY"] * n,
            "analysis_eligible": [True] * n,
            "feature_status": ["READY"] * n,
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * n),
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
            "waveform_rms_a_u": [0.7 * i for i in range(n)],
            "waveform_min_a_u": [-1.0] * n,
            "waveform_max_a_u": [1.0] * n,
            "waveform_mean_a_u": [0.1] * n,
            "waveform_std_a_u": [0.5] * n,
            "waveform_p2p_a_u": [2.0] * n,
            "waveform_abs_peak_a_u": [1.5] * n,
            "waveform_abs_peak_sample_index": [0] * n,
            "waveform_energy_sum_sq_a_u2": [3.0] * n,
            "envelope_peak_a_u": [1.2] * n,
            "envelope_peak_sample_index": [0] * n,
            "xcorr_reference_measurement_event_id": ["ME::0"] * n,
            "xcorr_shift_samples": [0] * n,
            "xcorr_peak_coefficient": [0.9] * n,
        }
    )
    lbls = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "cycle_index_raw": cyc,
            "soc_reference_percent": [50.0] * n,
            "soc_label_eligible": [True] * n,
            "soh_capacity_reference_percent": [100.0 if c == 1.0 else 99.68 for c in cyc],
            "soh_label_eligible": [True] * n,
            "battery_group_id": ["BG::CELL_X"] * n,
            "experiment_group_id": ["EG::CELL_X::EXP_X"] * n,
            "cycle_group_id": [f"CG::CELL_X::EXP_X::{int(c)}" for c in cyc],
            "label_group_id": [f"LG::CELL_X::EXP_X::{int(c)}" for c in cyc],
        }
    )
    cyc_lbls = pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * n_cycles,
            "experiment_id": ["EXP_X"] * n_cycles,
            "cycle_index_raw": [1.0, 2.0][:n_cycles],
            "soh_capacity_reference_percent": [100.0, 99.68][:n_cycles],
            "soh_reference_cycle_index": [1] * n_cycles,
            "soh_reference_quality": ["VALID_REFERENCE"] * n_cycles,
            "soh_label_eligible": [True] * n_cycles,
        }
    )
    return feats, lbls, cyc_lbls


def test_eligible_only_t19() -> None:
    feats, lbls, cyc = _make_inputs()
    lbls.loc[0, "soh_label_eligible"] = False
    _, df = build_soh_dataset(features=feats, event_labels=lbls, cycle_labels=cyc)
    assert "ME::0" not in df["measurement_event_id"].values


def test_target_non_null_t20() -> None:
    feats, lbls, cyc = _make_inputs()
    lbls.loc[1, "soh_capacity_reference_percent"] = None
    _, df = build_soh_dataset(features=feats, event_labels=lbls, cycle_labels=cyc)
    assert "ME::1" not in df["measurement_event_id"].values


def test_cycle_target_exact_t21() -> None:
    feats, lbls, cyc = _make_inputs()
    _, df = build_soh_dataset(features=feats, event_labels=lbls, cycle_labels=cyc)
    r_c1 = df[df["cycle_index_raw"] == 1.0].iloc[0]
    r_c2 = df[df["cycle_index_raw"] == 2.0].iloc[0]
    assert r_c1["soh_capacity_reference_percent"] == 100.0
    assert r_c2["soh_capacity_reference_percent"] == 99.68


def test_cycle_index_forbidden_predictor_t22() -> None:
    report, _df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    assert "cycle_index_raw" not in report.predictor_columns


def test_capacity_retention_forbidden_t23() -> None:
    report, _df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    for col in (
        "capacity_retention_percent",
        "discharge_capacity_measured_ah",
        "soh_reference_capacity_ah",
    ):
        assert col not in report.predictor_columns


def test_soc_target_absent_t24() -> None:
    _, df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    assert "soc_reference_percent" not in df.columns


def test_independent_soh_group_id_t25() -> None:
    _, df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    assert "independent_soh_group_id" in df.columns
    assert df["independent_soh_group_id"].nunique() == 2


def test_target_diversity_count_t26() -> None:
    report, _df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    assert report.distinct_soh_values == 2
    assert report.cycle_group_count == 2


def test_small_diversity_status_t27() -> None:
    report, _df = build_soh_dataset(
        **dict(zip(("features", "event_labels", "cycle_labels"), _make_inputs()))
    )
    assert report.dataset_status == "NOT_READY_FOR_MODEL_EVALUATION"


def test_exact_golden_propagation_t28() -> None:
    feats, lbls, cyc = _make_inputs()
    _, df = build_soh_dataset(features=feats, event_labels=lbls, cycle_labels=cyc)
    r = df[df["measurement_event_id"] == "ME::3"].iloc[0]
    assert r["soh_capacity_reference_percent"] == 99.68
    assert r["cycle_group_id"] == "CG::CELL_X::EXP_X::2"
    assert r["independent_soh_group_id"] == "CG::CELL_X::EXP_X::2"

"""T09-T18: SOC dataset builder contract."""

from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.datasets.builder import build_soc_dataset


def _make_inputs(n: int = 6):
    """Build minimal feature+label DataFrames with mixed eligibility."""
    feats = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "event_order_index": list(range(n)),
            "cycle_index_raw": [1.0] * n,
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
            # ultrasound predictors
            "waveform_min_a_u": [-1.0 * i for i in range(n)],
            "waveform_max_a_u": [1.0 * i for i in range(n)],
            "waveform_mean_a_u": [0.1 * i for i in range(n)],
            "waveform_std_a_u": [0.5 * i for i in range(n)],
            "waveform_rms_a_u": [0.7 * i for i in range(n)],
            "waveform_p2p_a_u": [2.0 * i for i in range(n)],
            "waveform_abs_peak_a_u": [1.5 * i for i in range(n)],
            "waveform_abs_peak_sample_index": [i for i in range(n)],
            "waveform_energy_sum_sq_a_u2": [3.0 * i for i in range(n)],
            "envelope_peak_a_u": [1.2 * i for i in range(n)],
            "envelope_peak_sample_index": [i for i in range(n)],
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
            "cycle_index_raw": [1.0] * n,
            "soc_reference_percent": [20.0 * i for i in range(n)],
            "soc_label_eligible": [True] * n,
            "soc_label_temporality": ["RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"] * n,
            "soc_reference_quality": ["VALID_REFERENCE"] * n,
            "soc_formula_version": ["0.2.0"] * n,
            "soc_anchor_quality": ["REFERENCE_PROTOCOL_ANCHOR"] * n,
            "soc_integral_unbounded_percent": [20.5 * i for i in range(n)],
            "soc_reference_capacity_ah": [11.04] * n,
            "soc_direction": ["DISCHARGE"] * n,
            "soh_capacity_reference_percent": [100.0] * n,
            "soh_label_eligible": [True] * n,
            "battery_group_id": ["BG::CELL_X"] * n,
            "experiment_group_id": ["EG::CELL_X::EXP_X"] * n,
            "cycle_group_id": ["CG::CELL_X::EXP_X::1"] * n,
            "label_group_id": ["LG::CELL_X::EXP_X::1"] * n,
        }
    )
    return feats, lbls


def _build(feats=None, lbls=None):
    from battery_workbench.datasets.schemas import DatasetConfig

    if feats is None:
        feats = _make_inputs()[0]
    if lbls is None:
        lbls = _make_inputs()[1]
    return build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=pd.DataFrame(
            {
                "battery_id": ["CELL_X"],
                "experiment_id": ["EXP_X"],
                "cycle_index_raw": [1.0],
                "soh_capacity_reference_percent": [100.0],
                "soh_reference_cycle_index": [1],
                "soh_reference_quality": ["VALID_REFERENCE"],
                "soh_label_eligible": [True],
            }
        ),
        config=DatasetConfig(),
    )


def test_eligible_only_t09() -> None:
    feats, lbls = _make_inputs()
    lbls.loc[0, "soc_label_eligible"] = False
    _report, df = _build(feats, lbls)
    assert "ME::0" not in df["measurement_event_id"].values
    assert len(df) == 5


def test_target_non_null_t10() -> None:
    feats, lbls = _make_inputs()
    lbls.loc[1, "soc_reference_percent"] = None
    _report, df = _build(feats, lbls)
    assert "ME::1" not in df["measurement_event_id"].values


def test_usable_feature_only_t11() -> None:
    feats, lbls = _make_inputs()
    feats.loc[2, "feature_status"] = "NONFINITE_WAVEFORM"
    _report, df = _build(feats, lbls)
    assert "ME::2" not in df["measurement_event_id"].values


def test_ultrasound_only_predictors_t12() -> None:
    report, _df = _build()
    for col in report.predictor_columns:
        assert col.startswith(("waveform_", "envelope_", "xcorr_"))
    for forbidden in ("voltage_v", "current_a", "capacity_ah", "temperature_c", "cycle_index_raw"):
        assert forbidden not in report.predictor_columns


def test_vendor_soc_dod_forbidden_t13() -> None:
    feats, lbls = _make_inputs()
    feats["soc_dod_percent"] = 50.0
    report, _df = _build(feats, lbls)
    assert "soc_dod_percent" not in report.predictor_columns
    assert "soc_dod_percent" in report.forbidden_predictor_columns


def test_capacity_forbidden_t14() -> None:
    report, _df = _build()
    for col in (
        "capacity_ah",
        "soc_reference_capacity_ah",
        "charge_capacity_ah",
        "discharge_capacity_ah",
    ):
        assert col not in report.predictor_columns


def test_soh_target_absent_t15() -> None:
    _report, df = _build()
    assert "soh_capacity_reference_percent" not in df.columns


def test_temporality_preserved_t16() -> None:
    _report, df = _build()
    assert "soc_label_temporality" in df.columns
    assert (df["soc_label_temporality"] == "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE").all()


def test_groups_preserved_t17() -> None:
    _report, df = _build()
    for c in ("battery_group_id", "experiment_group_id", "cycle_group_id", "label_group_id"):
        assert c in df.columns


def test_exact_golden_propagation_t18() -> None:
    feats, lbls = _make_inputs()
    _report, df = _build(feats, lbls)
    r0 = df[df["measurement_event_id"] == "ME::3"].iloc[0]
    assert r0["soc_reference_percent"] == 60.0
    assert r0["waveform_rms_a_u"] == pytest.approx(2.1)
    assert r0["cycle_group_id"] == "CG::CELL_X::EXP_X::1"

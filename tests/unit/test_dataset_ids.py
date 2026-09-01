"""T39-T46: deterministic dataset ID + provenance."""

from __future__ import annotations

import pandas as pd

from battery_workbench.datasets.ids import build_dataset_id
from battery_workbench.datasets.schemas import DatasetConfig


def _config(**kw) -> DatasetConfig:
    return DatasetConfig(**kw)


def test_deterministic_id_t39() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc_reference_percent",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc_reference_percent",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    assert a == b
    assert a.startswith("DS::")


def test_feature_set_change_t40() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::B",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(),
        feature_checksum="c3",
        label_checksum="c2",
    )
    assert a != b


def test_label_set_change_t41() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::B",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c3",
    )
    assert a != b


def test_target_change_t42() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soh",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    assert a != b


def test_predictor_policy_change_t43() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(predictor_policy="ULTRASOUND_ONLY"),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(predictor_policy="MULTIMODAL"),
        feature_checksum="c1",
        label_checksum="c2",
    )
    assert a != b


def test_leakage_policy_change_t44() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(leakage_policy_version="1.0"),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc",
        config=_config(leakage_policy_version="2.0"),
        feature_checksum="c1",
        label_checksum="c2",
    )
    assert a != b


def test_soc_soh_separate_ids() -> None:
    a = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soc_reference_percent",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    b = build_dataset_id(
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        target_name="soh_capacity_reference_percent",
        config=_config(),
        feature_checksum="c1",
        label_checksum="c2",
    )
    assert a != b


def test_parameter_provenance_t45() -> None:
    """Config records parameter_set_id + dependency level."""
    cfg = _config()
    assert hasattr(cfg, "parameter_dependency")
    assert cfg.parameter_dependency == "INFORMATIONAL"


def test_analysis_slice_provenance_t46() -> None:
    """Builder records analysis_slice_id in the report."""
    from battery_workbench.datasets.builder import build_soc_dataset
    from battery_workbench.datasets.schemas import DatasetConfig

    n = 2
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
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06"] * n),
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
            "waveform_rms_a_u": [1.0, 2.0],
            "waveform_min_a_u": [-1.0, -2.0],
            "waveform_max_a_u": [1.0, 2.0],
            "waveform_mean_a_u": [0.0, 0.1],
            "waveform_std_a_u": [0.5, 0.6],
            "waveform_p2p_a_u": [2.0, 4.0],
            "waveform_abs_peak_a_u": [1.0, 2.0],
            "waveform_abs_peak_sample_index": [0, 1],
            "waveform_energy_sum_sq_a_u2": [2.0, 4.0],
            "envelope_peak_a_u": [1.1, 2.1],
            "envelope_peak_sample_index": [0, 1],
            "xcorr_reference_measurement_event_id": ["ME::0", "ME::0"],
            "xcorr_shift_samples": [0, 0],
            "xcorr_peak_coefficient": [0.9, 0.9],
        }
    )
    lbls = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "cycle_index_raw": [1.0] * n,
            "soc_reference_percent": [10.0, 20.0],
            "soc_label_eligible": [True] * n,
            "soc_label_temporality": ["RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"] * n,
            "soc_reference_quality": ["VALID_REFERENCE"] * n,
            "soc_formula_version": ["0.2.0"] * n,
            "soc_anchor_quality": ["REFERENCE_PROTOCOL_ANCHOR"] * n,
            "soc_integral_unbounded_percent": [10.0, 20.0],
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
    cyc = pd.DataFrame(
        {
            "battery_id": ["CELL_X"],
            "experiment_id": ["EXP_X"],
            "cycle_index_raw": [1.0],
            "soh_capacity_reference_percent": [100.0],
            "soh_reference_cycle_index": [1],
            "soh_reference_quality": ["VALID_REFERENCE"],
            "soh_label_eligible": [True],
        }
    )
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=DatasetConfig(),
        analysis_slice_id="AS::test",
        feature_set_id="FS::test",
        label_set_id="LB::test",
        parameter_set_id="PS::test",
    )
    assert report.analysis_slice_id == "AS::test"
    assert report.feature_set_id == "FS::test"
    assert report.label_set_id == "LB::test"
    assert report.parameter_set_id == "PS::test"
    assert report.parameter_dependency == "INFORMATIONAL"

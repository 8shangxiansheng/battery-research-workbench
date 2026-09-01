"""BRW-017 V2: Dataset builder retrofit + feature_label_analysis tests."""

from __future__ import annotations

import pytest

from battery_workbench.datasets.builder import build_soc_dataset
from battery_workbench.datasets.schemas import DatasetConfig
from battery_workbench.datasets.test_helpers import make_inputs


def test_selected_features_explicit() -> None:
    """Dataset builder accepts selected_features and respects it."""
    feats, lbls, cyc = make_inputs()
    cfg = DatasetConfig()
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=["waveform_rms_a_u", "waveform_p2p_a_u"],
    )
    assert report.predictor_columns == ["waveform_p2p_a_u", "waveform_rms_a_u"]
    # Output df retains all joined columns (BRW-016 semantics); the ML feature
    # set is defined by predictor_columns.
    assert "waveform_min_a_u" not in report.predictor_columns


def test_selected_features_none_defaults_legacy() -> None:
    """selected_features=None reproduces the legacy BRW-016 predictor set."""
    feats, lbls, cyc = make_inputs()
    cfg = DatasetConfig()
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
    )
    assert "waveform_rms_a_u" in report.predictor_columns
    assert "waveform_min_a_u" in report.predictor_columns


def test_different_selected_features_different_id() -> None:
    feats, lbls, cyc = make_inputs()
    cfg = DatasetConfig()
    r1, _ = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=["waveform_rms_a_u"],
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
        selected_features=["waveform_p2p_a_u"],
        feature_set_id="FS::A",
        label_set_id="LB::A",
        parameter_set_id="PS::A",
        feature_set_path=None,
        label_set_path=None,
    )
    assert r1.dataset_id != r2.dataset_id


def test_selected_features_include_tof_us() -> None:
    """tof_us can be selected if a physical feature column exists."""
    feats, lbls, cyc = make_inputs()
    feats["tof_us"] = [0.1 * i for i in range(len(feats))]
    # amplitude_a_u is the user-visible alias of waveform_abs_peak_a_u.
    feats["amplitude_a_u"] = feats["waveform_abs_peak_a_u"]
    cfg = DatasetConfig()
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=["tof_us", "amplitude_a_u"],
    )
    assert "tof_us" in report.predictor_columns
    assert "amplitude_a_u" in report.predictor_columns
    assert "waveform_rms_a_u" not in report.predictor_columns


def test_selected_features_include_amplitude_alias() -> None:
    """amplitude_a_u is an alias for waveform_abs_peak_a_u."""
    feats, lbls, cyc = make_inputs()
    feats["amplitude_a_u"] = feats["waveform_abs_peak_a_u"]
    cfg = DatasetConfig()
    report, _df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=cfg,
        selected_features=["amplitude_a_u"],
    )
    assert "amplitude_a_u" in report.predictor_columns


def test_target_leakage_guard_not_bypassable() -> None:
    """Even with explicit selected_features, target-leakage fields are rejected."""
    feats, lbls, cyc = make_inputs()
    cfg = DatasetConfig()
    with pytest.raises(AssertionError, match="target-leakage"):
        build_soc_dataset(
            features=feats,
            event_labels=lbls,
            cycle_labels=cyc,
            config=cfg,
            selected_features=["soc_dod_percent"],
        )


# --- feature_label_analysis ---


def test_analysis_table_basic() -> None:
    from battery_workbench.datasets.analysis import build_feature_label_analysis

    feats, lbls, cyc = make_inputs()
    result = build_feature_label_analysis(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
    )
    assert "measurement_event_id" in result.columns
    assert "soc_reference_percent" in result.columns
    assert "waveform_rms_a_u" in result.columns
    assert "soh_capacity_reference_percent" in result.columns
    assert len(result) == len(feats)


def test_analysis_table_all_features() -> None:
    """Analysis table includes all ultrasound features by default."""
    from battery_workbench.datasets.analysis import build_feature_label_analysis

    feats, lbls, cyc = make_inputs()
    result = build_feature_label_analysis(features=feats, event_labels=lbls, cycle_labels=cyc)
    for col in (
        "waveform_rms_a_u",
        "waveform_p2p_a_u",
        "envelope_peak_a_u",
        "xcorr_shift_samples",
        "xcorr_peak_coefficient",
    ):
        assert col in result.columns


def test_analysis_table_carries_tof_status() -> None:
    """TOF status/block-reason accompany tof_us so nulls stay explainable."""
    from battery_workbench.datasets.analysis import build_feature_label_analysis

    feats, lbls, cyc = make_inputs()
    feats["tof_us"] = [None] * len(feats)
    feats["tof_status"] = "BLOCKED"
    feats["tof_block_reason"] = "ARRIVAL_DETECTOR_NOT_VALIDATED"
    result = build_feature_label_analysis(features=feats, event_labels=lbls, cycle_labels=cyc)
    assert "tof_us" in result.columns
    assert "tof_status" in result.columns
    assert "tof_block_reason" in result.columns
    assert (result["tof_status"] == "BLOCKED").all()


def test_dataset_id_legacy_compat_none() -> None:
    """selected_features=None reproduces the legacy id byte-for-byte."""
    from battery_workbench.datasets.ids import build_dataset_id

    kwargs = {
        "feature_set_id": "FS::A",
        "label_set_id": "LB::A",
        "parameter_set_id": "PS::A",
        "target_name": "soc_reference_percent",
        "config": DatasetConfig(),
        "feature_checksum": "c1",
        "label_checksum": "c2",
    }
    assert build_dataset_id(**kwargs) == build_dataset_id(**kwargs, selected_features=None)

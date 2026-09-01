"""T29-T38: leakage policy, column roles, preprocessing guards."""

from __future__ import annotations

from battery_workbench.datasets.leakage import (
    frame_random_split_prohibited,
    minimum_safe_grouping_key,
)
from battery_workbench.datasets.roles import ColumnRole


def test_frame_random_split_prohibited_t29() -> None:
    assert frame_random_split_prohibited() is True


def test_identity_not_predictor_t30() -> None:
    from battery_workbench.datasets.roles import get_column_role

    for col in (
        "measurement_event_id",
        "battery_id",
        "experiment_id",
        "ultrasound_asset_id",
        "frame_index_raw",
        "event_order_index",
    ):
        assert get_column_role(col) != ColumnRole.PREDICTOR


def test_group_not_predictor_t31() -> None:
    from battery_workbench.datasets.roles import get_column_role

    for col in ("battery_group_id", "experiment_group_id", "cycle_group_id", "label_group_id"):
        assert get_column_role(col) != ColumnRole.PREDICTOR


def test_target_not_predictor_t32() -> None:
    from battery_workbench.datasets.roles import get_column_role

    assert get_column_role("soc_reference_percent") == ColumnRole.TARGET
    assert get_column_role("soh_capacity_reference_percent") == ColumnRole.TARGET


def test_context_not_default_predictor_t33() -> None:
    from battery_workbench.datasets.roles import get_column_role

    for col in (
        "voltage_v",
        "current_a",
        "temperature_c",
        "capacity_ah",
        "cycle_index_raw",
        "elapsed_time_s",
        "step_type",
    ):
        assert get_column_role(col) != ColumnRole.PREDICTOR


def test_no_scaling_t34() -> None:
    import battery_workbench.datasets as ds

    for forbidden in ("StandardScaler", "MinMaxScaler", "PCA", "scale", "fit_transform"):
        assert not hasattr(ds, forbidden)


def test_no_imputation_t35() -> None:
    import battery_workbench.datasets as ds

    for forbidden in ("impute", "forward_fill", "fillna_predictor", "interpolate"):
        assert not hasattr(ds, forbidden)


def test_no_feature_selection_t36() -> None:
    import battery_workbench.datasets as ds

    for forbidden in ("select_features", "feature_selection", "rfe", "lasso_select"):
        assert not hasattr(ds, forbidden)


def test_no_balancing_t37() -> None:
    import battery_workbench.datasets as ds

    for forbidden in ("smote", "oversample", "undersample", "balance"):
        assert not hasattr(ds, forbidden)


def test_no_target_binning_t38() -> None:
    import battery_workbench.datasets as ds

    assert not hasattr(ds, "bin_target")


def test_minimum_safe_grouping_key() -> None:
    key = minimum_safe_grouping_key()
    assert key == "cycle_group_id"


def test_leakage_reasons_present() -> None:
    from battery_workbench.datasets.leakage import leakage_reasons

    reasons = leakage_reasons()
    assert len(reasons) >= 4
    assert any("correlation" in r.lower() for r in reasons)

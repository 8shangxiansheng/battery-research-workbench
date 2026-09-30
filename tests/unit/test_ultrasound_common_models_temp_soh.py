"""Planex AC: 超声常见模型扩展 + SOH离线标签复用验证 + 温度条件放行.

AC1 (M1-M5): ELASTIC_NET + HUBER_REGRESSION 进入固定基线套件
  (STRATEGIES/FIXED_CONFIGS/确定性 fit/未知拒绝/scaled pipeline).
AC2 (S1-S4): SOH 容量比法离线标签复用验证 — 公式与暴露列不变,
  只确认管线行为 (已有实现, 本文件锁定契约).
AC3 (T1-T2): 温度目标门从 blanket 拒收改为数据驱动
  (有通道且极差>=2C 放行, 否则拒收并说明原因).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# AC1: 新增模型族
# ---------------------------------------------------------------------------

NEW_STRATEGIES = ["ELASTIC_NET", "HUBER_REGRESSION"]


def _frame(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    half = n // 2
    return pd.DataFrame({
        "measurement_event_id": [f"ME::{i}" for i in range(n)],
        "cycle_group_id": ["CG::1"] * half + ["CG::2"] * (n - half),
        "step_type": ["恒流充电"] * (n // 3) + ["恒流放电"] * (n // 3)
                     + ["搁置"] * (n - 2 * (n // 3)),
        "soc_reference_percent": np.linspace(100, 20, n),
        "amplitude_a_u": np.linspace(90, 30, n) + rng.normal(0, 1, n),
        "waveform_rms_a_u": np.linspace(50, 15, n) + rng.normal(0, 0.5, n),
    })


def _view() -> object:
    from battery_workbench.modeling.view import build_fold_training_view

    frame = _frame()
    assigns = pd.DataFrame({
        "measurement_event_id": [f"ME::{i}" for i in range(len(frame))],
        "fold": ["fold1"] * len(frame),
        "role": ["TRAIN"] * (len(frame) // 2) + ["HELD_OUT"] * (len(frame) - len(frame) // 2),
    })
    return build_fold_training_view(
        frame, assigns, fold="fold1",
        features=["amplitude_a_u", "waveform_rms_a_u"],
        target="soc_reference_percent",
    )


def _spec(strategy: str) -> object:
    from battery_workbench.modeling.schemas import ModelSpec

    return ModelSpec(strategy=strategy, dataset_id="DS::t", split_id="SPLIT::t",
                     fold_index=1, selection_id="SEL::t",
                     selected_features=["amplitude_a_u", "waveform_rms_a_u"])


def test_new_strategies_registered_with_fixed_config() -> None:
    """M1: 新策略在白名单且有冻结配置 (无调参)."""
    from battery_workbench.modeling.schemas import FIXED_CONFIGS, STRATEGIES

    for strategy in NEW_STRATEGIES:
        assert strategy in STRATEGIES
        assert strategy in FIXED_CONFIGS


def test_new_strategies_fixed_hyperparameters_recorded() -> None:
    """M1: 冻结超参数显式记录在 FIXED_CONFIGS."""
    from battery_workbench.modeling.schemas import FIXED_CONFIGS

    assert FIXED_CONFIGS["ELASTIC_NET"]["l1_ratio"] == 0.5
    assert "alpha" in FIXED_CONFIGS["ELASTIC_NET"]
    assert "epsilon" in FIXED_CONFIGS["HUBER_REGRESSION"]
    assert "alpha" in FIXED_CONFIGS["HUBER_REGRESSION"]


def test_new_strategies_deterministic_no_random_state_needed() -> None:
    """M1: 确定性策略不需要 random_state."""
    from battery_workbench.modeling.schemas import STOCHASTIC_STRATEGIES

    for strategy in NEW_STRATEGIES:
        assert strategy not in STOCHASTIC_STRATEGIES


def test_new_strategies_fit_predict_deterministic() -> None:
    """M2: fit/predict 确定性且输出有限."""
    from battery_workbench.modeling.engine import fit_model, predict

    for strategy in NEW_STRATEGIES:
        view = _view()
        spec = _spec(strategy)
        p1 = predict(fit_model(view, spec), view.x_held_out)
        p2 = predict(fit_model(view, spec), view.x_held_out)
        np.testing.assert_array_equal(p1, p2)
        assert np.all(np.isfinite(p1))


def test_new_strategies_use_scaled_pipeline() -> None:
    """M2: 新策略走 StandardScaler pipeline (与现有线性族一致)."""
    from battery_workbench.modeling.engine import SCALED_STRATEGIES, fit_model

    for strategy in NEW_STRATEGIES:
        assert strategy in SCALED_STRATEGIES
        assert fit_model(_view(), _spec(strategy)).pipeline is not None


def test_new_strategies_beat_dummy_on_monotone_synthetic() -> None:
    """M3: 单调合成数据上新基线 held-out MAE 优于常数 Dummy (sanity, 非性能声明)."""
    from battery_workbench.modeling.engine import fit_model, predict

    for strategy in NEW_STRATEGIES:
        view = _view()
        preds = predict(fit_model(view, _spec(strategy)), view.x_held_out)
        frame = _frame()
        truth = frame.loc[list(view.held_out_measurement_event_ids),
                          "soc_reference_percent"].to_numpy(dtype=float)
        dummy = float(np.mean(view.y_train.to_numpy()))
        assert float(np.mean(np.abs(preds - truth))) < float(np.mean(np.abs(dummy - truth)))


def test_unknown_strategy_still_rejected() -> None:
    """M4: 未知策略仍被拒绝."""
    import pytest

    with pytest.raises(ValueError, match="unknown strategy"):
        _spec("DEEP_NEURAL_NETWORK_X")


# ---------------------------------------------------------------------------
# AC2: SOH 容量比法离线标签复用验证 (已有实现, 锁定契约)
# ---------------------------------------------------------------------------

def _cycles() -> pd.DataFrame:
    return pd.DataFrame({
        "cycle_index_raw": [1, 2, 3],
        "charge_capacity_ah": [2.0, 1.98, 1.95],
        "discharge_capacity_ah": [2.0, 1.96, 1.90],
    })


def test_soh_reference_selects_first_complete_baseline() -> None:
    """S1: Q_ref 取首个完整放电循环 (非标称猜测)."""
    from battery_workbench.labels.soh import select_reference_capacity

    ref = select_reference_capacity(_cycles())
    assert ref.q_ref_ah == 2.0
    assert ref.reference_cycle_index == 1
    assert ref.reference_capacity_source == "BASELINE_CYCLE"


def test_soh_ratio_formula() -> None:
    """S2: SOH_Q = 100 * Q_discharge / Q_ref."""
    from battery_workbench.labels.soh import compute_soh_reference

    r = compute_soh_reference(q_discharge_ah=1.90, q_ref_ah=2.0)
    assert r.soh_capacity_reference_percent == 95.0
    assert r.soh_reference_quality == "VALID_REFERENCE"
    assert r.soh_label_eligible is True


def test_soh_labels_expose_provenance_columns() -> None:
    """S3: 离线标签暴露 SOH 列 + 来源/方法/版本 provenance."""
    from battery_workbench.labels.soh import build_cycle_soh_labels, select_reference_capacity

    cycles = _cycles()
    out = build_cycle_soh_labels(cycles, reference=select_reference_capacity(cycles))
    assert list(out["soh_capacity_reference_percent"]) == [100.0, 98.0, 95.0]
    assert set(out["soh_reference_cycle_index"]) == {1}
    assert set(out["soh_reference_method"]) == {"CAPACITY_BASELINE_RATIO"}
    assert set(out["soh_reference_quality"]) == {"VALID_REFERENCE"}
    assert list(out["soh_label_eligible"]) == [True, True, True]


def test_soh_readiness_is_data_driven() -> None:
    """S4: 就绪门由真实独立状态数驱动, 不捏造."""
    from battery_workbench.labels.soh import soh_model_readiness

    r2 = soh_model_readiness(independent_state_count=2)
    assert r2.suitable_for_supervised_learning is False
    r30 = soh_model_readiness(independent_state_count=30, min_states=20)
    assert r30.suitable_for_supervised_learning is True


# ---------------------------------------------------------------------------
# AC3: 温度条件放行 (数据驱动门)
# ---------------------------------------------------------------------------

def _temp_gate() -> object:
    from battery_workbench.api import service as service_module

    gate = getattr(service_module, "temperature_target_gate", None)
    assert callable(gate), "temperature_target_gate helper missing"
    return gate


def test_temperature_gate_absent_channel_refused() -> None:
    """T1a: 无温度通道 → 拒收并说明原因."""
    gate = _temp_gate()
    allowed, reason = gate(valid_count=0, temp_range_c=None)
    assert allowed is False
    assert reason


def test_temperature_gate_insufficient_variation_refused() -> None:
    """T1b: 有通道但极差<2C → 拒收并说明原因."""
    gate = _temp_gate()
    allowed, reason = gate(valid_count=3995, temp_range_c=0.5)
    assert allowed is False
    assert "2" in reason


def test_temperature_gate_sufficient_variation_allowed() -> None:
    """T1c: 有通道且极差>=2C → 放行."""
    gate = _temp_gate()
    allowed, _ = gate(valid_count=120, temp_range_c=3.5)
    assert allowed is True

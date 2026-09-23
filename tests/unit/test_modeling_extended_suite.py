"""Models-1: extended fixed baseline suite (SVR / GPR / k-NN).

Fixed hyperparameters, TRAIN-only fitting, determinism, manifest config,
and suite-list wiring — positioned as diagnostic baselines, not a chase
for performance (the Dummy-first rule is unchanged).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.modeling.engine import fit_model, predict
from battery_workbench.modeling.schemas import FIXED_CONFIGS, STRATEGIES, ModelSpec
from battery_workbench.modeling.view import build_fold_training_view

NEW_STRATEGIES = ["SUPPORT_VECTOR_REGRESSION", "GAUSSIAN_PROCESS_REGRESSION", "K_NEAREST_NEIGHBORS"]


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


def _spec(strategy: str) -> ModelSpec:
    return ModelSpec(strategy=strategy, dataset_id="DS::t", split_id="SPLIT::t",
                     fold_index=1, selection_id="SEL::t",
                     selected_features=["amplitude_a_u", "waveform_rms_a_u"])


class TestSuiteRegistration:
    @pytest.mark.parametrize("strategy", NEW_STRATEGIES)
    def test_in_whitelist_with_fixed_config(self, strategy: str) -> None:
        assert strategy in STRATEGIES
        assert strategy in FIXED_CONFIGS

    def test_deterministic_strategies_need_no_random_state(self) -> None:
        from battery_workbench.modeling.schemas import STOCHASTIC_STRATEGIES
        for s in NEW_STRATEGIES:
            assert s not in STOCHASTIC_STRATEGIES

    def test_model_ids_stable_across_construction(self) -> None:
        for s in NEW_STRATEGIES:
            assert _spec(s).model_id == _spec(s).model_id


class TestFitting:
    @pytest.mark.parametrize("strategy", NEW_STRATEGIES)
    def test_fit_predict_is_deterministic(self, strategy: str) -> None:
        view = _view()
        spec = _spec(strategy)
        p1 = predict(fit_model(view, spec), view.x_held_out)
        p2 = predict(fit_model(view, spec), view.x_held_out)
        np.testing.assert_array_equal(p1, p2)
        assert np.all(np.isfinite(p1))

    @pytest.mark.parametrize("strategy", NEW_STRATEGIES)
    def test_beats_dummy_mean_on_heldout(self, strategy: str) -> None:
        """Sanity, not a performance claim: on monotone synthetic data every
        new baseline must beat the constant-mean Dummy on held-out MAE.
        FoldTrainingView carries no held-out y (structural isolation) — the
        test supplies its own truth."""
        view = _view()
        preds = predict(fit_model(view, _spec(strategy)), view.x_held_out)
        frame = _frame()
        truth = frame.loc[list(view.held_out_measurement_event_ids),
                          "soc_reference_percent"].to_numpy(dtype=float)
        dummy = float(np.mean(view.y_train.to_numpy()))
        assert float(np.mean(np.abs(preds - truth))) < float(np.mean(np.abs(dummy - truth)))

    def test_gpr_fixed_kernel_recorded_in_config(self) -> None:
        cfg = FIXED_CONFIGS["GAUSSIAN_PROCESS_REGRESSION"]
        assert "WhiteKernel" in cfg["kernel"]
        assert cfg["hyperparameter_optimization"].startswith("NONE")

    def test_unknown_strategy_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy"):
            _spec("DEEP_NEURAL_NETWORK_X")

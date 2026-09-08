"""BRW-013X V2 downstream E2E — V2 features → dataset → grouped split → model.

Proves the §56/§71/§110 chain: V2 physical feature series (real CELL_001 SWA +
synthetic second battery) become predictors in the existing downstream engines
— exact event join, grouped split with leakage audit, train-only view,
baseline fit, held-out evaluation — with no held-out target consumption.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from battery_workbench.datasets.joins import exact_event_join
from battery_workbench.features.physical_v2 import surface_wave_amplitude
from battery_workbench.modeling.engine import evaluate_predictions, fit_model, predict
from battery_workbench.modeling.schemas import ModelSpec
from battery_workbench.modeling.view import build_fold_training_view
from battery_workbench.splits.engine import (
    assert_no_held_out_consumption,
    build_assignments,
    leakage_audit,
)
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy

REPO = Path(__file__).resolve().parents[2]
EXP = REPO / "data/processed/ultrasound/CELL_001/EXP_001"

pytestmark = pytest.mark.skipif(
    not (EXP / "frames.parquet").is_file(), reason="real CELL_001 artifacts unavailable"
)

PREDICTORS = ["swa_raw_a_u"]


def _build_dataset() -> pd.DataFrame:
    g = zarr.open(str(EXP / "waveforms.zarr"), mode="r")
    frames = np.asarray(g["U001/waveform"][0:400], dtype=np.float64)
    swa = surface_wave_amplitude(frames)["raw"]

    events = pd.read_parquet(
        REPO / "data/processed/multimodal/CELL_001/EXP_001/measurement_events.parquet"
    ).iloc[0:400]
    labels = pd.read_parquet(
        REPO / "data/processed/labels/CELL_001/EXP_001/event_labels.parquet"
    )

    feats = events[["measurement_event_id", "battery_id", "experiment_id"]].copy()
    feats["swa_raw_a_u"] = swa

    label_cols = [
        "measurement_event_id", "cycle_index_raw", "soc_reference_percent",
    ]
    joined = exact_event_join(feats, labels[label_cols], report_surplus=False)
    if isinstance(joined, tuple):  # pragma: no cover
        raise TypeError("unexpected tuple")
    joined = joined[joined["soc_reference_percent"].notna()].reset_index(drop=True)

    # synthetic second battery (grouped split needs >=2 cycle groups); SWA
    # response is a linear function of SOC with different gain — a grouped
    # model must learn from battery 1 only and still transfer.
    rng = np.random.default_rng(42)
    soc2 = rng.uniform(0, 100, size=200)
    df2 = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::CELL_9X::EXP_9X::U001::{i}" for i in range(200)],
            "battery_id": "CELL_9X",
            "experiment_id": "EXP_9X",
            "cycle_index_raw": [1, 2] * 100,
            "soc_reference_percent": soc2,
            "swa_raw_a_u": 0.0004 * soc2 + 0.05 + rng.normal(0, 0.002, 200),
        }
    )
    out = pd.concat([joined, df2], ignore_index=True)
    out["cycle_group_id"] = (
        out["battery_id"].astype(str) + "::CG" + out["cycle_index_raw"].astype(int).astype(str)
    )
    return out


class TestDownstreamChain:
    @pytest.fixture(scope="class")
    def dataset(self) -> pd.DataFrame:
        return _build_dataset()

    def test_exact_join_on_measurement_event_id(self, dataset):
        # join grain is measurement_event_id; real rows keep their event ids
        real = dataset[dataset["battery_id"] == "CELL_001"]
        assert real["measurement_event_id"].str.startswith("ME::CELL_001").all()

    def test_grouped_split_leakage_audit(self, dataset):
        spec = SplitSpec(
            strategy=SplitStrategy.GROUP_HOLDOUT,
            group_column="cycle_group_id",
            dataset_id="DS::BRW013X_E2E",
            split_id="SPLIT::BRW013X_E2E",
            explicit_holdout_groups=["CELL_9X::CG2"],
        )
        assignments = build_assignments(spec, dataset)
        audit = leakage_audit(spec, assignments, dataset)
        assert audit["frame_random_split"] is False
        assert audit["cycle_overlap"] is False
        assert audit["target_used_for_assignment"] is False

        # held-out group never appears in TRAIN
        fold = assignments[assignments["fold"] == "fold1"]
        held = set(fold[fold["role"] != "TRAIN"]["measurement_event_id"])
        train = set(fold[fold["role"] == "TRAIN"]["measurement_event_id"])
        assert not (held & train)
        assert len(held) == 100
        assert_no_held_out_consumption(train_only := dataset[
            dataset["measurement_event_id"].isin(train)
        ], assignments, fold="fold1")
        assert len(train_only) == 500

    def test_grouped_model_fit_and_evaluation(self, dataset):
        spec = SplitSpec(
            strategy=SplitStrategy.LEAVE_ONE_GROUP_OUT,
            group_column="cycle_group_id",
            dataset_id="DS::BRW013X_E2E",
            split_id="SPLIT::BRW013X_E2E",
        )
        assignments = build_assignments(spec, dataset)
        view = build_fold_training_view(
            dataset, assignments, fold="fold3", features=PREDICTORS,
            target="soc_reference_percent",
        )
        # held-out rows excluded from fit
        assert len(view.x_held_out) > 0
        assert set(view.held_out_group_ids) == {"CELL_9X::CG2"}

        spec_model = ModelSpec(
            strategy="RIDGE",
            dataset_id="DS::BRW013X_E2E",
            split_id="SPLIT::BRW013X_E2E",
            fold_index=1,
            selection_id="SEL::BRW013X_E2E",
            selected_features=list(PREDICTORS),
        )
        fitted = fit_model(view, spec_model)
        y_pred = predict(fitted, view.x_held_out)
        # view.held_out_measurement_event_ids carries dataset row positions
        y_true = dataset.loc[view.held_out_measurement_event_ids, "soc_reference_percent"].to_numpy()
        metrics = evaluate_predictions(y_true, y_pred, step_type=None)
        assert metrics["overall"]["n"] == len(y_true)
        assert np.isfinite(metrics["overall"]["MAE"])

    def test_movmean5_variant_policy(self, dataset):
        """C22/C23 in the downstream chain — raw variant eligible; the
        smoothed variant is exploratory by policy and must never be handed
        to the ML-safe selection as a predictor."""
        from battery_workbench.features.gate_calibration import (
            smoothing_split_boundary_warning,
            variant_predictor_eligible,
        )

        assert variant_predictor_eligible("RAW") is True
        ds = dataset.copy()
        ds["swa_source_movmean5"] = (
            ds["swa_raw_a_u"].rolling(5, center=True, min_periods=1).mean()
        )
        assert variant_predictor_eligible("SOURCE_MOVMEAN5") is False
        # multi-cycle dataset → smoothed variant crosses split boundaries
        assert smoothing_split_boundary_warning(
            "SOURCE_MOVMEAN5", ds["cycle_group_id"].unique().tolist()
        ) is not None

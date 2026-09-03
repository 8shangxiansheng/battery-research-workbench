"""BRW-022 SOC Baseline Modeling schemas.

PREDECLARED_FIXED_BASELINE_CONFIG only: with 2 cycle groups there is no
independent validation group, so no hyperparameter tuning of any kind.
Model ids are deterministic over the scientific spec.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, model_validator

MODELING_POLICY_VERSION = "0.1.0"

STRATEGIES = (
    "DUMMY_MEAN",
    "LINEAR_REGRESSION",
    "RIDGE",
    "RANDOM_FOREST",
    "GRADIENT_BOOSTING",
)
STOCHASTIC_STRATEGIES = {"RANDOM_FOREST", "GRADIENT_BOOSTING"}

# PREDECLARED_FIXED_BASELINE_CONFIG (no tuning; frozen for this task pack).
FIXED_CONFIGS: dict[str, dict[str, Any]] = {
    "DUMMY_MEAN": {"strategy": "mean"},
    "LINEAR_REGRESSION": {},
    "RIDGE": {"alpha": 1.0},
    "RANDOM_FOREST": {"n_estimators": 300, "max_depth": None},
    "GRADIENT_BOOSTING": {"n_estimators": 200, "learning_rate": 0.05},
}


class ModelSpec(BaseModel):
    strategy: str
    dataset_id: str
    split_id: str
    fold_index: int
    selection_id: str
    selected_features: list[str]
    random_state: int | None = 42
    policy_version: str = MODELING_POLICY_VERSION
    model_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _defaults(cls, data: dict) -> dict:
        if isinstance(data, dict) and "random_state" not in data:
            data["random_state"] = 42
        return data

    @model_validator(mode="after")
    def _validate_and_id(self) -> ModelSpec:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy: {self.strategy!r} — allowed: {list(STRATEGIES)}")
        if self.strategy in STOCHASTIC_STRATEGIES and self.random_state is None:
            raise ValueError(f"stochastic strategy {self.strategy} requires a fixed random_state")
        if not self.model_id:
            canonical = json.dumps(
                {
                    "policy_version": self.policy_version,
                    "dataset_id": self.dataset_id,
                    "split_id": self.split_id,
                    "fold_index": self.fold_index,
                    "selection_id": self.selection_id,
                    "selected_features": self.selected_features,
                    "strategy": self.strategy,
                    "config": FIXED_CONFIGS[self.strategy],
                    "random_state": self.random_state,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self.model_id = "MODEL::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return self

    @property
    def config(self) -> dict[str, Any]:
        return dict(FIXED_CONFIGS[self.strategy])


class SelectionProvenance(BaseModel):
    analysis_id: str
    selection_id: str
    analysis_mode: Literal["TRAIN_ONLY_ML_SAFE"]
    selection_basis: str
    split_id: str
    fold_index: int
    selected_features: list[str]

"""BRW-020 leakage-safe grouped split schemas.

Random frame/row/measurement_event/SOC-bin splitting is rejected at the
schema layer — a grouped split is the only allowed semantics.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SplitStrategy(str, Enum):
    GROUP_HOLDOUT = "GROUP_HOLDOUT"
    LEAVE_ONE_GROUP_OUT = "LEAVE_ONE_GROUP_OUT"
    K_FOLD_GROUPED = "K_FOLD_GROUPED"
    TRAIN_ONLY = "TRAIN_ONLY"
    NO_VALID_SPLIT = "NO_VALID_SPLIT"


_PROHIBITED_STRATEGIES = {
    "RANDOM_FRAME_SPLIT",
    "RANDOM_ROW_SPLIT",
    "RANDOM_MEASUREMENT_EVENT_SPLIT",
    "SOC_BIN_ROW_SPLIT",
}

SplitUnit = Literal["CYCLE", "EXPERIMENT", "BATTERY"]


class SplitSpec(BaseModel):
    strategy: SplitStrategy
    split_unit: SplitUnit = "CYCLE"
    group_column: str = "cycle_group_id"
    dataset_id: str = ""
    explicit_holdout_groups: list[str] = Field(default_factory=list)
    k: int | None = None
    require_roles: list[str] = Field(default_factory=lambda: ["TRAIN", "VALIDATION"])
    purpose: str = "SCIENTIFIC_EVALUATION"
    split_id: str = ""
    split_version: str = "0.1.0"

    @model_validator(mode="before")
    @classmethod
    def _defaults_and_prohibition(cls, data: dict) -> dict:
        if isinstance(data, dict):
            if data.get("explicit_holdout_groups") is None:
                data["explicit_holdout_groups"] = []
            if "require_roles" not in data or data.get("require_roles") is None:
                data["require_roles"] = ["TRAIN", "VALIDATION"]
        strategy = data.get("strategy")
        if strategy is not None and str(strategy) in _PROHIBITED_STRATEGIES:
            raise ValueError(
                f"prohibited split strategy: {strategy} — grouped splitting only "
                "(FRAME_LEVEL_RANDOM_SPLIT_PROHIBITED)"
            )
        return data

    @model_validator(mode="after")
    def _validate(self) -> SplitSpec:
        # LEAVE_ONE_GROUP_OUT is a held-out limited evaluation (2-role folds);
        # its leave-out group is NOT a model-selection VALIDATION set.
        if self.strategy == SplitStrategy.LEAVE_ONE_GROUP_OUT:
            self.require_roles = ["TRAIN", "HELD_OUT"]
        elif self.strategy == SplitStrategy.K_FOLD_GROUPED:
            self.require_roles = ["TRAIN", "VALIDATION"]
        if self.split_unit == "CYCLE" and self.group_column != "cycle_group_id":
            raise ValueError("CYCLE split unit requires group_column=cycle_group_id")
        if self.strategy == SplitStrategy.K_FOLD_GROUPED and (self.k is None or self.k < 2):
            raise ValueError("K_FOLD_GROUPED requires k >= 2")
        if self.strategy == SplitStrategy.GROUP_HOLDOUT and not self.explicit_holdout_groups:
            raise ValueError("GROUP_HOLDOUT requires explicit_holdout_groups")
        if not self.split_id:
            self.split_id = split_id_for(self)
        return self


def split_id_for(spec: SplitSpec) -> str:
    """Deterministic SPLIT::id from the scientific spec + dataset identity."""
    canonical = json.dumps(
        {
            "strategy": spec.strategy.value,
            "split_unit": spec.split_unit,
            "group_column": spec.group_column,
            "dataset_id": spec.dataset_id,
            "explicit_holdout_groups": sorted(spec.explicit_holdout_groups),
            "k": spec.k,
            "require_roles": spec.require_roles,
            "split_version": spec.split_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "SPLIT::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


class SplitInfeasibleError(ValueError):
    """Requested split is scientifically impossible for the given groups."""

    def __init__(self, message: str, options: list[dict]) -> None:
        self.options = options
        super().__init__(f"{message} | options: {options}")

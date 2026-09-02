"""BRW-021 Feature Analysis Workbench schemas.

Two strictly separated modes:
  EXPLORATORY_FULL_DATA — full eligible data + labels; any selection made
    from full-data results is marked ml_safe_selection=False.
  TRAIN_ONLY_ML_SAFE — requires split_id + fold_index; structurally only
    TRAIN rows are visible (see engine.train_feature_input).

Feature identity is locator-based: feature_name[@gate_id]; no new feature
names are invented.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ANALYSIS_VERSION = "0.1.0"
POLICY_VERSION = "0.1.0"

FORBIDDEN_CANDIDATES = {
    "soc_reference_percent",
    "soh_capacity_reference_percent",
    "soc_dod_percent",
    "soc_integral_unbounded_percent",
    "soc_reference_capacity_ah",
    "soh_reference_capacity_ah",
    "capacity_ah",
    "cycle_index_raw",
    "soh_reference_cycle_index",
    "capacity_retention_percent",
}


class AnalysisMode(str, Enum):
    EXPLORATORY_FULL_DATA = "EXPLORATORY_FULL_DATA"
    TRAIN_ONLY_ML_SAFE = "TRAIN_ONLY_ML_SAFE"


class SelectionRequest(BaseModel):
    requested: bool = False
    mode: Literal["USER_EXPLICIT", "TRAIN_ONLY_RULE_BASED"] = "USER_EXPLICIT"
    user_features: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


class FeatureAnalysisSpec(BaseModel):
    analysis_mode: AnalysisMode
    target: str
    candidate_features: list[str] = Field(default_factory=list)
    split_id: str | None = None
    fold_index: int | None = None
    subgroup_by: list[str] = Field(default_factory=lambda: ["step_type", "cycle"])
    methods: list[str] = Field(default_factory=lambda: ["descriptive", "pearson", "spearman"])
    selection: SelectionRequest = Field(default_factory=SelectionRequest)
    analysis_version: str = ANALYSIS_VERSION
    policy_version: str = POLICY_VERSION
    analysis_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: dict) -> dict:
        if isinstance(data, dict):
            mode = data.get("analysis_mode")
            if isinstance(mode, AnalysisMode):
                data["analysis_mode"] = mode.value
            sel = data.get("selection")
            if isinstance(sel, dict) and "requested" not in sel:
                sel["requested"] = True
        return data

    @model_validator(mode="after")
    def _validate_and_id(self) -> FeatureAnalysisSpec:
        if self.target in FORBIDDEN_CANDIDATES and not self.target.endswith(
            ("soc_reference_percent", "soh_capacity_reference_percent")
        ):
            raise ValueError(f"invalid target: {self.target}")
        illegal = [f for f in self.candidate_features if f in FORBIDDEN_CANDIDATES]
        if illegal:
            raise ValueError(f"forbidden / target-leakage candidate features: {illegal}")
        for f in self.candidate_features:
            if f == self.target:
                raise ValueError(f"target {self.target!r} cannot be a candidate feature")
        if self.analysis_mode == AnalysisMode.TRAIN_ONLY_ML_SAFE:
            if not self.split_id:
                raise ValueError("TRAIN_ONLY_ML_SAFE requires split_id")
            if self.fold_index is None:
                raise ValueError("TRAIN_ONLY_ML_SAFE requires fold_index")
        if (
            self.selection.requested
            and self.selection.mode == "TRAIN_ONLY_RULE_BASED"
            and self.analysis_mode != AnalysisMode.TRAIN_ONLY_ML_SAFE
        ):
            raise ValueError("TRAIN_ONLY_RULE_BASED selection requires TRAIN_ONLY_ML_SAFE mode")
        if not self.analysis_id:
            canonical = json.dumps(
                {
                    "analysis_version": self.analysis_version,
                    "analysis_mode": self.analysis_mode.value,
                    "target": self.target,
                    "candidate_features": self.candidate_features,
                    "split_id": self.split_id,
                    "fold_index": self.fold_index,
                    "subgroup_by": self.subgroup_by,
                    "methods": self.methods,
                    "policy_version": self.policy_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self.analysis_id = "AN::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return self

    @property
    def ml_safe_selection(self) -> bool:
        return (
            self.analysis_mode == AnalysisMode.TRAIN_ONLY_ML_SAFE
            and self.split_id is not None
            and self.fold_index is not None
        )


def selection_id_for(analysis_id: str, spec: FeatureAnalysisSpec, resolved: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "analysis_id": analysis_id,
            "selection_policy_version": POLICY_VERSION,
            "selection": spec.selection.model_dump(mode="json"),
            "resolved": resolved,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "SEL::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]

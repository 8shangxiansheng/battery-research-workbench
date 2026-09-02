"""BRW-018 GateSpec schemas.

A GateSpec selects a sample window of a waveform for analysis. Raw waveforms
are never modified. The same feature algorithms apply to any gate; features
are distinguished by ``feature_name + gate_id``, never by new feature names.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator


class GateScope(str, Enum):
    GLOBAL_EXPERIMENT_GATE = "GLOBAL_EXPERIMENT_GATE"
    ANALYSIS_SLICE_GATE = "ANALYSIS_SLICE_GATE"
    EXPLORATORY_FRAME_GATE = "EXPLORATORY_FRAME_GATE"


class GateSpec(BaseModel):
    gate_name: str
    start_sample: int
    end_sample: int
    scope: GateScope = GateScope.ANALYSIS_SLICE_GATE
    waveform_length: int
    semantic_role: Literal[
        "ANALYSIS_WINDOW", "REFERENCE_PULSE", "RECEIVED_PULSE", "ECHO_WINDOW"
    ] = "ANALYSIS_WINDOW"
    source: str = ""
    created_by: str = ""
    gate_version: str = "0.1.0"
    gate_id: str = ""

    @model_validator(mode="after")
    def _validate_and_id(self) -> GateSpec:
        if not (0 <= self.start_sample < self.end_sample <= self.waveform_length):
            raise ValueError(
                f"invalid gate bounds: 0 <= start({self.start_sample}) < "
                f"end({self.end_sample}) <= length({self.waveform_length})"
            )
        if not self.gate_id:
            canonical = json.dumps(
                {
                    "gate_name": self.gate_name,
                    "start_sample": self.start_sample,
                    "end_sample": self.end_sample,
                    "scope": self.scope.value,
                    "waveform_length": self.waveform_length,
                    "gate_version": self.gate_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self.gate_id = "GATE::" + hashlib.sha256(canonical.encode()).hexdigest()[:20]
        return self

    @property
    def not_ml_ready(self) -> bool:
        return self.scope == GateScope.EXPLORATORY_FRAME_GATE


class TOFDefinitionSpec(BaseModel):
    tof_definition_id: str = ""
    mode: Literal["ABSOLUTE_TIME_ZERO", "BETWEEN_GATES"]
    reference_gate_id: str | None = None
    received_gate_id: str | None = None
    arrival_gate_id: str | None = None
    physical_interpretation_confirmed: bool = False
    definition_note: str = ""
    version: str = "0.1.0"

    @model_validator(mode="after")
    def _validate_and_id(self) -> TOFDefinitionSpec:
        if (
            self.mode == "BETWEEN_GATES"
            and self.physical_interpretation_confirmed
            and not (self.reference_gate_id and self.received_gate_id)
        ):
            raise ValueError(
                "confirmed BETWEEN_GATES requires reference_gate_id and received_gate_id"
            )
        if not self.tof_definition_id:
            canonical = json.dumps(
                self.model_dump(mode="json", exclude={"tof_definition_id"}),
                sort_keys=True,
                separators=(",", ":"),
            )
            self.tof_definition_id = (
                "TOFDEF::" + hashlib.sha256(canonical.encode()).hexdigest()[:20]
            )
        return self


def gate_set_ml_ready(gates: list[GateSpec]) -> bool:
    """A gate set is ML-ready only when no EXPLORATORY_FRAME_GATE is present."""
    return not any(g.not_ml_ready for g in gates)


# Canonical slicing semantics, fixed by policy (07_GATE_POLICY.md).
GATE_SLICING_SEMANTICS = "[start_sample:end_sample)"


def gate_set_warnings(gates: list[GateSpec]) -> list[str]:
    """Advisory warnings for a gate set (e.g. duplicate gate names)."""
    names = [g.gate_name for g in gates]
    warnings: list[str] = []
    for name in sorted({n for n in names if names.count(n) > 1}):
        warnings.append(f"DUPLICATE_GATE_NAME: {name}")
    return warnings


def gate_set_from_config(
    config: dict, *, waveform_length: int
) -> tuple[list[GateSpec], TOFDefinitionSpec | None, str, list[str]]:
    """Load a task-pack example-YAML-shaped config into specs.

    Expected shape:
      gate_set: {name, selection_basis, gates: [{gate_name, start_sample,
        end_sample, semantic_role, scope}, ...]}
      features: [feature_name, ...]
      tof_definition: {mode, physical_interpretation_confirmed, ...} (optional)

    ``waveform_length`` is injected for bounds validation; ``source`` records
    the config name for provenance.
    """
    gate_set = config.get("gate_set", {})
    gates = [
        GateSpec(
            waveform_length=waveform_length,
            source=f"config:{gate_set.get('name', '')}",
            created_by="gate_set_from_config",
            **gate,
        )
        for gate in gate_set.get("gates", [])
    ]
    tof_raw = config.get("tof_definition")
    tof_def = TOFDefinitionSpec(**tof_raw) if tof_raw else None
    basis = gate_set.get("selection_basis", "SIGNAL_ONLY")
    features = list(config.get("features", []))
    return gates, tof_def, basis, features

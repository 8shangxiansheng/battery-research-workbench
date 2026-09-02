"""BRW-019 T01-T07 + T25-T26: AnalysisPlan validation, plan id, DAG, gate set id."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from battery_workbench.gates.persistence import build_gate_set_id
from battery_workbench.gates.schemas import GateScope, GateSpec
from battery_workbench.orchestrator.dag import (
    CycleDetectedError,
    downstream_closure,
    topological_order,
)
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject


def _plan(**overrides) -> AnalysisPlan:
    values = {
        "profile": "BUILD_DATASET",
        "project": PlanProject(battery_id="CELL_001", experiment_id="EXP_001"),
        "stages": ["MEASUREMENT_EVENTS", "PARAMETER_SET"],
        "features": {"selected_features": ["amplitude_a_u"]},
        "target": "soc_reference_percent",
    }
    values.update(overrides)
    return AnalysisPlan(**values)


# --- T01-T04: AnalysisPlan ---


def test_t01_plan_validation_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(project=PlanProject(battery_id="B", experiment_id="E"))


def test_t02_plan_id_deterministic() -> None:
    assert _plan().plan_id == _plan().plan_id
    assert _plan().plan_id.startswith("PLAN::")


def test_t03_presentation_only_change_keeps_plan_id() -> None:
    base = _plan()
    dry = _plan(execution={"dry_run": True, "reuse_existing": True})
    no_reuse = _plan(execution={"dry_run": False, "reuse_existing": False})
    assert base.execution.dry_run is False  # default
    assert base.plan_id == dry.plan_id == no_reuse.plan_id


def test_t04_scientific_choice_change_changes_plan_id() -> None:
    base = _plan()
    other_features = _plan(features={"selected_features": ["waveform_rms_a_u"]})
    other_target = _plan(target="soh_capacity_reference_percent")
    other_params = _plan(parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"})
    assert base.plan_id != other_features.plan_id
    assert base.plan_id != other_target.plan_id
    assert base.plan_id != other_params.plan_id


# --- T05-T07: DAG ---


def test_t05_deterministic_node_order() -> None:
    deps = {"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}
    order1 = topological_order(["D", "C", "B", "A"], deps)
    order2 = topological_order(["A", "D", "B", "C"], deps)
    assert order1 == order2
    assert order1.index("A") < order1.index("B") < order1.index("D")
    assert order1.index("C") < order1.index("D")


def test_t06_dependency_cycle_rejected() -> None:
    deps = {"A": ["B"], "B": ["A"]}
    with pytest.raises(CycleDetectedError):
        topological_order(["A", "B"], deps)


def test_t07_unknown_stage_rejected() -> None:
    with pytest.raises(ValidationError):
        _plan(stages=["MEASUREMENT_EVENTS", "TRAIN_MODEL"])


def test_downstream_closure() -> None:
    deps = {"A": [], "B": ["A"], "C": ["B"], "D": ["A"]}
    assert downstream_closure("A", deps) == {"B", "C", "D"}
    assert downstream_closure("C", deps) == set()


# --- T25-T26: gate set id ---


def _gate(name: str, end: int = 200) -> GateSpec:
    return GateSpec(
        gate_name=name,
        start_sample=0,
        end_sample=end,
        scope=GateScope.ANALYSIS_SLICE_GATE,
        waveform_length=1250,
    )


def test_t25_gate_set_id_deterministic() -> None:
    assert build_gate_set_id([_gate("a")]) == build_gate_set_id([_gate("a")])
    assert build_gate_set_id([_gate("a")]).startswith("GATESET::")


def test_t26_changed_gate_set_changes_id() -> None:
    assert build_gate_set_id([_gate("a")]) != build_gate_set_id([_gate("a", end=201)])
    assert build_gate_set_id([_gate("a")]) != build_gate_set_id([_gate("a"), _gate("b", 300)])

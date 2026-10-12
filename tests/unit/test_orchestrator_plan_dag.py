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
from battery_workbench.orchestrator.nodes import (
    DatasetNode,
    MeasurementEventsNode,
    SocModelingNode,
)
from battery_workbench.orchestrator.resolver import _manifest_matches
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
    other_temperature_channel = _plan(measurement_events={"temperature_channel_id": "T2"})
    assert base.plan_id != other_features.plan_id
    assert base.plan_id != other_target.plan_id
    assert base.plan_id != other_params.plan_id
    assert base.plan_id != other_temperature_channel.plan_id


def test_measurement_event_reuse_requires_the_selected_temperature_channel() -> None:
    plan = _plan(measurement_events={"temperature_channel_id": "T2"})
    requirements = MeasurementEventsNode().requirements(plan, {})
    manifest = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "builder_version": "0.5.1",
        "temperature_channel_id": "T1",
    }

    assert _manifest_matches(manifest, requirements, None) == (
        False,
        "selection mismatch on temperature_channel_id",
    )
    manifest["temperature_channel_id"] = "T2"
    assert _manifest_matches(manifest, requirements, None) == (
        True,
        "manifest+identity+status+provenance verified",
    )


@pytest.mark.parametrize(
    ("target", "reason_fragment"),
    [
        ("temperature_c", "BLOCKED_BY_VALIDATION"),
        ("arbitrary_target", "unsupported target"),
    ],
)
def test_dataset_node_blocks_targets_without_a_ready_dataset_contract(
    target: str, reason_fragment: str
) -> None:
    plan = _plan(target=target)
    node = DatasetNode()

    readiness = node.validate_readiness(plan, {})

    assert not readiness.ok
    assert reason_fragment in readiness.reason


def test_blocked_target_is_not_resolved_as_an_existing_soh_dataset(tmp_path) -> None:
    plan = _plan(target="temperature_c")

    ref, reason = DatasetNode().resolve_existing_output(plan, {}, tmp_path)

    assert ref is None
    assert "BLOCKED_BY_VALIDATION" in reason


def test_temperature_target_never_uses_soh_dataset_family() -> None:
    plan = _plan(target="temperature_c")

    assert "/UNSUPPORTED_TARGET" in DatasetNode().output_rel_dir(plan)


def test_soh_target_remains_descriptive_dataset_but_is_not_model_ready() -> None:
    plan = _plan(target="soh_capacity_reference_percent")
    readiness = DatasetNode().validate_readiness(plan, {})

    assert readiness.ok
    assert "/SOH_CAPACITY" in DatasetNode().output_rel_dir(plan)


@pytest.mark.parametrize("target", ["temperature_c", "soh_capacity_reference_percent", "other"])
def test_soc_modeling_node_rejects_non_soc_targets_before_cache_lookup(
    target: str, tmp_path
) -> None:
    plan = _plan(target=target)
    node = SocModelingNode()

    readiness = node.validate_readiness(plan, {})
    ref, reason = node.resolve_existing_output(plan, {}, tmp_path)

    assert not readiness.ok
    assert "only supports soc_reference_percent" in readiness.reason
    assert ref is None
    assert "only supports soc_reference_percent" in reason


# --- T05-T07: DAG ---


def test_t05_deterministic_node_order() -> None:
    deps = {"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}
    order1 = topological_order(["D", "C", "B", "A"], deps)
    order2 = topological_order(["A", "D", "B", "C"], deps)
    assert order1 == order2
    assert order1.index("A") < order1.index("B") < order1.index("D")
    assert order1.index("C") < order1.index("D")


def test_dataset_requires_canonical_tof_stage_when_selected() -> None:
    from battery_workbench.orchestrator.engine import (
        _dependency_map_for_plan,
        _required_dependencies,
        _stages_for_plan,
    )

    tof_plan = _plan(
        stages=["ULTRASOUND_FEATURES", "REFERENCE_LABELS", "PARAMETER_SET", "DATASET"],
        features={"selected_features": ["tof_us", "waveform_rms_a_u"]},
    )
    non_tof_plan = _plan(
        stages=["ULTRASOUND_FEATURES", "REFERENCE_LABELS", "PARAMETER_SET", "DATASET"],
        features={"selected_features": ["waveform_rms_a_u"]},
    )

    assert "CANONICAL_TOF_FEATURES" in _required_dependencies("DATASET", tof_plan)
    assert "CANONICAL_TOF_FEATURES" not in _required_dependencies("DATASET", non_tof_plan)
    stages = _stages_for_plan(tof_plan)
    assert {
        "ULTRASOUND_CANONICAL",
        "TIME_ANCHOR",
        "ULTRASOUND_TIMESTAMPS",
        "SYNCHRONIZATION",
        "MEASUREMENT_EVENTS",
        "ANALYSIS_SLICE",
        "ULTRASOUND_FEATURES",
        "REFERENCE_LABELS",
        "PARAMETER_SET",
        "DATASET",
        "CANONICAL_TOF_FEATURES",
    }.issubset(stages)
    order = topological_order(stages, _dependency_map_for_plan(tof_plan))
    assert order.index("ULTRASOUND_FEATURES") < order.index("CANONICAL_TOF_FEATURES")
    assert order.index("PARAMETER_SET") < order.index("CANONICAL_TOF_FEATURES")
    assert order.index("CANONICAL_TOF_FEATURES") < order.index("DATASET")


def test_selected_tof_stage_expands_its_feature_and_parameter_dependencies() -> None:
    from battery_workbench.orchestrator.engine import _stages_for_plan

    plan = _plan(
        profile="FULL_PRE_MODEL",
        stages=["PARAMETER_SET", "DATASET", "SPLIT", "FEATURE_ANALYSIS"],
        features={"selected_features": ["tof_us", "waveform_rms_a_u"]},
        feature_analysis={
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "target": "soc_reference_percent",
            "split_id": "SPLIT::example",
            "fold_index": 1,
        },
    )

    stages = set(_stages_for_plan(plan))

    assert {
        "ANALYSIS_SLICE",
        "ULTRASOUND_FEATURES",
        "PARAMETER_SET",
        "CANONICAL_TOF_FEATURES",
    }.issubset(stages)


def test_evaluation_split_expands_required_dataset_dependency_closure() -> None:
    from battery_workbench.orchestrator.engine import _stages_for_plan

    plan = _plan(
        profile="EVALUATION_SPLIT",
        stages=["DATASET", "SPLIT"],
        features={"selected_features": ["tof_us", "waveform_rms_a_u"]},
    )

    stages = set(_stages_for_plan(plan))

    assert {
        "ELECTRICAL_CANONICAL",
        "ULTRASOUND_CANONICAL",
        "TIME_ANCHOR",
        "ULTRASOUND_TIMESTAMPS",
        "SYNCHRONIZATION",
        "MEASUREMENT_EVENTS",
        "ANALYSIS_SLICE",
        "ULTRASOUND_FEATURES",
        "REFERENCE_LABELS",
        "PARAMETER_SET",
        "CANONICAL_TOF_FEATURES",
        "DATASET",
        "SPLIT",
    }.issubset(stages)


def test_evaluation_split_does_not_require_optional_tof_for_non_tof_dataset() -> None:
    from battery_workbench.orchestrator.engine import _stages_for_plan

    plan = _plan(
        profile="EVALUATION_SPLIT",
        stages=["DATASET", "SPLIT"],
        features={"selected_features": ["waveform_rms_a_u"]},
    )

    assert "CANONICAL_TOF_FEATURES" not in _stages_for_plan(plan)


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

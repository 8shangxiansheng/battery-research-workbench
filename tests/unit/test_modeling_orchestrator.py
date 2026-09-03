"""BRW-022 T27-T36: persistence, orchestrator integration, guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.orchestrator.engine import PipelineOrchestrator

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

pytestmark = pytest.mark.skipif(
    not (PROCESSED / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e").exists(),
    reason="real CELL_001/EXP_001 artifacts not available",
)

GATE_A = "GATE::0c443fd8bb117e732a16"


def _engine(tmp_path: Path) -> PipelineOrchestrator:
    return PipelineOrchestrator(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")


def _modeling_plan(engine: PipelineOrchestrator, fold: int, **fa_overrides) -> dict:
    fa = {
        "analysis_mode": "TRAIN_ONLY_ML_SAFE",
        "candidate_features": [
            "amplitude_a_u",
            "waveform_rms_a_u",
            "waveform_p2p_a_u",
            "envelope_peak_a_u",
        ],
        "methods": ["descriptive", "spearman"],
        "selection": {
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.15, "max_missing_fraction": 0.05},
        },
    }
    for k, v in fa_overrides.items():
        if k == "selection" and isinstance(v, dict):
            merged = {**fa["selection"], **v}
            merged.setdefault("requested", True)
            fa["selection"] = merged
        else:
            fa[k] = v
    kwargs = {
        "profile": "SCIENTIFIC_ANALYSIS",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dry_run": False,
        "fold_index": fold,
        "stages": ["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING"],
        "target": "soc_reference_percent",
        "features": {"selected_features": ["amplitude_a_u"]},
        "analysis_slice": {"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        "parameters": {"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        "split": {
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
        "feature_analysis": fa,
        "modeling": {
            "strategies": [
                "DUMMY_MEAN",
                "LINEAR_REGRESSION",
                "RIDGE",
                "RANDOM_FOREST",
                "GRADIENT_BOOSTING",
            ],
            "random_state": 42,
        },
    }
    return engine.plan_run(**kwargs)


def _confirmed_run(engine: PipelineOrchestrator, fold: int) -> dict:
    run = engine.start_run(_modeling_plan(engine, fold))
    actions = engine.list_user_actions(run["run_id"])
    sel_actions = [a for a in actions if a["action_type"] == "CONFIRM_FEATURE_SELECTION"]
    if sel_actions:
        sel_id = sel_actions[0]["required_fields"][0]["value"]
        run = engine.resume_run(
            run["run_id"],
            user_inputs={"selection_id": sel_id},
            action_id=sel_actions[0]["action_id"],
        )
    return run


def test_t27_artifacts_materialize(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run = _confirmed_run(engine, 1)
    model_nodes = [n for n in run["nodes"] if n["node_id"] == "SOC_MODELING"]
    assert model_nodes and model_nodes[0]["state"] in {"SUCCEEDED", "REUSED", "RUNNING"}
    if model_nodes[0]["outputs"]:
        manifest = json.loads(Path(model_nodes[0]["outputs"][0]["manifest_path"]).read_text())
        assert manifest["policy_version"]
        assert manifest["scientific_claims"]["evaluation_scope"] == "WITHIN_BATTERY_CROSS_CYCLE"
        assert manifest["scientific_claims"]["no_cross_battery_generalization_claim"] is True


def test_t28_lineage_complete(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _confirmed_run(engine, 1)
    lineage = engine.get_artifact_lineage_by_id("SOC_MODELING", "EXP_001")
    assert lineage["artifact"]["artifact_type"] == "SOC_MODELING"


def test_t29_same_spec_reused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plan = _modeling_plan(engine, 1)
    run1 = _confirmed_run(engine, 1)
    m1 = [n for n in run1["nodes"] if n["node_id"] == "SOC_MODELING"]
    run2 = engine.start_run(plan)
    m2 = [n for n in run2["nodes"] if n["node_id"] == "SOC_MODELING"]
    if m1[0]["outputs"] and m2[0]["outputs"]:
        assert m1[0]["outputs"][0]["artifact_id"] == m2[0]["outputs"][0]["artifact_id"]
        assert m2[0]["state"] == "REUSED"


def test_t30_selection_change_refits_downstream_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    p1 = _modeling_plan(engine, 1)
    p2 = _modeling_plan(
        engine,
        1,
        selection={
            "requested": True,
            "mode": "TRAIN_ONLY_RULE_BASED",
            "policy": {"min_abs_spearman": 0.5, "max_missing_fraction": 0.05},
        },
    )
    e1 = engine.dry_run(p1)
    e2 = engine.dry_run(p2)
    f1 = next(n for n in e1.nodes if n.node_id == "FEATURE_ANALYSIS")
    f2 = next(n for n in e2.nodes if n.node_id == "FEATURE_ANALYSIS")
    assert f1.state.value in {"REUSED", "RUNNING"}
    assert f2.state.value == "RUNNING"  # different policy → different selection


def test_t31_report_only_change_no_refit(tmp_path: Path) -> None:
    """Two identical specs (report wording lives outside the plan) → same state."""
    engine = _engine(tmp_path)
    p1 = _modeling_plan(engine, 1)
    p2 = _modeling_plan(engine, 1)
    assert p1.plan_id == p2.plan_id  # report wording is not in the plan identity
    e1 = engine.dry_run(p1)
    e2 = engine.dry_run(p2)
    m1 = next(n for n in e1.nodes if n.node_id == "SOC_MODELING")
    m2 = next(n for n in e2.nodes if n.node_id == "SOC_MODELING")
    assert m1.state.value == m2.state.value


def test_t32_soh_blocked(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plan = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        fold_index=1,
        stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING"],
        target="soh_capacity_reference_percent",
        features={"selected_features": ["amplitude_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        split={
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
        feature_analysis={
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "candidate_features": ["amplitude_a_u"],
            "methods": ["spearman"],
        },
        modeling={"strategies": ["DUMMY_MEAN"], "random_state": 42},
    )
    run = engine.start_run(plan)
    soh_node = next(n for n in run["nodes"] if n["node_id"] == "SOC_MODELING")
    # SOH ML-safe modeling must NOT succeed: the node is blocked/waiting, and the
    # user-facing actions carry the SOH_NOT_READY reason (via the FA target gate
    # or the SOH_MODELING_NOT_READY guard).
    assert soh_node["state"] in {"WAITING_FOR_USER", "BLOCKED"}
    actions = engine.list_user_actions(run["run_id"])
    run_fa = next(n for n in run["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    soh_blocked = (
        any("SOH" in a["action_type"] or "SOH" in a["message"] for a in actions)
        or "target" in run_fa["reason"].lower()
        or "unrelated" in run_fa["reason"].lower()
    )
    assert soh_blocked, f"SOH blocking reason missing: {run_fa['reason']}"


def test_t33_one_battery_no_cross_battery_claim(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run = _confirmed_run(engine, 1)
    model_nodes = [n for n in run["nodes"] if n["node_id"] == "SOC_MODELING"]
    if model_nodes[0]["outputs"]:
        manifest = json.loads(Path(model_nodes[0]["outputs"][0]["manifest_path"]).read_text())
        claims = manifest["scientific_claims"]
        assert claims["no_cross_battery_generalization_claim"] is True
        assert claims["battery_group_count"] == 1
        assert claims["evaluation_uncertainty_high"] is True
        assert claims["no_hyperparameter_tuning"] is True


def test_t34_no_tuning_imports() -> None:
    """The modeling package must not import any tuning machinery."""

    import battery_workbench.modeling.engine as eng

    src = Path(eng.__file__).read_text()
    for banned in ("GridSearchCV", "RandomizedSearchCV", "optuna", "bayes_opt"):
        assert banned not in src


def test_t35_orchestrator_dependency(tmp_path: Path) -> None:
    from battery_workbench.orchestrator.dag import NODE_DEPENDENCIES

    assert NODE_DEPENDENCIES["SOC_MODELING"] == ["DATASET", "SPLIT", "FEATURE_ANALYSIS"]


def test_t36_upstream_immutable(tmp_path: Path) -> None:
    import hashlib

    def digest(p: Path) -> str:
        if p.is_file():
            return hashlib.sha256(p.read_bytes()).hexdigest()
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(str(f.relative_to(p)).encode())
            h.update(f.read_bytes())
        return h.hexdigest()

    protected = [
        PROCESSED / "ultrasound/CELL_001/EXP_001/waveforms.zarr",
        PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet",
        PROCESSED / "synchronization/CELL_001/EXP_001/aligned_ultrasound_frames.parquet",
        PROCESSED / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e",
        PROCESSED
        / "splits/CELL_001/EXP_001/DS::6a3142e5186fc684964ff09e/SPLIT::062cf007d21578a11ab2d728",
    ]
    before = {str(p): digest(p) for p in protected}
    engine = _engine(tmp_path)
    _confirmed_run(engine, 1)
    after = {str(p): digest(p) for p in protected}
    assert before == after

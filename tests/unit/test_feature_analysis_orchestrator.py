"""BRW-021 T37-T44: orchestrator integration + upstream immutability."""

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


def _engine(tmp_path: Path) -> PipelineOrchestrator:
    return PipelineOrchestrator(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")


def _exploratory_plan(engine: PipelineOrchestrator, **overrides) -> dict:
    kwargs = {
        "profile": "SCIENTIFIC_ANALYSIS",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dry_run": False,
        "stages": ["FEATURE_LABEL_ANALYSIS", "FEATURE_ANALYSIS"],
        "target": "soc_reference_percent",
        "analysis_slice": {"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        "parameters": {"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        "feature_analysis": {
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "candidate_features": [
                "amplitude_a_u",
                "waveform_rms_a_u",
                "tof_us",
            ],
            "methods": ["descriptive", "pearson", "spearman"],
        },
    }
    kwargs.update(overrides)
    return engine.plan_run(**kwargs)


def test_t39_exploratory_orchestrator_path(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run = engine.start_run(_exploratory_plan(engine))
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["FEATURE_LABEL_ANALYSIS"] in {"REUSED", "SUCCEEDED"}
    assert states["FEATURE_ANALYSIS"] in {"REUSED", "SUCCEEDED"}
    fa = next(n for n in run["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    ref = fa["outputs"][0]
    manifest = json.loads(Path(ref["manifest_path"]).read_text())
    assert manifest["analysis_mode"] == "EXPLORATORY_FULL_DATA"
    assert manifest["target"] == "soc_reference_percent"
    assert manifest["fold_index"] is None


def test_t40_ml_safe_dataset_split_feature_analysis(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plan = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS"],
        target="soc_reference_percent",
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
            "fold_index": 1,
            "candidate_features": ["amplitude_a_u", "waveform_rms_a_u"],
            "methods": ["descriptive", "spearman"],
        },
    )
    run = engine.start_run(plan)
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["SPLIT"] in {"REUSED", "SUCCEEDED"}
    assert states["FEATURE_ANALYSIS"] in {"REUSED", "SUCCEEDED"}
    fa = next(n for n in run["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    manifest = json.loads(Path(fa["outputs"][0]["manifest_path"]).read_text())
    assert manifest["split_id"] == "SPLIT::062cf007d21578a11ab2d728"
    assert manifest["fold_index"] == 1
    assert manifest["held_out_target_accessed"] is False


def test_t41_existing_analysis_reused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plan = _exploratory_plan(engine)
    run1 = engine.start_run(plan)
    run2 = engine.start_run(plan)
    a1 = next(n for n in run1["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    a2 = next(n for n in run2["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    assert a1["state"] in {"REUSED", "SUCCEEDED"}
    assert a2["state"] == "REUSED"
    assert a1["outputs"][0]["artifact_id"] == a2["outputs"][0]["artifact_id"]


def test_t42_fold_change_reevaluates(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    common = {
        "profile": "SCIENTIFIC_ANALYSIS",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dry_run": False,
        "stages": ["DATASET", "SPLIT", "FEATURE_ANALYSIS"],
        "target": "soc_reference_percent",
        "features": {"selected_features": ["amplitude_a_u"]},
        "analysis_slice": {"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        "parameters": {"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        "split": {
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
        "feature_analysis": {
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "candidate_features": ["amplitude_a_u"],
            "methods": ["spearman"],
        },
    }
    p1 = engine.plan_run(fold_index=1, **common)
    p2 = engine.plan_run(fold_index=2, **common)
    run1 = engine.start_run(p1)
    run2 = engine.start_run(p2)
    a1 = next(n for n in run1["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    a2 = next(n for n in run2["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    assert a1["state"] in {"REUSED", "SUCCEEDED"}
    assert a2["state"] in {"REUSED", "SUCCEEDED"}
    m1 = json.loads(Path(a1["outputs"][0]["manifest_path"]).read_text())
    m2 = json.loads(Path(a2["outputs"][0]["manifest_path"]).read_text())
    assert m1["fold_index"] == 1 and m2["fold_index"] == 2
    assert m1["analysis_id"] != m2["analysis_id"]


def test_t43_commit_selection_requires_user_action(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    gate_a = "GATE::0c443fd8bb117e732a16"  # real primary-signal gate (BRW-018)
    plan = _exploratory_plan(
        engine,
        feature_analysis={
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "candidate_features": [f"amplitude_a_u@{gate_a}"],
            "methods": ["spearman"],
            "selection": {
                "requested": True,
                "mode": "USER_EXPLICIT",
                "user_features": [f"amplitude_a_u@{gate_a}"],
            },
        },
    )
    run = engine.start_run(plan)
    fa = next(n for n in run["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    assert fa["state"] == "WAITING_FOR_USER"
    actions = engine.list_user_actions(run["run_id"])
    assert any(a["action_type"] == "CONFIRM_FEATURE_SELECTION" for a in actions)


def test_t44_no_automatic_dataset_rebuild(tmp_path: Path) -> None:
    """After selection commit, the plan never loops back to DATASET."""
    engine = _engine(tmp_path)
    plan = _exploratory_plan(engine)
    run = engine.start_run(plan)
    node_ids = [n["node_id"] for n in run["nodes"]]
    assert node_ids.count("DATASET") == 0  # dataset not rebuilt by analysis
    assert node_ids.count("FEATURE_ANALYSIS") == 1
    # and the selection is stored, waiting for user confirmation only
    fa = next(n for n in run["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    manifest = json.loads(Path(fa["outputs"][0]["manifest_path"]).read_text())
    if manifest.get("selection", {}).get("requested"):
        assert manifest["selection"]["commit_status"] == "WAITING_FOR_USER"


def test_t38_upstream_immutable(tmp_path: Path) -> None:
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
        PROCESSED / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e",
        PROCESSED
        / "splits/CELL_001/EXP_001/DS::6a3142e5186fc684964ff09e/SPLIT::062cf007d21578a11ab2d728",
    ]
    before = {str(p): digest(p) for p in protected}
    engine = _engine(tmp_path)
    engine.start_run(_exploratory_plan(engine))
    after = {str(p): digest(p) for p in protected}
    assert before == after

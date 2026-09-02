"""BRW-019 T15-T26 + T32-T44: orchestrator execution, resume, invalidation,
scientific safeguards, service facade.

Strategy: the engine is exercised through the REAL node registry. Real
CELL_001/EXP_001 manifests (read-only) drive dry-run/reuse decisions;
sandbox copies drive execution/resume without touching real artifacts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from battery_workbench.orchestrator.engine import PipelineOrchestrator

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

pytestmark = pytest.mark.skipif(
    not (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet").exists(),
    reason="real CELL_001/EXP_001 processed artifacts not available",
)


def _orch(processed_root: Path | None = None) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        raw_root=RAW,
        processed_root=processed_root or PROCESSED,
        runs_root=None,  # default: data/artifacts/runs (or sandbox)
    )


# --- T39-T41 + T15: dry run / all-reuse over REAL artifacts (read-only) ---


def test_t39_dry_run_plan_a_mostly_reuse() -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
    )
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["ELECTRICAL_CANONICAL"] == "REUSED"
    assert states["ULTRASOUND_CANONICAL"] == "REUSED"
    assert states["MEASUREMENT_EVENTS"] == "REUSED"


def test_t40_start_run_all_reuse(tmp_path: Path) -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        reuse_existing=True,
    )
    run = svc.start_run(plan, runs_root=tmp_path)
    assert run["status"] == "SUCCEEDED"
    reused = [n for n in run["nodes"] if n["state"] == "REUSED"]
    assert len(reused) >= 3
    assert (tmp_path / run["run_id"].replace("RUN::", "") / "run_manifest.json").exists()


def test_t41_get_run(tmp_path: Path) -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
    )
    run = svc.start_run(plan, runs_root=tmp_path)
    got = svc.get_run(run["run_id"], runs_root=tmp_path)
    assert got["run_id"] == run["run_id"]
    assert got["status"] == "SUCCEEDED"


# --- sandbox for execution tests (real inputs copied, real params untouched) ---


def _sandbox(tmp_path: Path) -> Path:
    """Sandbox processed root: real measurement events + its provenance inputs."""
    sandbox = tmp_path / "processed"
    events_rel = "multimodal/CELL_001/EXP_001"
    (sandbox / events_rel).mkdir(parents=True)
    src = PROCESSED / events_rel
    for name in (
        "measurement_events.parquet",
        "measurement_event_manifest.json",
        "measurement_event_candidates.parquet",
    ):
        shutil.copy(src / name, sandbox / events_rel / name)
    # provenance inputs referenced by the events manifest
    for rel in (
        "synchronization/CELL_001/EXP_001",
        "electrical/CELL_001/EXP_001",
        "labels/CELL_001/EXP_001",
        "ultrasound/CELL_001/EXP_001",
    ):
        (sandbox / rel).mkdir(parents=True)
        for f in (PROCESSED / rel).iterdir():
            if f.suffix in {".parquet", ".json"}:
                shutil.copy(f, sandbox / rel / f.name)
    return sandbox


def _param_plan(tmp_path: Path, **plan_kwargs):
    sandbox = _sandbox(tmp_path)
    svc = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
    plan = svc.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        runs_root=tmp_path / "runs",
        stages=["MEASUREMENT_EVENTS", "PARAMETER_SET"],
        parameters={"require_sampling_rate": plan_kwargs.pop("require_sampling_rate", False)},
    )
    return svc, plan, sandbox


# --- T16-T19: execution states ---


def test_t16_one_node_execution_runs(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path)
    run = svc.start_run(plan)
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["PARAMETER_SET"] in {"RUNNING", "SUCCEEDED", "REUSED"}
    assert run["status"] in {"SUCCEEDED", "WAITING_FOR_USER", "PARTIAL"}


def test_t18_blocked_is_not_failed(tmp_path: Path) -> None:
    """PARAMETER_SET depends on a node that FAILED → dependents BLOCKED."""
    sandbox = _sandbox(tmp_path)
    # corrupt the aligned frames input so MEASUREMENT_EVENTS fails
    victim = sandbox / "synchronization/CELL_001/EXP_001/aligned_ultrasound_frames.parquet"
    victim.write_bytes(b"corrupt")
    svc = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
    plan = svc.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        runs_root=tmp_path / "runs",
        stages=["MEASUREMENT_EVENTS", "PARAMETER_SET"],
    )
    run = svc.start_run(plan)
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["MEASUREMENT_EVENTS"] == "FAILED"
    assert states["PARAMETER_SET"] == "BLOCKED"
    assert run["status"] == "FAILED"


def test_t19_waiting_for_user_missing_sampling_rate(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path, require_sampling_rate=True)
    run = svc.start_run(plan)
    assert run["status"] == "WAITING_FOR_USER"
    actions = svc.list_user_actions(run["run_id"], runs_root=tmp_path / "runs")
    assert len(actions) == 1
    assert actions[0]["action_type"] == "MISSING_SAMPLING_RATE"
    assert actions[0]["blocking"] is True
    # orchestrator did not guess a value
    assert actions[0]["required_fields"]


# --- T20-T21: failure propagation + final status ---


def test_t20_failed_node_stops_dependents(tmp_path: Path) -> None:
    run, _svc, _sandbox = _corrupted_run(tmp_path)
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["PARAMETER_SET"] == "BLOCKED"


def test_t21_final_status_correct(tmp_path: Path) -> None:
    run, _svc, _sandbox = _corrupted_run(tmp_path)
    assert run["status"] == "FAILED"


def _corrupted_run(tmp_path: Path) -> tuple[dict, PipelineOrchestrator, Path]:
    sandbox = _sandbox(tmp_path)
    victim = sandbox / "synchronization/CELL_001/EXP_001/aligned_ultrasound_frames.parquet"
    victim.write_bytes(b"corrupt")
    svc = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
    plan = svc.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["MEASUREMENT_EVENTS", "PARAMETER_SET"],
    )
    return svc.start_run(plan), svc, sandbox


# --- T22-T26: resume / retry ---


def test_t22_t23_resume_after_user_action_no_upstream_recompute(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path, require_sampling_rate=True)
    run = svc.start_run(plan)
    assert run["status"] == "WAITING_FOR_USER"
    action = svc.list_user_actions(run["run_id"], runs_root=tmp_path / "runs")[0]

    resumed = svc.resume_run(
        run["run_id"],
        user_inputs={
            "ultrasound.sampling_rate_hz": {"value": 50.0, "unit": "MHz"},
            "ultrasound.trigger_sample_index": {"value": 0, "unit": "sample"},
        },
        action_id=action["action_id"],
        runs_root=tmp_path / "runs",
    )
    assert resumed["status"] == "SUCCEEDED"
    states = {n["node_id"]: n["state"] for n in resumed["nodes"]}
    # upstream events node was NOT recomputed
    assert states["MEASUREMENT_EVENTS"] in {"REUSED", "SUCCEEDED"}
    # parameter set now resolved with the user-supplied fs
    param = next(n for n in resumed["nodes"] if n["node_id"] == "PARAMETER_SET")
    assert param["state"] in {"SUCCEEDED", "REUSED"}


def test_t24_retry_failed_node(tmp_path: Path) -> None:
    run, svc, sandbox = _corrupted_run(tmp_path)
    assert run["status"] == "FAILED"
    # fix the corrupt input, then retry the failed node
    victim_rel = "synchronization/CELL_001/EXP_001/aligned_ultrasound_frames.parquet"
    shutil.copy(PROCESSED / victim_rel, sandbox / victim_rel)
    retried = svc.retry_node(run["run_id"], "MEASUREMENT_EVENTS", runs_root=tmp_path / "runs")
    states = {n["node_id"]: n["state"] for n in retried["nodes"]}
    assert states["MEASUREMENT_EVENTS"] in {"SUCCEEDED", "REUSED"}
    assert states["PARAMETER_SET"] in {"SUCCEEDED", "REUSED", "RUNNING"}


def test_t25_successful_node_not_retried(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path)
    run = svc.start_run(plan)
    events_node = next(n for n in run["nodes"] if n["node_id"] == "MEASUREMENT_EVENTS")
    assert events_node["state"] in {"REUSED", "SUCCEEDED"}
    # retrying a successful node is a no-op
    retried = svc.retry_node(run["run_id"], "MEASUREMENT_EVENTS", runs_root=tmp_path / "runs")
    node = next(n for n in retried["nodes"] if n["node_id"] == "MEASUREMENT_EVENTS")
    assert node["state"] == events_node["state"]


def test_t26_event_append_behavior(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path, require_sampling_rate=True)
    run = svc.start_run(plan)
    events_path = Path(run["run_dir"]) / "run_events.jsonl"
    lines_before = events_path.read_text().strip().splitlines()
    assert any("RUN_CREATED" in line for line in lines_before)
    assert any("USER_ACTION_REQUIRED" in line or "NODE_BLOCKED" in line for line in lines_before)
    svc.resume_run(
        run["run_id"],
        user_inputs={"ultrasound.sampling_rate_hz": {"value": 50.0, "unit": "MHz"}},
        runs_root=tmp_path / "runs",
    )
    lines_after = events_path.read_text().strip().splitlines()
    assert len(lines_after) > len(lines_before)
    assert any("RUN_RESUMED" in line for line in lines_after)


# --- T27-T31: incremental invalidation (dry-run over REAL artifacts) ---


def _analysis_plan(svc: PipelineOrchestrator, **overrides) -> dict:
    kwargs = {
        "profile": "FULL_PRE_MODEL",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "dry_run": True,
        "target": "soc_reference_percent",
        "features": {"selected_features": ["amplitude_a_u"]},
        "analysis_slice": {"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        "parameters": {"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
    }
    kwargs.update(overrides)
    return svc.plan_run(**kwargs)


def test_t27_gate_change_only_downstream() -> None:
    svc = _orch()
    plan = _analysis_plan(
        svc,
        gates={"gate_specs": [{"gate_name": "primary", "start_sample": 0, "end_sample": 250}]},
    )
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["GATED_FEATURES"] == "RUNNING"
    assert states["FEATURE_LABEL_ANALYSIS"] == "RUNNING"
    # "相关 DATASET": this plan's dataset uses only non-gated features → reused
    assert states["DATASET"] == "REUSED"
    # upstream untouched
    assert states["MEASUREMENT_EVENTS"] == "REUSED"
    assert states["ANALYSIS_SLICE"] == "REUSED"
    assert states["ULTRASOUND_FEATURES"] == "REUSED"
    assert states["SYNCHRONIZATION"] == "REUSED"


def test_t28_selected_feature_change_dataset_side_only() -> None:
    svc = _orch()
    plan = _analysis_plan(svc, features={"selected_features": ["waveform_rms_a_u"]})
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["DATASET"] == "RUNNING"
    assert states["GATED_FEATURES"] == "REUSED"
    assert states["ULTRASOUND_FEATURES"] == "REUSED"
    assert states["ANALYSIS_SLICE"] == "REUSED"


def test_t29_label_change_invalidates_analysis_and_dataset() -> None:
    svc = _orch()
    # no pinned label set + force label rebuild via provenance change is
    # simulated by demanding a different label producer version
    plan = _analysis_plan(svc, label_producer_version="9.9.9")
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["REFERENCE_LABELS"] == "RUNNING"
    assert states["FEATURE_LABEL_ANALYSIS"] == "RUNNING"
    assert states["DATASET"] == "RUNNING"
    assert states["ULTRASOUND_FEATURES"] == "REUSED"


def test_t30_parameter_change_only_physical_dependent_path() -> None:
    """New parameter intent (user overrides) → PARAMETER_SET runs; non-physical
    upstream (slice/features) reuse; downstream re-evaluates."""
    svc = _orch()
    plan = _analysis_plan(
        svc,
        parameters={
            "user_overrides": {"ultrasound.sampling_rate_hz": {"value": 100.0, "unit": "MHz"}},
        },
    )
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["PARAMETER_SET"] == "RUNNING"
    assert states["DATASET"] == "RUNNING"
    assert states["ANALYSIS_SLICE"] == "REUSED"
    assert states["ULTRASOUND_FEATURES"] == "REUSED"


def test_t31_raw_change_invalidates_downstream() -> None:
    svc = _orch()
    plan = _analysis_plan(svc, force_recompute=["ULTRASOUND_CANONICAL"])
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["ULTRASOUND_CANONICAL"] == "RUNNING"
    assert states["TIME_ANCHOR"] == "RUNNING"
    assert states["SYNCHRONIZATION"] == "RUNNING"
    assert states["MEASUREMENT_EVENTS"] == "RUNNING"
    assert states["DATASET"] == "RUNNING"


# --- T32-T38: scientific safeguards ---


def test_t32_cannot_fabricate_parameter(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path, require_sampling_rate=True)
    run = svc.start_run(plan)
    action = svc.list_user_actions(run["run_id"], runs_root=tmp_path / "runs")[0]
    # submitting an empty/absent value must NOT satisfy the action
    with pytest.raises(ValueError):
        svc.submit_user_action(
            run["run_id"], action["action_id"], values={}, runs_root=tmp_path / "runs"
        )
    with pytest.raises(ValueError):
        svc.submit_user_action(
            run["run_id"],
            action["action_id"],
            values={"ultrasound.sampling_rate_hz": {"value": None}},
            runs_root=tmp_path / "runs",
        )


def test_t33_delay_never_auto_promotes_to_tof(tmp_path: Path) -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
        stages=["GATED_FEATURES"],
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        gates={
            "gate_specs": [
                {"gate_name": "a", "start_sample": 0, "end_sample": 200},
                {"gate_name": "b", "start_sample": 800, "end_sample": 980},
            ]
        },
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
    )
    execution = svc.dry_run(plan)
    # delay column is diagnostic; no tof_us promotion without confirmation
    assert "tof_us" not in json.dumps([n.model_dump(mode="json") for n in execution.nodes])


def test_t34_soh_limitation_preserved() -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="BUILD_DATASET",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
        target="soh_capacity_reference_percent",
        features={"selected_features": ["waveform_rms_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        label_producer_version=None,
    )
    execution = svc.dry_run(plan)
    ds_node = next(n for n in execution.nodes if n.node_id == "DATASET")
    # existing SOH dataset carries NOT_READY_FOR_MODEL_EVALUATION — reused as-is
    assert ds_node.state == "REUSED"
    assert "NOT_READY_FOR_MODEL_EVALUATION" in json.dumps(ds_node.reason)


def test_t35_provisional_sync_preserved() -> None:
    ts_manifest = json.loads(
        (PROCESSED / "synchronization/CELL_001/EXP_001/timestamp_engine_manifest.json").read_text()
    )
    svc = _orch()
    ref = svc.describe_artifact("ULTRASOUND_TIMESTAMPS")
    assert ref is not None
    assert ref["manifest"]["engine_version"] == ts_manifest["engine_version"]


def test_t36_retrospective_soc_preserved() -> None:
    svc = _orch()
    ref = svc.describe_artifact("REFERENCE_LABELS")
    assert ref is not None
    assert ref["manifest"]["soc_method"] == "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED"


def test_t37_forbidden_predictor_guard_preserved(tmp_path: Path) -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="BUILD_DATASET",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        target="soc_reference_percent",
        stages=["DATASET"],
        features={"selected_features": ["soc_dod_percent"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
    )
    run = svc.start_run(plan, runs_root=tmp_path)
    ds = next(n for n in run["nodes"] if n["node_id"] == "DATASET")
    assert ds["state"] == "FAILED"
    assert "target-leakage" in ds["reason"]


def test_t38_frame_random_split_prohibition_preserved() -> None:
    svc = _orch()
    svc.get_artifact_lineage_by_id("DATASET", "DS::6a3142e5186fc684964ff09e")
    leakage = json.loads(
        (
            PROCESSED
            / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e/leakage_policy.json"
        ).read_text()
    )
    assert leakage["frame_level_random_split_prohibited"] is True


# --- T42-T44: service ---


def test_t42_user_actions_listing(tmp_path: Path) -> None:
    svc, plan, _sandbox = _param_plan(tmp_path, require_sampling_rate=True)
    run = svc.start_run(plan)
    actions = svc.list_user_actions(run["run_id"], runs_root=tmp_path / "runs")
    assert actions and set(actions[0]) >= {
        "action_id",
        "node_id",
        "action_type",
        "message",
        "required_fields",
        "scientific_reason",
        "blocking",
    }


def test_t44_lineage_structure() -> None:
    svc = _orch()
    lineage = svc.get_artifact_lineage_by_id("DATASET", "DS::6a3142e5186fc684964ff09e")
    assert lineage["artifact"]["artifact_id"] == "DS::6a3142e5186fc684964ff09e"
    children = {c["artifact"]["artifact_type"]: c for c in lineage["inputs"]}
    assert "ULTRASOUND_FEATURE_SET" in children
    assert "LABEL_SET" in children
    # recursive: feature set → analysis slice → measurement events
    fs_node = children["ULTRASOUND_FEATURE_SET"]
    fs_children = {c["artifact"]["artifact_type"] for c in fs_node["inputs"]}
    assert "ANALYSIS_SLICE" in fs_children

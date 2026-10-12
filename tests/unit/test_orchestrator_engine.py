"""BRW-019 T15-T26 + T32-T44: orchestrator execution, resume, invalidation,
scientific safeguards, service facade.

Strategy: the engine is exercised through the REAL node registry. Real
CELL_001/EXP_001 manifests (read-only) drive dry-run/reuse decisions;
sandbox copies drive execution/resume without touching real artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from battery_workbench.orchestrator.engine import (
    PipelineOrchestrator,
    _validate_selection_confirmation,
)
from battery_workbench.orchestrator.nodes import (
    ParameterSetNode,
    SynchronizationNode,
    TimeAnchorNode,
    UltrasoundTimestampsNode,
)
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject
from battery_workbench.provenance.parser_manifest import parser_output_integrity_reasons

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

pytestmark = pytest.mark.skipif(
    not (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet").exists()
    or any(parser_output_integrity_reasons(PROCESSED, "CELL_001", "EXP_001").values()),
    reason=(
        "real CELL_001/EXP_001 parser outputs are unavailable or lack verifiable "
        "generation-time checksums; use fresh parser artifacts for orchestration acceptance"
    ),
)


def _orch(processed_root: Path | None = None) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        raw_root=RAW,
        processed_root=processed_root or PROCESSED,
        runs_root=None,  # default: data/artifacts/runs (or sandbox)
    )


def _orch_with_fresh_timebase_chain(tmp_path: Path) -> PipelineOrchestrator:
    """Refresh the timestamp/sync chain in an isolated overlay over real inputs."""
    processed_root = tmp_path / "processed-overlay"
    processed_root.mkdir()
    for source in PROCESSED.iterdir():
        if source.name in {"synchronization", "electrical", "ultrasound"}:
            continue
        target = processed_root / source.name
        if source.is_dir():
            shutil.copytree(source, target, copy_function=os.link)
        else:
            os.link(source, target)
    synchronization_source = PROCESSED / "synchronization"
    if synchronization_source.exists():
        shutil.copytree(synchronization_source, processed_root / "synchronization")
    for modality in ("electrical", "ultrasound"):
        source = PROCESSED / modality / "CELL_001" / "EXP_001"
        target = processed_root / modality / "CELL_001" / "EXP_001"
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, copy_function=os.link)
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_001", experiment_id="EXP_001"),
    )
    ctx = SimpleNamespace(raw_root=RAW, processed_root=processed_root)
    TimeAnchorNode().run(plan, {}, ctx)
    UltrasoundTimestampsNode().run(plan, {}, ctx)
    SynchronizationNode().run(plan, {}, ctx)
    return _orch(processed_root)


# --- T39-T41 + T15: dry run / all-reuse over REAL artifacts (read-only) ---


def test_t39_dry_run_plan_marks_outdated_measurement_events_for_rebuild(tmp_path: Path) -> None:
    svc = _orch_with_fresh_timebase_chain(tmp_path)
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
    measurement_events = next(n for n in execution.nodes if n.node_id == "MEASUREMENT_EVENTS")
    manifest = json.loads(
        (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_event_manifest.json").read_text()
    )
    if manifest.get("builder_version") == "0.5.1":
        assert measurement_events.state == "REUSED"
    else:
        assert measurement_events.state == "RUNNING"


def test_t40_start_run_all_reuse(tmp_path: Path) -> None:
    svc = _orch(_sandbox(tmp_path))
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
    svc = _orch(_sandbox(tmp_path))
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
            destination = sandbox / rel / f.name
            if f.is_dir():
                shutil.copytree(f, destination)
            elif f.suffix in {".parquet", ".json"}:
                shutil.copy(f, destination)
    return sandbox


def _param_plan(tmp_path: Path, **plan_kwargs):
    sandbox = _sandbox(tmp_path)
    svc = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
    plan = svc.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
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
    """Corrupt cached input blocks reuse and downstream nodes without parsing it."""
    sandbox = _sandbox(tmp_path)
    # Corrupt the aligned input; its old manifest checksum must block reuse.
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
    assert states["MEASUREMENT_EVENTS"] == "BLOCKED"
    assert states["PARAMETER_SET"] == "BLOCKED"
    assert run["status"] == "PARTIAL"


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
    """Corrupt a pinned timestamp output so synchronization itself FAILs."""
    sandbox = _sandbox(tmp_path)
    victim = sandbox / "synchronization/CELL_001/EXP_001/timestamped_ultrasound_frames.parquet"
    victim.write_bytes(b"corrupt")
    manifest_path = victim.parent / "timestamp_engine_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_checksum"] = hashlib.sha256(victim.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    svc = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=tmp_path / "runs")
    plan = svc.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        reuse_existing=True,
        force_recompute=[
            "MEASUREMENT_EVENTS",
            "PARAMETER_SET",
        ],
        stages=[
            "ELECTRICAL_CANONICAL",
            "ULTRASOUND_CANONICAL",
            "TIME_ANCHOR",
            "ULTRASOUND_TIMESTAMPS",
            "SYNCHRONIZATION",
            "MEASUREMENT_EVENTS",
            "PARAMETER_SET",
        ],
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


def test_selection_confirmation_rejects_a_different_pending_selection_id() -> None:
    action = {
        "action_type": "CONFIRM_FEATURE_SELECTION",
        "required_fields": [{"field": "selection_id", "value": "SEL::expected"}],
    }

    with pytest.raises(ValueError, match="does not match the pending feature selection"):
        _validate_selection_confirmation(action, {"selection_id": "SEL::stale"})


def test_selection_confirmation_accepts_only_the_pending_selection_id() -> None:
    action = {
        "action_type": "CONFIRM_FEATURE_SELECTION",
        "required_fields": [{"field": "selection_id", "value": "SEL::expected"}],
    }

    _validate_selection_confirmation(action, {"selection_id": "SEL::expected"})


@pytest.mark.parametrize(
    "required_fields",
    [
        [],
        [{"field": "selection_id"}],
        [
            {"field": "selection_id", "value": "SEL::expected"},
            {"field": "selection_id", "value": "SEL::other"},
        ],
    ],
)
def test_selection_confirmation_rejects_malformed_pending_action(
    required_fields: list[dict[str, str]],
) -> None:
    action = {
        "action_type": "CONFIRM_FEATURE_SELECTION",
        "required_fields": required_fields,
    }

    with pytest.raises(ValueError, match="pending feature selection action"):
        _validate_selection_confirmation(action, {"selection_id": "SEL::expected"})


def test_t24_retry_failed_node(tmp_path: Path) -> None:
    run, svc, sandbox = _corrupted_run(tmp_path)
    assert run["status"] == "FAILED"
    # fix the corrupt input, then retry
    victim_rel = "synchronization/CELL_001/EXP_001/timestamped_ultrasound_frames.parquet"
    shutil.copy(PROCESSED / victim_rel, sandbox / victim_rel)
    manifest_rel = "synchronization/CELL_001/EXP_001/timestamp_engine_manifest.json"
    shutil.copy(PROCESSED / manifest_rel, sandbox / manifest_rel)
    retried = svc.retry_node(run["run_id"], "SYNCHRONIZATION", runs_root=tmp_path / "runs")
    states = {n["node_id"]: n["state"] for n in retried["nodes"]}
    assert states["SYNCHRONIZATION"] in {"SUCCEEDED", "REUSED"}
    assert states["MEASUREMENT_EVENTS"] in {"SUCCEEDED", "REUSED", "RUNNING"}
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
        "parameters": {"parameter_set_id": "PS::091640eaac26f6f3b4392f90"},
    }
    kwargs.update(overrides)
    return svc.plan_run(**kwargs)


def test_t27_gate_change_only_downstream(tmp_path: Path) -> None:
    svc = _orch_with_fresh_timebase_chain(tmp_path)
    plan = _analysis_plan(
        svc,
        features={
            "selected_features": [
                "tof_us",
                "amplitude_a_u",
                "waveform_p2p_a_u",
                "waveform_mean_a_u",
                "waveform_rms_a_u",
                "envelope_peak_a_u",
            ]
        },
        gates={"gate_specs": [{"gate_name": "primary", "start_sample": 0, "end_sample": 250}]},
    )
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["GATED_FEATURES"] == "RUNNING"
    assert states["FEATURE_LABEL_ANALYSIS"] == "RUNNING"
    # The checked-in AnalysisSlice records a different MeasurementEvents
    # checksum, so Dataset/Split must be reevaluated along with the slice.
    assert states["DATASET"] == "RUNNING"
    assert states["SPLIT"] == "RUNNING"
    assert states["TOF_ACTIVATION"] == "RUNNING"
    # Missing an explicit feature_analysis plan block is a plan error, not a
    # deferable dependency state, even while the upstream FLA is rebuilding.
    assert states["FEATURE_ANALYSIS"] == "BLOCKED"
    analysis_node = next(node for node in execution.nodes if node.node_id == "FEATURE_ANALYSIS")
    assert "no feature_analysis block in plan" in analysis_node.reason
    # upstream untouched
    assert states["MEASUREMENT_EVENTS"] == "REUSED"
    assert states["ANALYSIS_SLICE"] == "RUNNING"
    slice_node = next(node for node in execution.nodes if node.node_id == "ANALYSIS_SLICE")
    assert "INPUT_CHECKSUM_MISMATCH:measurement_events" in slice_node.reason
    assert states["ULTRASOUND_FEATURES"] == "RUNNING"
    assert states["SYNCHRONIZATION"] == "REUSED"
    # Physical-time dependents also re-evaluate because their upstream chain is stale.
    assert states["TOF_ACTIVATION"] == "RUNNING"


def test_t28_selected_feature_change_dataset_side_only(tmp_path: Path) -> None:
    svc = _orch_with_fresh_timebase_chain(tmp_path)
    # Pick a supported single feature that is not already materialized as a
    # fresh Dataset in the current CELL_001 fixture inventory.
    plan = _analysis_plan(svc, features={"selected_features": ["waveform_mean_a_u"]})
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["DATASET"] == "RUNNING"
    # The stale AnalysisSlice blocks downstream cache decisions until it is
    # rebuilt, so GateSet validation is deferred with the dependency reason.
    assert states["GATED_FEATURES"] == "RUNNING"
    gate_node = next(node for node in execution.nodes if node.node_id == "GATED_FEATURES")
    assert "upstream invalidated" in gate_node.reason
    assert states["ULTRASOUND_FEATURES"] == "RUNNING"
    assert states["ANALYSIS_SLICE"] == "RUNNING"
    # No explicit Feature Analysis spec is present in this run plan; silently
    # reusing an arbitrary historical analysis would violate its input contract.
    assert states["FEATURE_ANALYSIS"] == "BLOCKED"


def test_t29_label_change_invalidates_analysis_and_dataset(tmp_path: Path) -> None:
    svc = _orch_with_fresh_timebase_chain(tmp_path)
    # no pinned label set + force label rebuild via provenance change is
    # simulated by demanding a different label producer version
    plan = _analysis_plan(svc, label_producer_version="9.9.9")
    execution = svc.dry_run(plan)
    states = {n.node_id: n.state for n in execution.nodes}
    assert states["REFERENCE_LABELS"] == "RUNNING"
    assert states["FEATURE_LABEL_ANALYSIS"] == "RUNNING"
    assert states["DATASET"] == "RUNNING"
    assert states["ANALYSIS_SLICE"] == "RUNNING"
    slice_node = next(node for node in execution.nodes if node.node_id == "ANALYSIS_SLICE")
    assert "INPUT_CHECKSUM_MISMATCH:measurement_events" in slice_node.reason
    assert states["ULTRASOUND_FEATURES"] == "RUNNING"


def test_t30_parameter_change_only_physical_dependent_path(tmp_path: Path) -> None:
    """Parameter intent runs; the stale AnalysisSlice is rejected and its
    dependent feature/Dataset stages are scheduled for reevaluation."""
    svc = _orch_with_fresh_timebase_chain(tmp_path)
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
    assert states["ANALYSIS_SLICE"] == "RUNNING"
    slice_node = next(node for node in execution.nodes if node.node_id == "ANALYSIS_SLICE")
    assert "INPUT_CHECKSUM_MISMATCH:measurement_events" in slice_node.reason
    assert states["ULTRASOUND_FEATURES"] == "RUNNING"


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
        parameters={"parameter_set_id": "PS::091640eaac26f6f3b4392f90"},
    )
    execution = svc.dry_run(plan)
    # delay column is diagnostic; no tof_us promotion without confirmation
    assert "tof_us" not in json.dumps([n.model_dump(mode="json") for n in execution.nodes])


def test_t34_stale_soh_dataset_not_reused_and_label_limitation_preserved() -> None:
    svc = _orch()
    plan = svc.plan_run(
        profile="BUILD_DATASET",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
        target="soh_capacity_reference_percent",
        features={"selected_features": ["waveform_rms_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::091640eaac26f6f3b4392f90"},
        label_producer_version=None,
    )
    execution = svc.dry_run(plan)
    ds_node = next(n for n in execution.nodes if n.node_id == "DATASET")
    assert ds_node.state == "RUNNING"
    assert ds_node.outputs == []
    stale_dataset = json.loads(
        (PROCESSED / "datasets/CELL_001/EXP_001/SOH_CAPACITY/DS::c10c43b1890949aff0e94663/dataset_manifest.json").read_text()
    )
    from battery_workbench.datasets.freshness import dataset_freshness

    stale_assessment = dataset_freshness(
        PROCESSED,
        PROCESSED
        / "datasets/CELL_001/EXP_001/SOH_CAPACITY/DS::c10c43b1890949aff0e94663/dataset_manifest.json",
        stale_dataset,
    )
    assert stale_assessment["freshness_status"] == "STALE_SOURCE"
    assert "LABEL_SOURCE_CHECKSUM_MISMATCH" in stale_assessment["freshness_reasons"]
    current_labels = json.loads(
        (PROCESSED / "labels/CELL_001/EXP_001/label_manifest.json").read_text()
    )
    assert current_labels["soh_independent_state_count"] == 2
    assert current_labels["soh_model_readiness"] == "NOT_READY_FOR_ROBUST_SUPERVISED_LEARNING"


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
    # Historical labels without ultrasound parser provenance must be rebuilt,
    # not exposed as a reusable artifact.
    if ref is None:
        plan = svc.plan_run(
            profile="FULL_PRE_MODEL",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=True,
            stages=["MEASUREMENT_EVENTS", "REFERENCE_LABELS"],
        )
        execution = svc.dry_run(plan)
        labels = next(node for node in execution.nodes if node.node_id == "REFERENCE_LABELS")
        assert labels.state == "RUNNING"
    else:
        assert ref["manifest"]["soc_method"] == "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED"


def test_t37_legacy_parameter_records_are_recovered_but_cache_is_rebuilt(tmp_path: Path) -> None:
    sandbox_processed = tmp_path / "processed"
    shutil.copytree(PROCESSED, sandbox_processed, copy_function=shutil.copy2)
    plan = AnalysisPlan(
        profile="BUILD_DATASET",
        project=PlanProject(battery_id="CELL_001", experiment_id="EXP_001"),
        target="soc_reference_percent",
        parameters={"parameter_set_id": "PS::091640eaac26f6f3b4392f90"},
    )
    ctx = SimpleNamespace(processed_root=sandbox_processed)
    node = ParameterSetNode()
    output = node.run(plan, {}, ctx)
    new_manifest = json.loads(Path(output["manifest_path"]).read_text(encoding="utf-8"))
    effective = json.loads(Path(output["path"], "effective_parameters.json").read_text())
    assert output["artifact_id"] == "PS::091640eaac26f6f3b4392f90"
    assert effective["ultrasound.sampling_rate_hz"]["value"] == 50_000_000
    assert effective["ultrasound.sampling_rate_hz"]["verification_status"] == "VERIFIED"
    assert new_manifest["input_checksums"]["waveform_store"]
    assert not Path(output["manifest_path"]).samefile(
        PROCESSED / "parameters/CELL_001/EXP_001" / output["artifact_id"] / "parameter_set_manifest.json"
    )


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

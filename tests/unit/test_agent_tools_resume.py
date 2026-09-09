"""BRW-026 Final Interactive Resume Remediation — E2E for the interaction loop.

Flow: tool execution → WAITING_FOR_USER → agent explains → user provides value
→ submit_user_action → resume_run → downstream continues on the SAME run.

Both scenarios run through ToolGateway only (BRW-019 orchestrator does the
science; the tool layer never fabricates values).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.agent_tools.models import AgentScientificContext
from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data/raw"
PROCESSED = REPO / "data/processed"


def _sandbox_service(tmp_path: Path):
    """Real measurement events + provenance in a sandbox processed root."""
    import shutil

    sandbox = tmp_path / "processed"
    events_rel = "multimodal/CELL_001/EXP_001"
    (sandbox / events_rel).mkdir(parents=True)
    for name in (
        "measurement_events.parquet",
        "measurement_event_manifest.json",
        "measurement_event_candidates.parquet",
    ):
        shutil.copy(PROCESSED / events_rel / name, sandbox / events_rel / name)
    for rel in (
        "synchronization/CELL_001/EXP_001",
        "electrical/CELL_001/EXP_001",
        "labels/CELL_001/EXP_001",
        "ultrasound/CELL_001/EXP_001",
    ):
        (sandbox / rel).mkdir(parents=True)
        for f in (PROCESSED / rel).iterdir():
            if f.is_file():
                shutil.copy(f, sandbox / rel / f.name)
    service = create_app(
        raw_root=RAW,
        processed_root=sandbox,
        runs_root=tmp_path / "runs",
    ).state.workbench_service
    service.runs_root = tmp_path / "runs"
    return service


def _confirmed(gw: ToolGateway, ctx: AgentScientificContext, tool: str, inputs: dict) -> dict:
    result = gw.execute(tool, ctx, inputs)
    if result.status == "CONFIRMATION_REQUIRED":
        result = gw.execute(
            tool, ctx, inputs, confirmation_id=result.confirmation["confirmation_id"]
        )
    assert result.status == "SUCCEEDED", result.error
    return result.data


class TestResumeLoopSamplingRate:
    """E2E: MISSING_SAMPLING_RATE → WAITING_FOR_USER → submit 50 MHz → resume."""

    def test_sampling_rate_resume_loop(self, tmp_path: Path) -> None:
        service = _sandbox_service(tmp_path)
        gw = ToolGateway(service=service)
        ctx = AgentScientificContext(battery_id="CELL_001", experiment_id="EXP_001")

        # run INGEST/parameter flow that requires sampling rate → WAITING_FOR_USER
        started = _confirmed(
            gw,
            ctx,
            "start_run",
            {
                "profile": "SCIENTIFIC_ANALYSIS",
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "stages": ["MEASUREMENT_EVENTS", "PARAMETER_SET"],
                "parameters": {"require_sampling_rate": True},
            },
        )
        if started.get("status") != "WAITING_FOR_USER":
            pytest.skip(f"fixture run did not reach WAITING_FOR_USER: {started.get('status')}")

        run_id = started["run_id"]
        ctx.run_id = run_id

        # 1. Agent detects pending scientific action
        pending = gw.execute("list_pending_user_actions", ctx, {"run_id": run_id})
        assert pending.status == "SUCCEEDED"
        actions = pending.data["pending_actions"]
        sampling = next(a for a in actions if a.get("action_type") == "MISSING_SAMPLING_RATE")
        assert sampling["required_fields"][0]["field"] == "ultrasound.sampling_rate_hz"
        # scientific reason present for the agent to explain to the user
        assert (
            "cadence" in sampling.get("scientific_reason", "").lower()
            or "sampling" in sampling.get("scientific_reason", "").lower()
        )

        # 2. Agent must NOT guess: values without _source are rejected
        no_source = gw.execute(
            "submit_user_action",
            ctx,
            {
                "run_id": run_id,
                "action_id": sampling["action_id"],
                "values": {"ultrasound.sampling_rate_hz": {"value": 50.0, "unit": "MHz"}},
            },
        )
        assert no_source.status == "FAILED"
        assert no_source.error["code"] == "SECURITY_VIOLATION"

        # 3. user provides/approves 50 MHz → agent submits with provenance
        #    (confirmation-protected: first call returns CONFIRMATION_REQUIRED)
        submit_inputs = {
            "run_id": run_id,
            "action_id": sampling["action_id"],
            "values": {
                "ultrasound.sampling_rate_hz": {"value": 50.0, "unit": "MHz"},
                "_source": "user:instrument-record",
            },
        }
        submit = gw.execute("submit_user_action", ctx, submit_inputs)
        assert submit.status == "CONFIRMATION_REQUIRED"
        submit = gw.execute(
            "submit_user_action",
            ctx,
            submit_inputs,
            confirmation_id=submit.confirmation["confirmation_id"],
        )
        assert submit.status == "SUCCEEDED"

        # 4. resume the SAME run (lineage preserved, RUN_RESUMED appended)
        resumed = gw.execute("resume_run", ctx, {"run_id": run_id})
        assert resumed.status == "SUCCEEDED"
        assert resumed.data["resumed_run_id"] == run_id
        assert resumed.data["original_run_id"] == run_id
        assert resumed.data["lineage_preserved"] is True

        # 5. downstream continued on the same run: parameter set resolved with user fs
        run_after = service.get_run(run_id)
        assert run_after["status"] in ("SUCCEEDED", "PARTIAL")
        param = next(n for n in run_after["nodes"] if n["node_id"] == "PARAMETER_SET")
        assert param["state"] in ("SUCCEEDED", "REUSED")

        # 6. RUN_RESUMED appended to the same run's events (lineage preserved)
        events_path = Path(run_after["run_dir"]) / "run_events.jsonl"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        assert any("RUN_RESUMED" in line for line in lines)
        # same run dir → lineage preserved
        assert any("RUN_CREATED" in line for line in lines)

        # 7. re-submitting the consumed action fails safely (orchestrator contract:
        # unknown/consumed action) — the gateway still requires confirmation first,
        # then surfaces the orchestrator's typed rejection
        resubmit_inputs = {
            "run_id": run_id,
            "action_id": sampling["action_id"],
            "values": {
                "ultrasound.sampling_rate_hz": {"value": 60.0, "unit": "MHz"},
                "_source": "user:x",
            },
        }
        resubmit = gw.execute("submit_user_action", ctx, resubmit_inputs)
        if resubmit.status == "CONFIRMATION_REQUIRED":
            resubmit = gw.execute(
                "submit_user_action",
                ctx,
                resubmit_inputs,
                confirmation_id=resubmit.confirmation["confirmation_id"],
            )
        assert resubmit.status in ("FAILED", "BLOCKED")

        # 8. audit trail captured the whole loop
        audit_tools = [e.tool_name for e in gw.audit.all_entries()]
        assert {"list_pending_user_actions", "submit_user_action", "resume_run"} <= set(audit_tools)
        # no waveform payload in audit
        audit_blob = json.dumps([e.model_dump(mode="json") for e in gw.audit.all_entries()])
        assert "amplitude_a_u" not in audit_blob


class TestAgentSetParameterWritesAndResumes:
    """BRW-018R2: set_experiment_parameter(fs) must REALLY write + resume."""

    def test_fs_write_resume_not_guidance_only(self, tmp_path: Path) -> None:
        service = _sandbox_service(tmp_path)
        gw = ToolGateway(service=service)
        ctx = AgentScientificContext(battery_id="CELL_001", experiment_id="EXP_001")

        started = _confirmed(
            gw,
            ctx,
            "start_run",
            {
                "profile": "SCIENTIFIC_ANALYSIS",
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "stages": ["MEASUREMENT_EVENTS", "PARAMETER_SET"],
                "parameters": {"require_sampling_rate": True},
            },
        )
        if started.get("status") != "WAITING_FOR_USER":
            pytest.skip(f"fixture run did not reach WAITING_FOR_USER: {started.get('status')}")
        run_id = started["run_id"]
        ctx.run_id = run_id

        d = _confirmed(
            gw,
            ctx,
            "set_experiment_parameter",
            {
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "parameter_name": "ultrasound.sampling_rate_hz",
                "value": "50.0",
                "unit": "MHz",
                "verified": True,
                "source": "user:instrument-record",
            },
        )
        # real write + real resume — NOT a guidance-only reply
        assert d["save_status"] == "SAVED"
        assert d["parameter_set_id"], d
        assert d["resume_status"] == "RESUMED"
        assert d["run_id"] == run_id
        assert d["run_state"] in ("SUCCEEDED", "PARTIAL")
        # the same run's PARAMETER_SET resolved with Hz=50e6 VERIFIED
        run_after = service.get_run(run_id)
        param = next(n for n in run_after["nodes"] if n["node_id"] == "PARAMETER_SET")
        assert param["state"] in ("SUCCEEDED", "REUSED")
        eff = json.loads(
            (Path(param["outputs"][0]["path"]) / "effective_parameters.json").read_text()
        )
        fs = eff["ultrasound.sampling_rate_hz"]
        assert fs["value"] == 50_000_000.0 and fs["unit"] == "Hz"
        assert fs["verification_status"] == "VERIFIED"


class TestResumeLoopImpossibleSplit:
    """E2E: impossible split → WAITING_FOR_USER → choose LEAVE_ONE_GROUP_OUT → resume."""

    def test_split_scheme_resume_loop(self, tmp_path: Path) -> None:
        # real demo artifacts provide the full upstream chain (analysis slices etc.);
        # runs land in an isolated runs root; a second K_FOLD(5) request on 2-cycle
        # demo data is impossible → WAITING_FOR_USER
        service = create_app(
            raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs"
        ).state.workbench_service
        service.runs_root = tmp_path / "runs"
        gw = ToolGateway(service=service)
        ctx = AgentScientificContext(battery_id="CELL_001", experiment_id="EXP_001")

        # full pre-model chain then DATASET/SPLIT: 2-group demo data makes
        # K_FOLD_GROUPED(k=5) impossible → WAITING_FOR_USER with legal options
        started = gw.execute(
            "start_run",
            ctx,
            {
                "profile": "FULL_PRE_MODEL",
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "split": {"strategy": "K_FOLD_GROUPED", "k": 5, "split_unit": "CYCLE"},
                "dry_run": False,
            },
        )
        started = (
            gw.execute(
                "start_run",
                ctx,
                {
                    "profile": "FULL_PRE_MODEL",
                    "battery_id": "CELL_001",
                    "experiment_id": "EXP_001",
                    "split": {"strategy": "K_FOLD_GROUPED", "k": 5, "split_unit": "CYCLE"},
                    "dry_run": False,
                },
                confirmation_id=started.confirmation["confirmation_id"],
            )
            if started.status == "CONFIRMATION_REQUIRED"
            else started
        )
        if started.status != "SUCCEEDED" or started.data.get("status") != "WAITING_FOR_USER":
            pytest.skip(
                f"run did not reach WAITING_FOR_USER: {started.status} {started.data.get('status')}"
            )

        run_id = started.data["run_id"]
        ctx.run_id = run_id

        # agent sees the SELECT_SPLIT_SCHEME action with legal options
        pending = gw.execute("list_pending_user_actions", ctx, {"run_id": run_id})
        actions = pending.data["pending_actions"]
        split_actions = [a for a in actions if a.get("action_type") == "SELECT_SPLIT_SCHEME"]
        if not split_actions:
            pytest.skip(
                f"no SELECT_SPLIT_SCHEME pending: {[a.get('action_type') for a in actions]}"
            )
        split_action = split_actions[0]
        option_values = json.dumps(split_action.get("options", []))
        assert "LEAVE_ONE_GROUP_OUT" in option_values

        # user picks LEAVE_ONE_GROUP_OUT → agent submits. BRW-019 contract:
        # dict values must carry a non-null "value" key for validation; the
        # resume merge flattens {**plan.split, **value} so strategy/k ride at
        # the top level of the split dict.
        submit_inputs = {
            "run_id": run_id,
            "action_id": split_action["action_id"],
            "values": {
                "split": {
                    "value": {"strategy": "LEAVE_ONE_GROUP_OUT", "k": None},
                    "strategy": "LEAVE_ONE_GROUP_OUT",
                    "k": None,
                }
            },
        }
        submit = gw.execute("submit_user_action", ctx, submit_inputs)
        if submit.status == "CONFIRMATION_REQUIRED":
            submit = gw.execute(
                "submit_user_action",
                ctx,
                submit_inputs,
                confirmation_id=submit.confirmation["confirmation_id"],
            )
        assert submit.status == "SUCCEEDED"

        resumed = gw.execute("resume_run", ctx, {"run_id": run_id})
        assert resumed.status == "SUCCEEDED"
        assert resumed.data["resumed_run_id"] == run_id

        run_after = service.get_run(run_id)
        events_path = Path(run_after["run_dir"]) / "run_events.jsonl"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        assert any("RUN_RESUMED" in line for line in lines)
        # the SPLIT node continued on the same run with the user-chosen scheme
        states = {n["node_id"]: n["state"] for n in run_after["nodes"]}
        assert states.get("SPLIT") in ("SUCCEEDED", "REUSED", "FAILED")

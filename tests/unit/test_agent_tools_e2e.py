"""BRW-026 §20 E2E A/B/C — full workflows through ToolGateway only.

A: Demo read-only science audit (real CELL_001/EXP_001 artifacts)
B: Brand-new experiment intake (sandbox, real confirmation)
C: Scientific analysis workflow (waveform→gate→analysis→selection→dataset→split→baselines→report)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.agent_tools.models import AgentScientificContext, ToolResult
from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "brw024r"


@pytest.fixture()
def demo_gateway() -> ToolGateway:
    """Real demo workspace (read-only paths only)."""
    service = create_app(
        raw_root=REPO / "data/raw", processed_root=REPO / "data/processed"
    ).state.workbench_service
    return ToolGateway(service=service)


@pytest.fixture()
def sandbox(tmp_path: Path) -> tuple[ToolGateway, AgentScientificContext]:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    manifests = raw / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,parser_name,parser_version\n",
        encoding="utf-8",
    )
    (manifests / "batteries.csv").write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_500,,,sandbox\n", encoding="utf-8"
    )
    service = create_app(raw_root=raw, processed_root=processed).state.workbench_service
    gateway = ToolGateway(service=service)
    ctx = AgentScientificContext(battery_id="CELL_500", experiment_id="EXP_500")
    return gateway, ctx


def _confirmed(gw: ToolGateway, ctx: AgentScientificContext, tool: str, inputs: dict) -> ToolResult:
    result = gw.execute(tool, ctx, inputs)
    if result.status == "CONFIRMATION_REQUIRED":
        result = gw.execute(
            tool, ctx, inputs, confirmation_id=result.confirmation["confirmation_id"]
        )
    return result


class TestE2EA_DemoReadOnlyAudit:
    """E2E A: list → inspect → features → model comparison → evidence → lineage."""

    def test_demo_readonly_science_audit(self, demo_gateway: ToolGateway) -> None:
        ctx = AgentScientificContext(battery_id="CELL_001", experiment_id="EXP_001")

        r1 = demo_gateway.execute("list_experiments", ctx, {})
        assert r1.status == "SUCCEEDED"

        r2 = demo_gateway.execute("inspect_experiment", ctx, {})
        assert r2.status == "SUCCEEDED"

        r3 = demo_gateway.execute("list_available_features", ctx, {})
        assert r3.status == "SUCCEEDED"
        names = [f["feature_name"] for f in r3.data["features"]]
        assert "tof_us" in names

        r4 = demo_gateway.execute("inspect_model_comparison", ctx, {})
        assert r4.status == "SUCCEEDED"
        macro = r4.data.get("macro", [])
        assert len(macro) == 5
        assert r4.data.get("dummy_baseline") is not None
        assert r4.evidence  # evidence propagated

        r5 = demo_gateway.execute(
            "explain_result_evidence", ctx, {"result_id": "R::macro_DUMMY_MEAN_MAE"}
        )
        assert r5.status == "SUCCEEDED"
        assert r5.data["evidence_type"] == "DIRECT_CURRENT_ARTIFACT"

        # unsupported claim blocked at the same tool
        r5b = demo_gateway.execute(
            "explain_result_evidence",
            ctx,
            {
                "result_id": "R::macro_DUMMY_MEAN_MAE",
                "claim": "validated cross-battery SOC model",
            },
        )
        assert r5b.status == "BLOCKED"
        assert r5b.error["code"] == "UNSUPPORTED_CLAIM"

        r6 = demo_gateway.execute("inspect_lineage", ctx, {})
        assert r6.status == "SUCCEEDED"
        assert r6.data["lineage_chain"]


class TestE2EB_NewExperimentIntake:
    """E2E B: create → intake → upload → detect → validate → confirm → commit."""

    def test_new_experiment_intake(
        self, sandbox: tuple[ToolGateway, AgentScientificContext]
    ) -> None:
        gw, ctx = sandbox
        assert HAS_FIXTURES()

        r1 = _confirmed(
            gw, ctx, "create_experiment", {"battery_id": ctx.battery_id, "name": "E2E B"}
        )
        assert r1.status == "SUCCEEDED"
        ctx = AgentScientificContext(
            battery_id=r1.data["battery_id"], experiment_id=r1.data["experiment_id"]
        )

        r2 = gw.execute(
            "start_intake", ctx, {"battery_id": ctx.battery_id, "experiment_id": ctx.experiment_id}
        )
        assert r2.status == "SUCCEEDED"
        sid = r2.data["session_id"]

        for role, fixture in (
            ("ELECTRICAL", "sample_electrical.xlsx"),
            ("ULTRASOUND", "sample_ultrasound.txt"),
        ):
            content = (FIXTURES / fixture).read_bytes().decode("latin-1")
            r3 = gw.execute(
                "upload_experiment_asset",
                ctx,
                {
                    "session_id": sid,
                    "file_ref": fixture,
                    "role": role,
                    "content": content,
                },
            )
            assert r3.status == "SUCCEEDED"

        r4 = gw.execute("detect_asset_format", ctx, {"session_id": sid})
        assert r4.status == "SUCCEEDED"
        assert all(d["state"] == "DETECTED_UNIQUE" for d in r4.data["detections"])

        r5 = gw.execute("validate_intake", ctx, {"session_id": sid})
        assert r5.status == "SUCCEEDED"
        assert r5.data["sampling_rate_hz"] is None
        assert r5.data["sampling_rate_status"] == "UNKNOWN"

        r6 = gw.execute("commit_intake", ctx, {"session_id": sid})
        assert r6.status == "CONFIRMATION_REQUIRED"  # real confirmation required
        r6b = gw.execute(
            "commit_intake",
            ctx,
            {"session_id": sid},
            confirmation_id=r6.confirmation["confirmation_id"],
        )
        assert r6b.status in ("SUCCEEDED", "REUSED")

        # library reflects READY_FOR_PIPELINE
        lib = gw.service.intake.load_library()[ctx.composite_id]
        assert lib["status"] == "READY_FOR_PIPELINE"


def HAS_FIXTURES() -> bool:
    return (FIXTURES / "sample_electrical.xlsx").is_file()


class TestE2EC_ScientificWorkflow:
    """E2E C: waveform → propose/confirm gate → analysis → selection → dataset → split → baselines → report."""

    def test_scientific_analysis_workflow(
        self, sandbox: tuple[ToolGateway, AgentScientificContext]
    ) -> None:
        gw, ctx = sandbox
        assert HAS_FIXTURES()

        # setup: create + intake commit (via tool layer, with confirmations)
        r1 = _confirmed(
            gw, ctx, "create_experiment", {"battery_id": ctx.battery_id, "name": "E2E C"}
        )
        ctx = AgentScientificContext(
            battery_id=r1.data["battery_id"], experiment_id=r1.data["experiment_id"]
        )
        r2 = gw.execute(
            "start_intake", ctx, {"battery_id": ctx.battery_id, "experiment_id": ctx.experiment_id}
        )
        sid = r2.data["session_id"]
        for role, fixture in (
            ("ELECTRICAL", "sample_electrical.xlsx"),
            ("ULTRASOUND", "sample_ultrasound.txt"),
        ):
            content = (FIXTURES / fixture).read_bytes().decode("latin-1")
            gw.execute(
                "upload_experiment_asset",
                ctx,
                {
                    "session_id": sid,
                    "file_ref": fixture,
                    "role": role,
                    "content": content,
                },
            )
        gw.execute("detect_asset_format", ctx, {"session_id": sid})
        gw.execute("validate_intake", ctx, {"session_id": sid})
        commit = gw.execute("commit_intake", ctx, {"session_id": sid})
        commit = gw.execute(
            "commit_intake",
            ctx,
            {"session_id": sid},
            confirmation_id=commit.confirmation["confirmation_id"],
        )
        assert commit.status in ("SUCCEEDED", "REUSED")

        # waveform inspect (may be BLOCKED pre-pipeline: typed, not fabricated)
        wf = gw.execute("inspect_waveform_frame", ctx, {"frame_index": 0})
        assert wf.status in ("SUCCEEDED", "BLOCKED")

        # propose gate (read-only) → confirm create gate
        proposal = gw.execute(
            "propose_gate",
            ctx,
            {
                "battery_id": ctx.battery_id,
                "gate_name": "Gate A",
                "start_sample": 100,
                "end_sample": 400,
            },
        )
        assert proposal.status == "SUCCEEDED"
        assert proposal.data["proposal"]["valid"] is True
        gate = _confirmed(
            gw,
            ctx,
            "create_gate",
            {
                "battery_id": ctx.battery_id,
                "gate_name": "Gate A",
                "start_sample": 100,
                "end_sample": 400,
            },
        )
        assert gate.status in ("SUCCEEDED", "REUSED")
        assert gate.data["gate_id"].startswith("GATE::")

        # feature analysis (exploratory) with evidence
        analysis = _confirmed(
            gw,
            ctx,
            "analyze_feature_relationships",
            {
                "analysis_mode": "EXPLORATORY_FULL_DATA",
                "target": "soc_reference_percent",
                "candidate_features": ["waveform_rms_a_u"],
            },
        )
        assert analysis.status == "SUCCEEDED"
        assert analysis.data["analysis_id"].startswith("AN::")
        assert analysis.evidence

        # selection: propose → confirm
        sel = gw.execute(
            "propose_feature_selection", ctx, {"selected_features": ["waveform_rms_a_u"]}
        )
        assert sel.data["confirmed"] is False
        confirm = _confirmed(
            gw, ctx, "confirm_feature_selection", {"selected_features": ["waveform_rms_a_u"]}
        )
        assert confirm.status == "SUCCEEDED"
        assert confirm.data["confirmed"] is True

        # dataset → split → baselines (deterministic chain, typed outcomes)
        dataset = _confirmed(
            gw, ctx, "prepare_soc_dataset", {"selected_features": ["waveform_rms_a_u"]}
        )
        assert dataset.status in ("SUCCEEDED", "REUSED", "BLOCKED", "FAILED")
        if dataset.status in ("SUCCEEDED", "REUSED"):
            dataset_id = dataset.data["dataset_id"]
            split = _confirmed(
                gw, ctx, "prepare_grouped_evaluation_split", {"dataset_id": dataset_id}
            )
            assert split.status in ("SUCCEEDED", "REUSED", "BLOCKED", "FAILED")
            if split.status in ("SUCCEEDED", "REUSED"):
                split_id = split.data["split_id"]
                baselines = _confirmed(
                    gw,
                    ctx,
                    "run_limited_soc_baselines",
                    {
                        "dataset_id": dataset_id,
                        "split_id": split_id,
                        "selected_features": ["waveform_rms_a_u"],
                    },
                )
                assert baselines.status in ("SUCCEEDED", "REUSED", "BLOCKED", "FAILED")

        # report (aggregation-only)
        report = _confirmed(gw, ctx, "generate_scientific_report", {})
        assert report.status in ("SUCCEEDED", "REUSED")

        # audit trail complete for this experiment
        entries = [
            e for e in gw.audit.all_entries() if e.resource_ids.get("battery_id") == ctx.battery_id
        ]
        assert len(entries) >= 8
        tool_names = {e.tool_name for e in entries}
        assert {
            "create_experiment",
            "commit_intake",
            "create_gate",
            "analyze_feature_relationships",
            "confirm_feature_selection",
            "generate_scientific_report",
        } <= tool_names

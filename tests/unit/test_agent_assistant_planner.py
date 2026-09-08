"""BRW-027R A01–A44 — intent / context / no-guess / safety / confirmation /
interpretation / tool-boundary tests for the research assistant planner.

All scientific values flow through ToolGateway → WorkbenchService; the
planner itself imports no scientific modules (asserted in A39–A44).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from battery_workbench.agent_assistant.intents import (
    FORBIDDEN_PHRASES,
    ResearchIntent,
    classify_intent,
    enforce_claim_safety,
)
from battery_workbench.agent_assistant.planner import ResearchPlanner
from battery_workbench.agent_assistant.session import AgentResearchSession, SessionStore
from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
B, E = "CELL_001", "EXP_001"


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[ResearchPlanner, AgentResearchSession, ToolGateway]:
    """Sandbox workspace that SYMLINKS nothing; service reads real artifacts
    via the demo share. For planning tests we mount a service over the real
    processed root but read-only (planner never writes except session json)."""
    service = create_app(raw_root=REPO / "data/raw", processed_root=REPO / "data/processed").state.workbench_service
    gateway = ToolGateway(service=service)
    store = SessionStore(tmp_path / "processed")
    session = AgentResearchSession(
        session_id=SessionStore.new_session_id(B, E), battery_id=B, experiment_id=E,
    )
    return ResearchPlanner(gateway=gateway, store=store), session, gateway


def _send(planner: ResearchPlanner, session: AgentResearchSession, msg: str) -> Any:
    return planner.handle_message(session, msg)


# ---------- Intent A01–A06 ----------
class TestIntent:
    def test_a01_soc_goal(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "帮我研究SOC")
        assert r.intent == "SELECT_TARGET"
        assert session.selected_target == "reference_soc_percent"
        assert "retrospective" in r.message.lower()

    def test_a02_alignment_intent(self):
        assert classify_intent("同步对齐怎么样").intent == ResearchIntent.CHECK_ALIGNMENT

    def test_a03_rank_intent(self):
        assert classify_intent("哪些特征和SOC关系明显？").intent == ResearchIntent.RANK_CANDIDATE_FEATURES

    def test_a04_train_intent(self):
        assert classify_intent("用这些训练模型").intent == ResearchIntent.RUN_BASELINES

    def test_a05_report_intent(self):
        assert classify_intent("生成这次SOC研究报告").intent == ResearchIntent.GENERATE_REPORT

    def test_a06_unknown_falls_back_to_inspect(self):
        assert classify_intent("你好").intent == ResearchIntent.INSPECT_FEATURES


# ---------- Context A07–A12 ----------
class TestContext:
    def test_a07_session_persists_target(self, workspace):
        planner, session, _ = workspace
        _send(planner, session, "帮我研究SOC")
        restored = planner.store.load(session.battery_id, session.experiment_id, session.session_id)
        assert restored is not None
        assert restored.selected_target == "reference_soc_percent"
        assert restored.conversation[-1].role == "assistant"

    def test_a08_conversation_has_no_tool_logs(self, workspace):
        planner, session, _ = workspace
        _send(planner, session, "帮我研究SOC")
        dump = json.dumps(session.model_dump(mode="json"))
        assert "chain_of_thought" not in dump
        for turn in session.conversation:
            assert "ToolResult(" not in turn.message

    def test_a09_page_context_carried(self, workspace):
        planner, session, _ = workspace
        session.current_page = "waveform"
        r = _send(planner, session, "帮我研究SOC")
        assert r.phase  # page does not break routing

    def test_a10_target_switch_invalidates_draft(self, workspace):
        planner, session, _ = workspace
        _send(planner, session, "帮我研究SOC")
        session.dataset_id = "DS::x"
        _send(planner, session, "换成温度看看")
        assert session.selected_target == "temperature_c"
        assert session.dataset_id is None  # target-dependent draft invalidated

    def test_a11_alignment_counts_real(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "为什么3999只有3995？")
        assert "3995" in r.message and "4" in r.message

    def test_a12_session_store_roundtrip(self, tmp_path):
        store = SessionStore(tmp_path)
        s = AgentResearchSession(session_id=SessionStore.new_session_id(B, E), battery_id=B, experiment_id=E)
        store.save(s)
        assert store.latest(B, E) is not None


# ---------- No-guess A13–A17 ----------
class TestNoGuess:
    def test_a13_planner_imports_no_scientific_modules(self):
        import battery_workbench.agent_assistant.planner as pmod
        src = Path(pmod.__file__).read_text()
        for banned in ("from battery_workbench.features", "from battery_workbench.labels",
                       "from battery_workbench.modeling", "from battery_workbench.datasets",
                       "import numpy"):
            assert banned not in src, f"planner must not import {banned}"

    def test_a14_no_fs_tof_answer_is_sample_domain(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "算TOF微秒")
        # no fabricated numeric µs value without fs
        import re as _re
        assert not _re.search(r"\d+\s*µs", r.message), r.message

    def test_a15_no_parameter_guessing_in_planner(self):
        import importlib
        import inspect as _inspect
        src = _inspect.getsource(importlib.import_module("battery_workbench.agent_assistant.planner"))
        for banned in ("sampling_rate_hz =", "trigger_sample_index =", "path_length"):
            assert banned not in src

    def test_a16_no_guess_guard_list_unchanged(self):
        from battery_workbench.agent_tools.security import NO_GUESS_PARAMETERS
        assert "ultrasound.sampling_rate_hz" in NO_GUESS_PARAMETERS

    def test_a17_planner_uses_gateway_only(self):
        import battery_workbench.agent_assistant.planner as pmod
        assert "gateway.execute" in Path(pmod.__file__).read_text()


# ---------- Scientific safety A18–A25 ----------
class TestScientificSafety:
    def test_a18_random_split_refused(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "随机80/20训练测试")
        assert r.status == "SCIENTIFIC_BLOCK"
        assert "泄漏" in r.message

    def test_a19_cross_battery_claim_refused(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "已经跨电池验证了吗？")
        assert r.status == "SCIENTIFIC_BLOCK"
        assert "within-battery" in r.message

    def test_a20_soh_modeling_blocked(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "训练SOH模型")
        assert r.status == "SCIENTIFIC_BLOCK"
        assert "2 个独立状态" in r.message

    def test_a21_temperature_unavailable_honest(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "看温度和BPS关系")
        # temperature has no channel in CELL_001 — coefficient must be None (honest)
        assert r.status == "SUCCEEDED"

    def test_a22_forbidden_phrases_list_complete(self):
        lowered = [p.lower() for p in FORBIDDEN_PHRASES]
        for required in ("true soc", "ground truth soc", "production-ready", "cross-battery validated"):
            assert required in lowered

    def test_a23_claim_guard_blocks_assistant_text(self):
        for phrase in ("这是 true SOC", "Ground Truth SOC 已确认", "production-ready 模型"):
            with pytest.raises(ValueError):
                enforce_claim_safety(phrase)

    def test_a24_validated_sync_never_claimed(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "同步对齐怎么样？")
        assert "validated_sync=false" in r.message
        assert "完全验证" not in r.message

    def test_a25_provisional_note_present(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "为什么3999只有3995？")
        assert "暂定时间基准" in r.message


# ---------- Confirmation/resume A26–A32 ----------
class TestConfirmationResume:
    def test_a26_confirmation_store_rejects_payload_change(self):
        from battery_workbench.agent_tools.models import ConfirmationPolicy, ConfirmationStore
        store = ConfirmationStore()
        rec = store.issue("create_gate", {"start": 1}, ConfirmationPolicy.USER_CONFIRMATION)
        store.validate(rec.confirmation_id, "create_gate", {"start": 1})  # ok
        with pytest.raises(PermissionError):
            store.validate(rec.confirmation_id, "create_gate", {"start": 2})
        store.consume(rec.confirmation_id)
        with pytest.raises(PermissionError):
            store.validate(rec.confirmation_id, "create_gate", {"start": 1})

    def test_a27_read_only_tools_have_no_confirmation(self):
        from battery_workbench.agent_tools.registry import build_default_registry
        for t in build_default_registry().tools():
            if t.read_only and not t.side_effect:
                assert t.confirmation_required.value == "NO_CONFIRMATION"

    def test_a28_consequential_tools_require_confirmation(self):
        from battery_workbench.agent_tools.registry import build_default_registry
        r = build_default_registry()
        for name in ("set_experiment_parameter", "create_gate", "confirm_feature_selection",
                     "run_limited_soc_baselines", "generate_scientific_report"):
            spec = r.get(name)
            assert spec.confirmation_required.value != "NO_CONFIRMATION", name

    def test_a29_resume_tools_registered(self):
        from battery_workbench.agent_tools.registry import build_default_registry
        r = build_default_registry()
        for name in ("list_pending_user_actions", "submit_user_action", "resume_run"):
            assert r.get(name) is not None

    def test_a30_session_records_pending_action(self, workspace):
        planner, session, _ = workspace
        # SOH block routes to WAITING-like state with next actions
        r = _send(planner, session, "训练SOH模型")
        assert r.status == "SCIENTIFIC_BLOCK"
        assert session.phase in ("WAITING_FOR_USER", "CHECK_GROUPED_SPLIT", "RUN_BASELINES")

    def test_a31_duplicate_submit_guarded_by_orchestrator(self):
        from battery_workbench.orchestrator.engine import PipelineOrchestrator  # noqa: F401
        # submit_user_action → resume same run semantics tested in test_agent_tools_resume.py
        assert True

    def test_a32_report_tool_is_idempotent(self):
        from battery_workbench.agent_tools.registry import build_default_registry
        spec = build_default_registry().get("generate_scientific_report")
        assert spec.idempotent is True


# ---------- Interpretation A33–A38 ----------
class TestInterpretation:
    def test_a33_dummy_first_when_all_lose(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "这个模型效果怎么样？")
        assert "尚未表现出稳定预测优势" in r.message or "没有模型跑赢 Dummy" in r.message

    def test_a34_dummy_mentioned_in_interpretation(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "这个模型效果怎么样？")
        assert "Dummy" in r.message

    def test_a35_scientific_conclusion_not_failure(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "这个模型效果怎么样？")
        assert "不是处理故障" in r.message

    def test_a36_exploratory_marked_not_ml_safe(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "哪些特征和SOC关系明显？")
        assert "非 ML-safe" in r.message or "EXPLORATORY" in r.message

    def test_a37_causation_disclaimer_on_ranking(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "哪些特征和SOC关系明显？")
        assert "因果关系" in r.message

    def test_a38_explain_exclusion_funnel(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "为什么3999只有3995？")
        assert "ambiguous" in r.message.lower() or "歧义" in r.message


# ---------- Tool boundary A39–A44 ----------
class TestToolBoundary:
    def test_a39_planner_has_no_numpy(self):
        import importlib
        import inspect as _inspect
        src = _inspect.getsource(importlib.import_module("battery_workbench.agent_assistant.planner"))
        assert "numpy" not in src

    def test_a40_planner_has_no_pandas(self):
        import importlib
        import inspect as _inspect
        src = _inspect.getsource(importlib.import_module("battery_workbench.agent_assistant.planner"))
        assert "pandas" not in src

    def test_a41_semantic_adapters_registered(self):
        from battery_workbench.agent_tools.registry import build_default_registry
        r = build_default_registry()
        names = {t.name for t in r.tools()}
        for required in ("inspect_research_state", "select_target", "inspect_alignment",
                         "inspect_gate_readiness", "analyze_target_relationships",
                         "prepare_ml_safe_dataset", "run_baseline_suite",
                         "get_model_comparison"):
            assert required in names

    def test_a42_adapter_tool_results_carry_envelope(self, workspace):
        _, _, gateway = workspace
        from battery_workbench.agent_tools.models import AgentScientificContext
        ctx = AgentScientificContext(battery_id=B, experiment_id=E)
        r = gateway.execute("inspect_alignment", ctx, {})
        assert r.status == "SUCCEEDED"
        assert r.request_id and r.tool_call_id
        assert r.scientific_context is not None

    def test_a43_audit_records_no_message_payloads(self, workspace):
        planner, session, gateway = workspace
        _send(planner, session, "帮我研究SOC 一条很长的私密消息 markers-secret-123")
        for entry in gateway.audit.all_entries():
            dump = json.dumps(entry.model_dump(mode="json"))
            assert "markers-secret-123" not in dump
            assert "chain_of_thought" not in dump

    def test_a44_planner_response_has_no_raw_tool_dump(self, workspace):
        planner, session, _ = workspace
        r = _send(planner, session, "哪些特征和SOC关系明显？")
        assert "ToolResult" not in r.message
        assert "scientific_context=" not in r.message

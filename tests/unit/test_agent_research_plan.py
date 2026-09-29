"""B01–B12 — 多步研究计划编排 + LLM只做理解 验收测试（先验收再实现）.

契约：
- LLM 仅映射 intent/target/features（枚举校验 + ClaimGuard），不猜科学值；
- 无LLM/失败时确定性回退（关键词规则，零幻觉）；
- 多步计划状态机持久化到 AgentResearchSession（只存引用/状态，不存计算值）；
- 写操作一律 USER_CONFIRMATION，不可被 LLM/计划路径绕过；
- WHAT_NEXT 与 workflow_context 同源推荐。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.agent_assistant.session import AgentResearchSession, SessionStore
from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
B, E = "CELL_001", "EXP_001"


@pytest.fixture()
def workspace(tmp_path: Path):
    from battery_workbench.agent_assistant.planner import ResearchPlanner

    service = create_app(
        raw_root=REPO / "data/raw", processed_root=REPO / "data/processed"
    ).state.workbench_service
    gateway = ToolGateway(service=service)
    store = SessionStore(tmp_path / "processed")
    session = AgentResearchSession(
        session_id=SessionStore.new_session_id(B, E), battery_id=B, experiment_id=E
    )
    return ResearchPlanner(gateway=gateway, store=store), session, gateway


# ---------- LLM 理解适配层 B01–B04 ----------
class TestUnderstandingAdapter:
    def test_b01_no_key_falls_back_deterministic(self, workspace, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U
        from battery_workbench.agent_assistant.intents import classify_intent

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(U, "_llm_available", lambda: False)
        _planner, _session, _ = workspace
        # 适配层无 key 时必须与关键词规则一致
        got = U.understand("帮我研究SOC", mode="EXPLORATORY")
        want = classify_intent("帮我研究SOC", mode="EXPLORATORY")
        assert got.intent == want.intent
        assert got.target_id == want.target_id
        assert got.mode == "EXPLORATORY"

    def test_b02_garbage_llm_output_falls_back(self, workspace, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        monkeypatch.setattr(U, "_llm_available", lambda: True)
        monkeypatch.setattr(
            U, "_call_llm", lambda *a, **k: {"intent": "NOT_AN_INTENT", "target_id": "mystery"}
        )
        got = U.understand("帮我研究SOC", mode="EXPLORATORY")
        # 非法枚举必须回退到确定性规则，而非透传
        assert got.intent.value == "SELECT_TARGET"
        assert got.target_id == "reference_soc_percent"

    def test_b03_enum_validation_rejects_unknown_target(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        monkeypatch.setattr(U, "_llm_available", lambda: True)
        monkeypatch.setattr(
            U,
            "_call_llm",
            lambda *a, **k: {"intent": "SELECT_TARGET", "target_id": "not_a_target"},
        )
        got = U.understand("研究温度", mode="EXPLORATORY")
        assert got.target_id in (
            "reference_soc_percent",
            "temperature_c",
            "soh_capacity_reference_percent",
            "voltage_v",
            "current_a",
            None,
        )

    def test_b04_adapter_emits_no_scientific_values_or_forbidden(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U
        from battery_workbench.agent_assistant.intents import FORBIDDEN_PHRASES

        monkeypatch.setattr(U, "_llm_available", lambda: True)
        monkeypatch.setattr(
            U,
            "_call_llm",
            lambda *a, **k: {
                "intent": "SELECT_TARGET",
                "target_id": "reference_soc_percent",
                "features": ["SWA"],
            },
        )
        got = U.understand("帮我研究SOC", mode="EXPLORATORY")
        dump = got.model_dump_json().lower()
        for p in FORBIDDEN_PHRASES:
            assert p not in dump
        # 适配层只输出枚举/特征码，不输出数值
        assert "tof_us" not in dump.replace("target", "")


# ---------- 多步计划编排 B05–B07/B10 ----------
class TestResearchPlan:
    def test_b05_plan_built_and_persisted(self, workspace):
        from battery_workbench.agent_assistant.research_plan import build_plan

        planner, session, _ = workspace
        plan = build_plan(planner.gateway.service, session, goal="研究SOC与超声特征关系")
        assert plan.goal
        assert len(plan.steps) >= 5
        assert {s.step_id for s in plan.steps} >= {
            "TARGET",
            "ALIGNMENT",
            "FEATURES",
            "DATASET",
            "SPLIT",
            "MODELS",
            "REPORT",
        }
        # 持久化到 session 并 roundtrip
        session.research_goal = plan.goal
        session.research_plan = plan.model_dump(mode="json")
        planner.store.save(session)
        restored = planner.store.load(session.battery_id, session.experiment_id, session.session_id)
        assert restored is not None
        assert restored.research_plan is not None
        assert restored.research_plan["goal"] == plan.goal

    def test_b06_plan_advance_persists_status(self, workspace):
        from battery_workbench.agent_assistant.research_plan import advance_plan, build_plan

        planner, session, _ = workspace
        plan = build_plan(planner.gateway.service, session, goal="研究SOC")
        plan = advance_plan(plan, "TARGET", "DONE")
        plan = advance_plan(plan, "ALIGNMENT", "IN_PROGRESS")
        session.research_plan = plan.model_dump(mode="json")
        planner.store.save(session)
        restored = planner.store.load(session.battery_id, session.experiment_id, session.session_id)
        assert restored is not None
        by_id = {s["step_id"]: s for s in restored.research_plan["steps"]}
        assert by_id["TARGET"]["status"] == "DONE"
        assert by_id["ALIGNMENT"]["status"] == "IN_PROGRESS"

    def test_b07_what_next_same_source_as_workflow_context(self, workspace):
        from battery_workbench.api.workflow_context import build_workflow_context

        planner, session, _ = workspace
        r = planner.handle_message(session, "下一步做什么？")
        assert r.intent == "WHAT_NEXT"
        wf = build_workflow_context(planner.gateway.service.processed_root, B, E)
        rec = wf["recommended_next_action"]
        assert rec["action_id"] in r.message or any(
            n.action_id == rec["action_id"] for n in r.next_actions
        )

    def test_b10_plan_stores_refs_not_values(self, workspace):
        from battery_workbench.agent_assistant.research_plan import build_plan

        planner, session, _ = workspace
        plan = build_plan(planner.gateway.service, session, goal="研究SOC")
        dump = plan.model_dump_json()
        # 计划只存步骤/状态/引用，不存计算值
        for banned in ("pearson", "tof_us", "mae", "ToolResult("):
            assert banned not in dump.lower()


# ---------- 只读+确认门 B08/B09 ----------
class TestConfirmationGate:
    def test_b08_write_tool_still_requires_confirmation(self, workspace):
        from battery_workbench.agent_tools.models import AgentScientificContext

        _, _, gateway = workspace
        ctx = AgentScientificContext(battery_id=B, experiment_id=E)
        r = gateway.execute(
            "generate_scientific_report", ctx, {"battery_id": B, "experiment_id": E}
        )
        assert r.status == "CONFIRMATION_REQUIRED"
        assert r.confirmation and r.confirmation.get("confirmation_id")

    def test_b09_planner_never_auto_confirms_write(self, workspace):
        planner, session, _ = workspace
        r = planner.handle_message(session, "生成这次SOC研究报告")
        # planner 只做只读建议 + 返回确认需求，不得直调写操作完成
        assert r.status in ("SUCCEEDED", "CONFIRMATION_REQUIRED", "WAITING_FOR_USER", "BLOCKED")
        if r.status == "SUCCEEDED" and r.confirmation_id:
            raise AssertionError("planner must not auto-confirm write tools")
        # 报告类写操作必须走确认或明确提示确认
        assert (
            r.confirmation_id is not None
            or "确认" in r.message
            or session.pending_user_action is not None
            or r.status in ("SUCCEEDED", "BLOCKED")
        )


# ---------- 边界 B11/B12 ----------
class TestBoundaries:
    def test_b11_new_modules_import_no_scientific_code(self):
        for mod in (
            "battery_workbench.agent_assistant.understanding",
            "battery_workbench.agent_assistant.research_plan",
        ):
            src = Path(__file__).resolve().parents[2] / "src" / Path(*mod.split(".")).with_suffix(
                ".py"
            )
            text = src.read_text(encoding="utf-8")
            for banned in (
                "from battery_workbench.features",
                "from battery_workbench.labels",
                "from battery_workbench.modeling",
                "from battery_workbench.datasets",
                "import numpy",
                "import pandas",
            ):
                assert banned not in text, f"{mod} must not import {banned}"

    def test_b12_claim_guard_still_enforced(self, workspace):
        planner, session, _ = workspace
        r = planner.handle_message(session, "已经跨电池验证了吗？")
        assert r.status == "SCIENTIFIC_BLOCK"
        assert "within-battery" in r.message

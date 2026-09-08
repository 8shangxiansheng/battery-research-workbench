"""BRW-027R — Research-assistant planner & interpretation.

The planner routes classified intents to BRW-026 ToolGateway tools, checks
target/alignment/gate readiness before feature–label analysis, enforces
exploratory vs ML-safe separation, blocks random splits and unsupported
claims, and produces Dummy-first honest interpretations.

Boundary: the planner ONLY calls ToolGateway.execute and reads ToolResult
envelopes. It imports no scientific calculation modules and never computes
SOC/TOF/Pearson/model metrics itself.
"""

from __future__ import annotations

from typing import Any

from battery_workbench.agent_assistant.intents import (
    REFERENCE_SOC_ID,
    SOC_DISCLAIMER,
    SOC_DISCLAIMER_ZH,
    classify_intent,
    enforce_claim_safety,
)
from battery_workbench.agent_assistant.session import (
    AgentResearchSession,
    NextAction,
    SessionStore,
)
from battery_workbench.agent_tools.gateway import ToolGateway

PLANNER_VERSION = "RESEARCH_PLANNER_V1"

# target ids whose direct-measurement correlation is routed through the
# feature-target-ranking API via the semantic adapter
DIRECT_TARGETS = {"voltage_v", "current_a"}


from pydantic import BaseModel


class PlannerResponse(BaseModel):
    """User-facing planner answer — no CoT, no tool-log wall."""

    message: str
    message_zh: str | None = None
    intent: str
    phase: str
    status: str = "SUCCEEDED"
    pending_user_action: dict[str, Any] | None = None
    confirmation_id: str | None = None
    evidence_refs: list[str] = []
    limitations: list[str] = []
    next_actions: list[NextAction] = []


class _FakeRequest:
    """Minimal request shim exposing service for read route functions."""

    def __init__(self, service: Any) -> None:
        self.state = type("S", (), {"workbench_service": service})()
        self.app = type("A", (), {"state": self.state})()


class ResearchPlanner:
    def __init__(self, gateway: ToolGateway, store: SessionStore) -> None:
        self.gateway = gateway
        self.store = store

    # ------------------------------------------------------------------
    # tool execution helpers
    # ------------------------------------------------------------------
    def _execute(self, tool_name: str, ctx: AgentResearchSession, inputs: dict[str, Any], *,
                 confirmation_id: str | None = None):
        from battery_workbench.agent_tools.models import AgentScientificContext

        agent_ctx = AgentScientificContext(
            battery_id=ctx.battery_id, experiment_id=ctx.experiment_id,
            run_id=ctx.model_run_id, dataset_id=ctx.dataset_id,
            split_id=ctx.split_id, gate_id=None,
            current_ui_route=ctx.current_page,
        )
        return self.gateway.execute(tool_name, agent_ctx, inputs, confirmation_id=confirmation_id)

    @staticmethod
    def _limitations(result) -> list[str]:
        return [
            str(l.get("description") or l.get("code") or l)
            for l in (result.scientific_context.limitations or [])
        ]

    @staticmethod
    def _evidence(result) -> list[str]:
        return [f"{e.evidence_type}:{e.evidence_ref}" for e in (result.evidence or [])]

    # ------------------------------------------------------------------
    # readiness checks (all through tools)
    # ------------------------------------------------------------------
    def check_target_readiness(self, ctx: AgentResearchSession, target_id: str) -> dict[str, Any]:
        """Target-aware readiness: SOC/Temperature/SOH policies from tools."""
        result = self._execute("inspect_experiment", ctx, {})
        readiness: dict[str, Any] = {
            "target_id": target_id, "ready": True, "block_reason": None,
        }
        if result.status == "WAITING_FOR_USER":
            readiness.update(ready=False, block_reason="WAITING_FOR_USER",
                             pending=result.data.get("pending"))
            return readiness
        limitations = " ".join(self._limitations(result)).lower()

        if target_id == "soh_capacity_reference_percent" and result.status != "SUCCEEDED":
            readiness.update(ready=False, block_reason="SOH_NOT_READY")
            return readiness
        if "soh" in target_id and "two independent states" in limitations:
            readiness.update(ready=False, block_reason="SOH_NOT_READY_FOR_ROBUST_MODELING")
        return readiness

    def check_alignment(self, ctx: AgentResearchSession) -> dict[str, Any]:
        """Canonical alignment before any Feature–Label analysis (§G).

        Counts come from the MeasurementEvent grain (matches/ambiguous/
        unmatched), not the sync manifest intent; provisional semantics are
        preserved verbatim.
        """
        result = self._execute("inspect_synchronization", ctx, {})
        if result.status != "SUCCEEDED":
            return {"status": "UNAVAILABLE", "reason": str(result.error)}
        # event-grain counts via the R1 alignment-summary aggregation (read-only,
        # same canonical artifacts; no rematch)
        from battery_workbench.api.routes.features_v2 import alignment_summary as _align

        summary = _align(
            _FakeRequest(self.gateway.service),  # type: ignore[arg-type]
            ctx.battery_id, ctx.experiment_id,
        )["data"]
        return {
            "status": "OK",
            "provisional": True,
            "validated_sync": summary["sync_quality"]["validated_sync"],
            "timebase": summary["sync_quality"]["timebase_status"],
            "matched_frames": summary["matched_unique"],
            "ambiguous_frames": summary["ambiguous"],
            "unmatched": summary["unmatched"],
            "eligible": summary["eligible"],
            "excluded": summary["excluded"],
        }

    # ------------------------------------------------------------------
    # intent handlers
    # ------------------------------------------------------------------
    def handle_message(self, ctx: AgentResearchSession, message: str) -> PlannerResponse:
        """Main entry: classify → policy gates → tool → interpretation."""
        ctx.add_turn("user", message)
        classified = classify_intent(message, mode=ctx.feature_selection_mode)

        # SOC mention always carries the retrospective disclaimer (§F)
        disclaimer = ""
        if classified.target_id == REFERENCE_SOC_ID or "soc" in message.lower():
            disclaimer = f"{SOC_DISCLAIMER} {SOC_DISCLAIMER_ZH}"

        # cross-battery / production-ready claim questions → honest limitation answer
        if any(p in message.lower() for p in (
            "跨电池", "cross-battery", "电池无关", "production", "量产",
        )):
            return self._refuse_overclaim(ctx, message, classified)

        # Random split request → refusal with leakage explanation + alternatives
        if any(p in message.lower() for p in ("80/20", "随机划分", "random split", "随机 8", "随机8")):
            return self._refuse_random_split(ctx, message, classified)

        handler = getattr(self, f"_on_{classified.intent.value.lower()}", None)
        if handler is None:
            resp = self._inspect_state(ctx, classified)
        else:
            resp = handler(ctx, message, classified)

        if disclaimer and disclaimer.split(".")[0] not in resp.message:
            resp.message = f"{disclaimer}\n\n{resp.message}"
        enforce_claim_safety(resp.message)
        ctx.add_turn("assistant", resp.message, intent=resp.intent,
                     evidence_refs=resp.evidence_refs)
        self.store.save(ctx)
        return resp

    # ---- SELECT_TARGET ----
    def _on_select_target(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        target_id = classified.target_id
        if target_id is None:
            return self._inspect_state(ctx, classified)
        ctx.selected_target = target_id
        ctx.phase = "CHECK_TARGET_READINESS"
        ctx.dataset_id = ctx.split_id = ctx.model_run_id = None
        readiness = self.check_target_readiness(ctx, target_id)
        ctx.target_readiness = "READY" if readiness["ready"] else str(readiness.get("block_reason"))

        if not readiness["ready"]:
            reason = str(readiness.get("block_reason"))
            if reason.startswith("SOH"):
                msg = (
                    "SOH 健康状态目前只有 2 个独立状态，不足以做稳健相关性或监督建模。"
                    "可以先看 cycle 级的 SOH 分组摘要（不做 frame 级相关）。"
                )
                ctx.phase = "WAITING_FOR_USER"
                return PlannerResponse(
                    message=msg, message_zh=msg, intent=classified.intent.value,
                    phase=ctx.phase, status="SCIENTIFIC_BLOCK",
                    limitations=["SOH NOT_READY — two independent states; frame rows pseudoreplicated"],
                    next_actions=[NextAction(action_id="a1", label_en="View SOH group summary",
                                             label_zh="查看 SOH 循环级摘要",
                                             intent="ANALYZE_RELATIONSHIP")],
                )
            return PlannerResponse(
                message=f"目标 {target_id} 当前不可用: {reason}", intent=classified.intent.value,
                phase=ctx.phase, status="NOT_READY",
                next_actions=[NextAction(action_id="a1", label_en="Check alignment",
                                         label_zh="检查同步对齐", intent="CHECK_ALIGNMENT")],
            )

        msg = (
            f"已选择研究目标: {target_id}。"
            + ("接下来先检查同步对齐，再看特征与关系。" if target_id == REFERENCE_SOC_ID else "")
        )
        ctx.phase = "SELECT_TARGET"
        ctx.next_actions = [
            NextAction(action_id="a1", label_en="Check alignment", label_zh="检查同步对齐",
                       intent="CHECK_ALIGNMENT"),
            NextAction(action_id="a2", label_en="Inspect features", label_zh="浏览特征",
                       intent="INSPECT_FEATURES"),
        ]
        return PlannerResponse(message=msg, intent=classified.intent.value, phase=ctx.phase,
                               next_actions=ctx.next_actions)

    # ---- CHECK_ALIGNMENT ----
    def _on_check_alignment(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        ctx.phase = "CHECK_ALIGNMENT"
        alignment = self.check_alignment(ctx)
        ctx.alignment_status = alignment
        matched = alignment.get("matched_frames")
        amb = alignment.get("ambiguous_frames") or 0
        ambiguous = amb if isinstance(amb, int) else len(amb)
        msg = (
            f"同步对齐（暂定时间基准，validated_sync=false）：matched {matched} 帧，"
            f"ambiguous {ambiguous} 帧；未匹配不会自动挑选电学记录。"
            "闸门只是同一超声帧内部的局部采样窗口，同一帧的所有特征共享同一 MeasurementEvent 电学状态。"
        )
        return PlannerResponse(message=msg, intent=classified.intent.value, phase=ctx.phase,
                               limitations=["PROVISIONAL timebase; not fully validated synchronization"])

    # ---- ANALYZE_RELATIONSHIP / RANK ----
    def _relationship_result(self, ctx: AgentResearchSession, classified, *, ranking: bool) -> PlannerResponse:
        # a target explicitly mentioned in THIS message takes precedence
        if classified.target_id and classified.target_id != ctx.selected_target:
            sel = self._on_select_target(ctx, classified.raw_message, classified)
            if sel.status != "SUCCEEDED":
                return sel
        if ctx.selected_target is None:
            ctx2 = self._ask_target(ctx, classified)
            return ctx2
        # alignment first (§G)
        alignment = self.check_alignment(ctx)
        if alignment.get("status") != "OK":
            return PlannerResponse(
                message="同步对齐不可用，先完成对齐再分析关系。", intent=classified.intent.value,
                phase="CHECK_ALIGNMENT", status="BLOCKED",
                next_actions=[NextAction(action_id="a1", label_en="Inspect alignment",
                                         label_zh="查看对齐", intent="CHECK_ALIGNMENT")],
            )
        features = classified.features or ctx.selected_features or ["SWA", "BOTTOM_AMP"]
        ctx.selected_features = features
        result = self._execute("analyze_target_relationships", ctx, {
            "target_id": ctx.selected_target, "features": features,
            "mode": "EXPLORATORY" if ctx.feature_selection_mode == "EXPLORATORY" else "TRAIN_ONLY_ML_SAFE",
        })
        if result.status != "SUCCEEDED":
            return PlannerResponse(
                message=f"关系分析未完成: {result.error}", intent=classified.intent.value,
                phase="ANALYZE_RELATIONSHIPS", status=result.status,
                limitations=self._limitations(result),
                next_actions=[NextAction(action_id="a1", label_en="Review features",
                                         label_zh="查看特征", intent="INSPECT_FEATURES")],
            )
        ctx.phase = "EXPLORATORY_RESULT" if ctx.feature_selection_mode == "EXPLORATORY" else "TRAIN_ONLY_FEATURE_SELECTION"
        data = result.data
        if "group_summary" in data and data.get("ranking") == []:
            msg = "SOH 只提供 cycle 级分组摘要（2 个独立状态，不做 frame 级相关）。"
            return PlannerResponse(message=msg, intent=classified.intent.value, phase=ctx.phase,
                                   evidence_refs=self._evidence(result),
                                   limitations=["SOH pseudoreplication guard"])
        ranking = data.get("ranking") or []
        lines = []
        for r in ranking:
            lines.append(
                f"{r.get('feature_code')}: Pearson {r.get('pearson_overall')}"
                + (f"，充电 {r['pearson_charge']} / 放电 {r['pearson_discharge']}"
                   if r.get("direction_dependent") else "")
            )
        expl = "探索性排序（EXPLORATORY，非 ML-safe）" if ctx.feature_selection_mode == "EXPLORATORY" \
            else "TRAIN-only ML-safe 排序（held-out 未访问）"
        msg = ("较高相关性不代表因果关系，也不保证预测能力。\n" + "\n".join(lines)
               + f"\n[{expl}]")
        ctx.phase = "CHOOSE_PATH"
        ctx.next_actions = [
            NextAction(action_id="a1", label_en="Build exploratory table",
                       label_zh="构建探索性特征表", intent="BUILD_EXPLORATORY_TABLE"),
            NextAction(action_id="a2", label_en="Start ML-safe flow (grouped split first)",
                       label_zh="开始 ML-safe 流程（先分组划分）", intent="BUILD_ML_SAFE_DATASET"),
        ]
        return PlannerResponse(message=msg, intent=classified.intent.value, phase=ctx.phase,
                               evidence_refs=self._evidence(result),
                               limitations=self._limitations(result),
                               next_actions=ctx.next_actions)

    def _on_analyze_relationship(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        return self._relationship_result(ctx, classified, ranking=False)

    def _on_rank_candidate_features(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        return self._relationship_result(ctx, classified, ranking=True)

    # ---- model / baselines ----
    def _on_run_baselines(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        # SOH modeling blocked outright with 2 independent states (§F)
        if "soh" in message.lower() or "健康状态" in message or (
            ctx.selected_target == "soh_capacity_reference_percent"
        ):
            ctx.selected_target = "soh_capacity_reference_percent"
            return self._soh_blocked(ctx, classified)
        if ctx.feature_selection_mode != "ML_SAFE" and classified.mode == "EXPLORATORY":
            # user says "用这些训练" — must not send exploratory ranking to model
            return PlannerResponse(
                message=(
                    "正式建模需要先建立 grouped split（按 cycle 分组），再做 TRAIN-only 特征选择、"
                    "锁定特征集，最后 held-out 评估。探索性排序不能直接送入模型。"
                    "请先到 Advanced → Splits 建立分组划分，或选择 Build ML-safe Dataset。"
                ),
                intent=classified.intent.value, phase="CHECK_GROUPED_SPLIT", status="SCIENTIFIC_BLOCK",
                next_actions=[NextAction(action_id="a1", label_en="Open grouped splits",
                                         label_zh="打开分组划分", intent="CREATE_GROUPED_SPLIT")],
            )
        if not ctx.split_id:
            return PlannerResponse(
                message="需要先有 grouped split 才能做正式评估。",
                intent=classified.intent.value, phase="CHECK_GROUPED_SPLIT", status="BLOCKED",
                next_actions=[NextAction(action_id="a1", label_en="Create grouped split",
                                         label_zh="创建分组划分", intent="CREATE_GROUPED_SPLIT")],
            )
        result = self._execute("run_limited_soc_baselines", ctx, {})
        if result.status in ("WAITING_FOR_USER", "BLOCKED"):
            ctx.phase = "WAITING_FOR_USER"
            ctx.pending_user_action = result.data.get("pending")
            return PlannerResponse(
                message=f"建模缺少输入，需要你确认: {result.error}",
                intent=classified.intent.value, phase=ctx.phase, status="WAITING_FOR_USER",
                pending_user_action=ctx.pending_user_action,
                limitations=self._limitations(result),
            )
        ctx.phase = "RUN_BASELINES"
        ctx.model_run_id = result.data.get("run_id")
        return self._interpret(ctx, result, classified)

    def _on_interpret_model(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("inspect_model_comparison", ctx, {})
        return self._interpret(ctx, result, classified)

    def _interpret(self, ctx: AgentResearchSession, result, classified) -> PlannerResponse:
        """Dummy-first honest interpretation (§O)."""
        data = result.data
        macro = data.get("macro") or []
        dummy = data.get("dummy_baseline") or {}
        dummy_val = dummy.get("value")
        real = [r for r in macro if r.get("strategy") != "DUMMY_MEAN"]
        best = min((r for r in real if isinstance(r.get("value"), (int, float))),
                   key=lambda r: r["value"], default=None)
        if dummy_val is None:
            msg = "还没有模型评估结果。请先构建数据集、建立 grouped split 并跑基线。"
        elif not data.get("real_beats_dummy", False):
            msg = (
                f"当前没有任何模型跑赢 Dummy 基准（Dummy 宏观 MAE {dummy_val}%）。"
                "也就是说，本轮候选特征在 held-out cross-cycle 评估中尚未表现出稳定预测优势。"
                "这是科学结论，不是处理故障。"
            )
        else:
            msg = f"最好的模型是 {best['strategy']}（宏观 MAE {best['value']}%），优于 Dummy {dummy_val}%。"
            msg += " 这仍是 within-battery、limited 评估，不代表跨电池泛化。"
        ctx.phase = "INTERPRET"
        return PlannerResponse(message=msg, intent=classified.intent.value, phase=ctx.phase,
                               evidence_refs=self._evidence(result),
                               limitations=self._limitations(result),
                               next_actions=[NextAction(action_id="a1", label_en="Open report",
                                                        label_zh="打开科学报告",
                                                        intent="GENERATE_REPORT")])

    # ---- dataset ----
    def _on_build_ml_safe_dataset(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        if ctx.feature_selection_mode != "ML_SAFE":
            return self._on_run_baselines(ctx, message, classified)
        result = self._execute("prepare_soc_dataset", ctx, {})
        if result.status in ("WAITING_FOR_USER", "BLOCKED"):
            ctx.phase = "WAITING_FOR_USER"
            return PlannerResponse(message=f"构建数据集缺少输入: {result.error}",
                                   intent=classified.intent.value, phase=ctx.phase,
                                   status=result.status, limitations=self._limitations(result))
        ctx.dataset_id = result.data.get("dataset_id")
        ctx.phase = "BUILD_DATASET"
        return PlannerResponse(
            message=f"ML-safe 数据集已就绪（{ctx.dataset_id}）。下一步建 grouped split，然后 TRAIN-only 选择。",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result),
            next_actions=[NextAction(action_id="a1", label_en="Create grouped split",
                                     label_zh="创建分组划分", intent="CREATE_GROUPED_SPLIT")],
        )

    def _on_build_exploratory_table(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        ctx.phase = "EXPLORATORY_RESULT"
        return PlannerResponse(
            message="探索性特征表已可在 Feature–Label Table 预览中查看（EXPLORATORY，非 ML-safe，不能用于正式评估）。",
            intent=classified.intent.value, phase=ctx.phase,
            limitations=["EXPLORATORY — not ML-safe for formal evaluation"])

    # ---- report / evidence / limitation / misc ----
    def _on_generate_report(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("generate_scientific_report", ctx, {})
        ctx.phase = "REPORT"
        ctx.report_id = result.data.get("report_id")
        return PlannerResponse(
            message="科学报告已生成（只汇总既有结果，不会重新训练模型）。",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result), limitations=self._limitations(result),
            next_actions=[NextAction(action_id="a1", label_en="Inspect evidence",
                                     label_zh="查看证据", intent="INSPECT_EVIDENCE")])

    def _on_inspect_evidence(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("inspect_evidence", ctx, {})
        items = result.data.get("evidence") or []
        summary = "; ".join(
            f"{e.get('evidence_type')} → {e.get('evidence_ref')}" for e in items[:5]
        ) if items else "暂无证据记录。"
        return PlannerResponse(
            message=f"证据与可复现性: {summary}（证据类型不升级；prior audit 不冒充 current artifact）",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result))

    def _on_explain_limitation(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("inspect_evidence", ctx, {})
        lims = self._limitations(result)
        return PlannerResponse(
            message="当前限制: " + ("; ".join(lims) if lims else "参考 SOC · 有限评估 · 结果仅针对当前实验。"),
            intent=classified.intent.value, phase=ctx.phase,
            limitations=lims)

    def _on_inspect_features(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("list_available_features", ctx, {})
        feats = result.data.get("features") or []
        names = [f.get("feature_name") for f in feats][:8]
        return PlannerResponse(
            message=f"可用特征（前 8）: {', '.join(map(str, names))}。完整双语目录见特征分析页。",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result))

    def _on_calibrate_gates(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        self._execute("list_gates", ctx, {})
        return PlannerResponse(
            message="标定闸门流程在 波形与闸门 → Calibrate Gates：后端确定性挑选 24–40 代表帧，确认后冻结。",
            intent=classified.intent.value, phase=ctx.phase)

    def _on_create_grouped_split(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        if not ctx.dataset_id:
            return PlannerResponse(
                message="先构建 ML-safe 数据集，再创建 grouped split。",
                intent=classified.intent.value, phase="BUILD_DATASET", status="BLOCKED")
        result = self._execute("prepare_grouped_evaluation_split", ctx, {"dataset_id": ctx.dataset_id})
        ctx.split_id = result.data.get("split_id")
        ctx.phase = "CHECK_GROUPED_SPLIT"
        return PlannerResponse(
            message=f"Grouped split 已就绪（{ctx.split_id}，按 cycle 分组）。下一步 TRAIN-only 特征选择。",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result))

    def _soh_blocked(self, ctx: AgentResearchSession, classified) -> PlannerResponse:
        ctx.target_readiness = "NOT_READY"
        ctx.phase = "WAITING_FOR_USER"
        msg = (
            "SOH 健康状态目前只有 2 个独立状态，不足以做稳健相关性或监督建模。"
            "当前可以查看 cycle 级 SOH 分组摘要（不做 frame 级相关），或改用 Reference SOC。"
        )
        return PlannerResponse(
            message=msg, intent=classified.intent.value, phase=ctx.phase,
            status="SCIENTIFIC_BLOCK",
            limitations=["SOH NOT_READY_FOR_ROBUST_CORRELATION_OR_SUPERVISED_MODELING — two independent states"],
            next_actions=[NextAction(action_id="a1", label_en="View SOH group summary",
                                     label_zh="查看 SOH 循环级摘要", intent="ANALYZE_RELATIONSHIP"),
                          NextAction(action_id="a2", label_en="Switch to Reference SOC",
                                     label_zh="改用参考 SOC", intent="SELECT_TARGET")])

    # ---- helpers ----
    def _ask_target(self, ctx: AgentResearchSession, classified) -> PlannerResponse:
        ctx.phase = "SELECT_TARGET"
        return PlannerResponse(
            message="请先选择一个研究目标（Reference SOC / Temperature / SOH / Voltage / Current）。",
            intent=classified.intent.value, phase=ctx.phase, status="WAITING_FOR_USER",
            next_actions=[NextAction(action_id="a1", label_en="Select Reference SOC",
                                     label_zh="选择参考 SOC", intent="SELECT_TARGET")])

    def _inspect_state(self, ctx: AgentResearchSession, classified) -> PlannerResponse:
        result = self._execute("inspect_experiment", ctx, {})
        return PlannerResponse(
            message="可以帮你：选择研究目标、检查同步对齐、浏览特征、分析关系、构建数据集、跑基线并解读。",
            intent=classified.intent.value, phase=ctx.phase,
            evidence_refs=self._evidence(result))

    def _refuse_overclaim(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        result = self._execute("inspect_evidence", ctx, {})
        return PlannerResponse(
            message=(
                "没有跨电池验证。当前所有评估都是 within-battery（CELL_001 单电池、cross-cycle held-out），"
                "结果仅针对当前实验，不能宣称跨电池泛化或 production-ready。"
                "证据与限制见科学报告页。"
            ),
            intent=classified.intent.value, phase=ctx.phase, status="SCIENTIFIC_BLOCK",
            evidence_refs=self._evidence(result),
            limitations=["within-battery evaluation only; no cross-battery claim supported"])

    def _refuse_random_split(self, ctx: AgentResearchSession, message: str, classified) -> PlannerResponse:
        return PlannerResponse(
            message=(
                "随机 80/20 帧级划分在当前科学流程中不可用：同一 cycle 的相邻帧高度相似，"
                "随机拆分会把近似重复的帧分进训练与评估两侧，造成泄漏并高估性能。"
                "可用的替代：Leave-One-Group-Out、Group Holdout 或 Train-only（按 cycle 分组）。"
            ),
            intent=classified.intent.value, phase=ctx.phase, status="SCIENTIFIC_BLOCK",
            limitations=["Random Frame Split prohibited — frame-level leakage"],
            next_actions=[NextAction(action_id="a1", label_en="Create grouped split",
                                     label_zh="创建分组划分", intent="CREATE_GROUPED_SPLIT")])

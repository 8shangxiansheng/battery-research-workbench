"""BRW-027R+ — 多步研究计划（只编排，不做科学计算）.

契约：
- 计划步骤固定为 TARGET → ALIGNMENT → FEATURES → DATASET → SPLIT →
  MODELS → REPORT（与 workflow_context._STEPS 同源子集，不含 PREVIEW）；
- 每个步骤只存 step_id / title / status / ref（引用 id），不存任何
  科学计算值（B10：禁 pearson/tof_us/mae/ToolResult）；
- build_plan / advance_plan 纯函数式，不调科学模块、不做 I/O；
  持久化由调用方写入 AgentResearchSession.research_plan；
- 本模块不 import 任何科学计算模块与数值库（B11 断言保护）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PLAN_VERSION = "RESEARCH_PLAN_V1"

PlanStepId = Literal[
    "TARGET", "ALIGNMENT", "FEATURES", "DATASET", "SPLIT", "MODELS", "REPORT",
]

PlanStepStatus = Literal["TODO", "IN_PROGRESS", "DONE", "BLOCKED", "SKIPPED"]

_STEP_ORDER: tuple[PlanStepId, ...] = (
    "TARGET", "ALIGNMENT", "FEATURES", "DATASET", "SPLIT", "MODELS", "REPORT",
)

_STEP_TITLES: dict[PlanStepId, str] = {
    "TARGET": "选择研究目标",
    "ALIGNMENT": "复核同步对齐",
    "FEATURES": "选择候选特征",
    "DATASET": "构建 ML-safe 数据集",
    "SPLIT": "建立分组划分",
    "MODELS": "训练并对比基线模型",
    "REPORT": "生成科学报告",
}


class PlanStep(BaseModel):
    step_id: PlanStepId
    title: str
    status: PlanStepStatus = "TODO"
    # 只存引用（dataset_id/split_id/model_run_id/report_id 等），不存计算值
    ref: str | None = None
    note: str | None = None


class ResearchPlan(BaseModel):
    version: str = PLAN_VERSION
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)

    def by_id(self, step_id: PlanStepId) -> PlanStep | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    @property
    def current(self) -> PlanStep | None:
        for s in self.steps:
            if s.status in ("IN_PROGRESS", "TODO"):
                return s
        return None


def _seed_refs(session: Any) -> dict[str, str | None]:
    get = getattr(session, "__getattribute__", None)
    out: dict[str, str | None] = {}
    if get is None:
        return out
    try:
        out["DATASET"] = session.dataset_id
        out["SPLIT"] = session.split_id
        out["MODELS"] = session.model_run_id
        out["REPORT"] = session.report_id
        out["TARGET"] = session.selected_target
    except Exception:  # noqa: BLE001, S110 — session 形态变化时不阻塞建计划
        pass
    return out


def build_plan(service: Any, session: Any, *, goal: str) -> ResearchPlan:
    """从 session 已有引用 + 后端已物化产物推导初始步骤状态.

    只读：service 仅用于探测既有产物 id（若可用），失败即全 TODO；
    绝不触发构建/训练/计算。
    """
    refs = _seed_refs(session)
    done: set[PlanStepId] = set()
    if refs.get("TARGET"):
        done.add("TARGET")
    if session is not None and getattr(session, "alignment_status", None):
        done.add("ALIGNMENT")
    if getattr(session, "selected_features", None):
        done.add("FEATURES")
    for key in ("DATASET", "SPLIT", "MODELS", "REPORT"):
        if refs.get(key):
            done.add(key)  # type: ignore[arg-type]

    steps = [
        PlanStep(
            step_id=sid,
            title=_STEP_TITLES[sid],
            status="DONE" if sid in done else "TODO",
            ref=refs.get(sid),
        )
        for sid in _STEP_ORDER
    ]
    return ResearchPlan(goal=goal.strip() or "未命名研究目标", steps=steps)


def advance_plan(plan: ResearchPlan, step_id: PlanStepId, status: PlanStepStatus, *,
                 ref: str | None = None, note: str | None = None) -> ResearchPlan:
    """推进单个步骤状态（纯函数，返回同一 plan 对象以便调用方持久化）."""
    step = plan.by_id(step_id)
    if step is None:
        raise ValueError(f"unknown plan step: {step_id}")
    step.status = status
    if ref is not None:
        step.ref = ref
    if note is not None:
        step.note = note
    return plan


def plan_summary(plan: ResearchPlan) -> str:
    parts = [f"{s.step_id}:{s.status}" for s in plan.steps]
    cur = plan.current.step_id if plan.current else "ALL_DONE"
    return f"goal={plan.goal} current={cur} " + " ".join(parts)

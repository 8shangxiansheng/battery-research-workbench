"""BRW-027R — Research intent taxonomy + natural-language normalization.

Intents are classified from user phrasing; scientific values are NEVER
inferred here. "SOC" normalizes to Reference SOC with a mandatory
retrospective-reference disclaimer; no True SOC / Ground Truth wording is
ever produced or accepted.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

INTENT_VERSION = "RESEARCH_INTENT_TAXONOMY_V1"

REFERENCE_SOC_ID = "reference_soc_percent"
TARGET_ALIASES: dict[str, str] = {
    "soc": REFERENCE_SOC_ID,
    "reference soc": REFERENCE_SOC_ID,
    "参考soc": REFERENCE_SOC_ID,
    "temperature": "temperature_c",
    "温度": "temperature_c",
    "soh": "soh_capacity_reference_percent",
    "健康状态": "soh_capacity_reference_percent",
    "voltage": "voltage_v",
    "电压": "voltage_v",
    "current": "current_a",
    "电流": "current_a",
}

SOC_DISCLAIMER = (
    "Reference SOC is a retrospective segment-normalized reference label, "
    "not a directly measured state of charge."
)
SOC_DISCLAIMER_ZH = "参考SOC 是回顾性分段归一化参考标签，非真实 SOC。"

# wording the assistant must never emit
FORBIDDEN_PHRASES = (
    "true soc", "ground truth soc", "真实soc", "真实的soc",
    "fully validated synchronization", "完全验证同步",
    "production-ready", "cross-battery validated", "validated cross-battery",
    "robust battery-independent", "robust soh model",
)


class ResearchIntent(str, Enum):
    SELECT_TARGET = "SELECT_TARGET"
    CHECK_ALIGNMENT = "CHECK_ALIGNMENT"
    CALIBRATE_GATES = "CALIBRATE_GATES"
    INSPECT_FEATURES = "INSPECT_FEATURES"
    ANALYZE_RELATIONSHIP = "ANALYZE_RELATIONSHIP"
    RANK_CANDIDATE_FEATURES = "RANK_CANDIDATE_FEATURES"
    BUILD_EXPLORATORY_TABLE = "BUILD_EXPLORATORY_TABLE"
    BUILD_ML_SAFE_DATASET = "BUILD_ML_SAFE_DATASET"
    CREATE_GROUPED_SPLIT = "CREATE_GROUPED_SPLIT"
    RUN_BASELINES = "RUN_BASELINES"
    INTERPRET_MODEL = "INTERPRET_MODEL"
    GENERATE_REPORT = "GENERATE_REPORT"
    EXPLAIN_LIMITATION = "EXPLAIN_LIMITATION"
    INSPECT_EVIDENCE = "INSPECT_EVIDENCE"


class ClassifiedIntent(BaseModel):
    intent: ResearchIntent
    target_id: str | None = None
    features: list[str] = []
    mode: str = "EXPLORATORY"
    rationale: str = ""
    raw_message: str = ""


_INTENT_PATTERNS: list[tuple[ResearchIntent, tuple[str, ...]]] = [
    (ResearchIntent.SELECT_TARGET, ("研究soc", "研究温度", "研究soh", "研究电压", "研究电流",
     "换成温度", "换温度", "看看温度", "study soc", "switch to temperature")),
    (ResearchIntent.CHECK_ALIGNMENT, ("对齐", "同步", "匹配", "3999", "为什么只有", "alignment", "matched")),
    (ResearchIntent.CALIBRATE_GATES, ("标定", "标定闸门", "calibrate", "gate calibration")),
    (ResearchIntent.INSPECT_FEATURES, ("特征列表", "有哪些特征", "查看特征", "inspect features", "x和y", "x 和 y")),
    (ResearchIntent.ANALYZE_RELATIONSHIP, ("关系", "相关", "relationship", "correlation", "和soc关系", "和温度")),
    (ResearchIntent.RANK_CANDIDATE_FEATURES, ("哪些特征", "排序", "ranking", "关系明显", "candidate")),
    (ResearchIntent.BUILD_EXPLORATORY_TABLE, ("探索性特征表", "exploratory table", "探索表")),
    (ResearchIntent.BUILD_ML_SAFE_DATASET, ("构建数据集", "建数据集", "build dataset", "ml-safe dataset", "数据集")),
    (ResearchIntent.CREATE_GROUPED_SPLIT, ("分组划分", "grouped split", "划分数据", "80/20", "随机")),
    (ResearchIntent.RUN_BASELINES, ("训练", "跑基线", "run baseline", "建模", "train")),
    (ResearchIntent.INTERPRET_MODEL, ("效果怎么样", "模型效果", "结果怎么", "interpret", "效果如何", "模型怎么样")),
    (ResearchIntent.GENERATE_REPORT, ("报告", "生成报告", "report")),
    (ResearchIntent.EXPLAIN_LIMITATION, ("限制", "为什么不能", "limitation", "为什么不可")),
    (ResearchIntent.INSPECT_EVIDENCE, ("证据", "evidence", "可复现", "来源是什么")),
]


def normalize_target(text: str) -> str | None:
    lowered = text.lower().strip()
    for alias, target_id in TARGET_ALIASES.items():
        if alias in lowered:
            return target_id
    return None


def extract_features(text: str) -> list[str]:
    """Feature code extraction from phrasing — only exact known codes."""
    known = ["SWA", "BOTTOM_AMP", "TOF_XCORR", "ATTEN_MAX", "ATTEN_MEAN",
             "ATTEN_ENERGY", "BPS", "TDM", "TDSTD", "TDRMS2", "FDEQ", "FDAF"]
    found = [c for c in known if c.lower() in text.lower()]
    return found


def classify_intent(message: str, *, mode: str = "EXPLORATORY") -> ClassifiedIntent:
    """Deterministic keyword routing — no model inference, no guessing."""
    lowered = message.lower().strip()
    target_id = normalize_target(message)

    # explicit "SOH model" goes to RUN_BASELINES but the planner will block
    # via readiness; "temperature+BPS relationship" goes to ANALYZE_RELATIONSHIP
    for intent, patterns in _INTENT_PATTERNS:
        for p in patterns:
            if p in lowered:
                # SELECT_TARGET only when a target is actually mentioned
                if intent == ResearchIntent.SELECT_TARGET and target_id is None:
                    continue
                # RANK wins over ANALYZE for "哪些特征和SOC关系明显"
                if intent == ResearchIntent.ANALYZE_RELATIONSHIP and ("哪些特征" in lowered or "ranking" in lowered):
                    continue
                return ClassifiedIntent(
                    intent=intent, target_id=target_id,
                    features=extract_features(message), mode=mode,
                    rationale=f"matched pattern {p!r}", raw_message=message,
                )
    if target_id is not None:
        return ClassifiedIntent(intent=ResearchIntent.SELECT_TARGET, target_id=target_id,
                                features=extract_features(message), mode=mode,
                                rationale="target mention", raw_message=message)
    return ClassifiedIntent(intent=ResearchIntent.INSPECT_FEATURES, target_id=None,
                            features=extract_features(message), mode=mode,
                            rationale="fallback: inspect", raw_message=message)


def enforce_claim_safety(text: str) -> str:
    """ClaimGuard for assistant text: forbid unsupported phrases (§Q).

    Raises ValueError — the planner converts it into an honest refusal with
    the limitation restated instead of the blocked claim.
    """
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            raise ValueError(
                f"UNSUPPORTED_CLAIM: phrase {phrase!r} is not supported by current evidence"
            )
    return text

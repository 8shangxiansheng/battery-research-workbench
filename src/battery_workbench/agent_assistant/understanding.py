"""BRW-027R+ — LLM 理解适配层（只做理解，不做科学计算）.

契约：
- LLM 仅映射 intent / target / features，不猜任何科学数值；
- 输出必须通过枚举校验（ResearchIntent + 允许 target 清单 + 已知特征码）；
- 无 key / 无依赖 / 调用失败 / 非法枚举时，一律确定性回退到
  ``classify_intent``（关键词规则，零幻觉）；
- 本模块不 import 任何科学计算模块（features/labels/modeling/datasets）
  与数值库（numpy/pandas），B11 断言保护。
"""

from __future__ import annotations

import json
import os
from typing import Any

from battery_workbench.agent_assistant.intents import (
    ClassifiedIntent,
    ResearchIntent,
    classify_intent,
    enforce_claim_safety,
    extract_features,
)

ADAPTER_VERSION = "UNDERSTANDING_ADAPTER_V1"

_ALLOWED_TARGETS = frozenset(
    {
        "reference_soc_percent",
        "temperature_c",
        "soh_capacity_reference_percent",
        "voltage_v",
        "current_a",
    }
)

_ALLOWED_INTENTS = frozenset(e.value for e in ResearchIntent)

_KNOWN_FEATURES = frozenset(
    [
        "SWA",
        "BOTTOM_AMP",
        "TOF_XCORR",
        "ATTEN_MAX",
        "ATTEN_MEAN",
        "ATTEN_ENERGY",
        "BPS",
        "TDM",
        "TDSTD",
        "TDRMS2",
        "FDEQ",
        "FDAF",
    ]
)


def _llm_available() -> bool:
    """仅当显式配置 key 且未被测试 monkeypatch 关闭时才认为可用."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def _call_llm(message: str, *, mode: str = "EXPLORATORY") -> dict[str, Any]:
    """调用外部 LLM 做意图映射，返回原始 dict（调用方负责枚举校验）.

    默认实现走 OpenAI Chat Completions（JSON 模式）；无依赖/无 key/
    调用失败一律抛异常，由 ``understand`` 捕获并确定性回退。测试通过
    monkeypatch 替换本函数注入各种 LLM 输出。
    """
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("openai dependency unavailable") from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)
    schema_hint = (
        "Return STRICT JSON only with keys: intent (one of "
        + ", ".join(sorted(_ALLOWED_INTENTS))
        + "), target_id (one of "
        + ", ".join(sorted(_ALLOWED_TARGETS))
        + " or null), features (array of known codes). "
        "Do not output any numeric scientific values."
    )
    resp = client.chat.completions.create(
        model=os.environ.get("BRW_LLM_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": schema_hint},
            {"role": "user", "content": message},
        ],
        response_format={"type": "json_object"},
        max_tokens=256,
        timeout=15,
    )
    content = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned non-JSON: {content[:120]!r}") from exc
    if not isinstance(data, dict):
        raise TypeError("LLM returned non-object JSON")
    return data


def _sanitize_llm_output(
    raw: dict[str, Any], *, fallback: ClassifiedIntent, mode: str
) -> ClassifiedIntent:
    """枚举校验 + ClaimGuard；任一非法即整体回退到确定性结果."""
    try:
        intent_raw = raw.get("intent")
        if intent_raw not in _ALLOWED_INTENTS:
            return fallback
        intent = ResearchIntent(intent_raw)

        target_raw = raw.get("target_id")
        if target_raw is not None and target_raw not in _ALLOWED_TARGETS:
            # 非法 target 不透传，用回退的 target（B03）
            target_id = fallback.target_id
        else:
            target_id = target_raw if target_raw is None else str(target_raw)

        feats_raw = raw.get("features") or []
        if not isinstance(feats_raw, list):
            feats_raw = []
        features = [f for f in feats_raw if isinstance(f, str) and f in _KNOWN_FEATURES]
        # 与关键词提取取并集，但只保留已知码
        for f in fallback.features:
            if f in _KNOWN_FEATURES and f not in features:
                features.append(f)

        candidate = ClassifiedIntent(
            intent=intent,
            target_id=target_id,
            features=features,
            mode=mode,
            rationale="llm-mapped+enum-validated",
            raw_message=fallback.raw_message,
        )
        enforce_claim_safety(candidate.model_dump_json())
        return candidate
    except Exception:  # noqa: BLE001 — 任何校验异常都回退
        return fallback


def understand(message: str, *, mode: str = "EXPLORATORY") -> ClassifiedIntent:
    """LLM 理解入口：成功时返回枚举校验后的映射，失败时确定性回退."""
    fallback = classify_intent(message, mode=mode)
    if not _llm_available():
        return fallback
    try:
        raw = _call_llm(message, mode=mode)
    except Exception:  # noqa: BLE001 — LLM 路径永不抛给上游
        return fallback
    if not isinstance(raw, dict):
        return fallback
    # 防御：LLM 原始输出中若夹带禁语，直接回退
    try:
        enforce_claim_safety(json.dumps(raw, ensure_ascii=False))
    except ValueError:
        return fallback
    result = _sanitize_llm_output(raw, fallback=fallback, mode=mode)
    # 最后再确认无禁语 / 无数值泄漏（只允许枚举 + 特征码）
    try:
        enforce_claim_safety(result.model_dump_json())
    except ValueError:
        return fallback
    # 冗余提取兜底：若 LLM 漏掉文中明确的已知特征码，补上
    extra = extract_features(message)
    for f in extra:
        if f not in result.features:
            result.features.append(f)
    return result

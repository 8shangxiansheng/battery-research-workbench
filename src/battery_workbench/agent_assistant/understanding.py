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
from pathlib import Path
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


_LLM_ENV_NAMES = frozenset({"OPENAI_API_KEY", "OPENAI_BASE_URL", "BRW_LLM_MODEL"})


def _load_llm_env(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """只读解析仓库根 ``.env`` 的 LLM 三变量，缺文件返回 ``{}``.

    极简 KEY=VALUE 解析：跳过空行/``#`` 注释/无 ``=`` 行，剥离前后空格与
    单双引号；只认 ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` /
    ``BRW_LLM_MODEL``，其它变量一律拒绝（``.env`` 是全仓库共享空间）。
    永不新建或写入文件，无新依赖。默认读取当前工作目录下的 ``.env``
    （本地从仓库根启动服务、容器 WORKDIR 挂载 ``.env`` 均覆盖）。
    """
    target = Path(path) if path is not None else Path.cwd() / ".env"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {}
    data: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name not in _LLM_ENV_NAMES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1].strip()
        data[name] = value
    return data


def _llm_env_snapshot() -> dict[str, str]:
    """合并显式环境变量与 ``.env`` 文件值：显式环境优先.

    空字符串视为未设置（回退文件值，兼容 compose ``${VAR:-}`` 缺省透传
    的空串）；文件中的空值同样丢弃。每次调用重新读取文件，本地改
    ``.env`` 无需重启进程（Docker 仍需重建容器，见 USER_GUIDE）。
    """
    file_values = _load_llm_env()
    snap: dict[str, str] = {}
    for name in _LLM_ENV_NAMES:
        explicit = os.environ.get(name)
        if explicit:
            snap[name] = explicit
        elif file_values.get(name):
            snap[name] = file_values[name]
    return snap


def _llm_available() -> bool:
    """仅当快照中有 key（显式环境或 ``.env`` 文件）时才认为可用."""
    return bool(_llm_env_snapshot().get("OPENAI_API_KEY"))


def _call_llm(message: str, *, mode: str = "EXPLORATORY") -> dict[str, Any]:
    """调用外部 LLM 做意图映射，返回原始 dict（调用方负责枚举校验）.

    默认实现走 OpenAI Chat Completions（JSON 模式，兼容 DeepSeek 等
    OpenAI 兼容网关：``OPENAI_BASE_URL`` 透传给 client，未配置时为
    None 走官方默认地址）；无依赖/无 key/调用失败一律抛异常，由
    ``understand`` 捕获并确定性回退。测试通过 monkeypatch 替换本函数
    注入各种 LLM 输出。
    """
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("openai dependency unavailable") from exc

    snap = _llm_env_snapshot()
    api_key = snap.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key, base_url=snap.get("OPENAI_BASE_URL") or None)
    schema_hint = (
        "Return STRICT JSON only with keys: intent (one of "
        + ", ".join(sorted(_ALLOWED_INTENTS))
        + "), target_id (one of "
        + ", ".join(sorted(_ALLOWED_TARGETS))
        + " or null), features (array of known codes). "
        "Do not output any numeric scientific values."
    )
    resp = client.chat.completions.create(
        model=snap.get("BRW_LLM_MODEL") or "gpt-4o-mini",
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

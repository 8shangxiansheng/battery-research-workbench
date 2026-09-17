"""BRW-025R-WF-R2 — Scientific workflow-context read model.

GET /experiments/{b}/{e}/workflow-context

Single read-only aggregation that answers, for every page (Overview / Target /
Alignment / Features / Preview / Dataset / Split / Models / Report /
Assistant): what is the current step, per-step status, committed scientific
identity, artifact freshness, pending user action, blocking reason and the
one recommended next action.

Design contract (BRW-025R-WF master prompt §3/§42/§43):
- Aggregates EXISTING artifacts only (targets/alignment from canonical
  measurement_events + event_labels; dataset/split/model/analysis/report
  manifests; assistant session state; BRW-018R2 submission service). It
  NEVER recomputes science (no TOF, no CE, no correlation, no model metrics,
  no split) and NEVER writes artifacts.
- Draft/committed separation: only MATERIALIZED artifacts count as committed
  workflow state; in-page draft selections (not yet built) are invisible here
  by design — the read model is the committed scientific truth.
- Blocking is structured: blocking_code / blocking_message /
  required_action / scientific_reason (§25).
- Typed actions: every action carries action_id + route; the frontend maps
  action_id → route instead of each page re-deriving strings (§33/§34).

Status vocabulary per master prompt §7: COMPLETE / CURRENT / READY / BLOCKED
/ STALE / NOT_STARTED / LIMITED.
Freshness vocabulary per §23: CURRENT / STALE / LEGACY / SUPERSEDED / MISSING.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

_SCHEMA_VERSION = "workflow-context/1.0"

# Steps in canonical research order (master prompt §7). Frontend stepper,
# deep links and Resume Research all consume this exact ordering.
_STEPS = (
    "TARGET",
    "ALIGNMENT",
    "FEATURES",
    "PREVIEW",
    "DATASET",
    "SPLIT",
    "MODELS",
    "REPORT",
)

# API create_dataset/create_split write deterministic SPEC placeholders;
# materialization happens through a scientific Run (POST /runs). Master
# prompt §10 draft/committed separation: only materialized manifests count as
# committed workflow state; spec-pending entries surface as draft separately.
_SPEC_PENDING_STATUSES = {"SPEC_PENDING_RUN"}
_MATERIAL_STATUSES = {
    "READY_FOR_SPLIT", "READY_WITH_LIMITATIONS", "NOT_READY_FOR_MODEL_EVALUATION",
    "EMPTY", "FAILED",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# Experiment bases that establish identity (same set as WorkbenchService).
_EXPERIMENT_BASES = (
    "datasets", "labels", "synchronization", "parameters", "splits", "models",
    "gated_features", "feature_analysis", "features", "multimodal",
    "measurement_events", "electrical", "artifacts",
)


def _require_experiment(processed_root: Path, b: str, e: str) -> None:
    """404 for unknown experiments (§36 NOT_FOUND vs empty read)."""
    if any((processed_root / base / b / e).exists() for base in _EXPERIMENT_BASES):
        return
    raise APIError(ErrorCode.NOT_FOUND, "experiment not found")


def _latest_by_mtime(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def _fs_state(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Verified sampling-rate state from the parameter registry (no recompute)."""
    from battery_workbench.features_physical.canonical_tof import effective_fs

    ps_dir = processed_root / "parameters" / b / e
    newest: tuple[float | None, str | None] = (None, None)
    if ps_dir.is_dir():
        for manifest in sorted(ps_dir.glob("PS::*/effective_parameters.json")):
            eff = _read_json(manifest) or {}
            eff = eff.get("effective_parameters") or eff
            fs, verified = effective_fs(eff, require_verified=True)
            if verified:
                return {
                    "sampling_rate_hz": fs,
                    "sampling_rate_verified": True,
                    "parameter_set_id": manifest.parent.name,
                }
            if fs is not None and newest[0] is None:
                newest = (fs, manifest.parent.name)
    return {
        "sampling_rate_hz": newest[0],
        "sampling_rate_verified": False,
        "parameter_set_id": newest[1],
    }


def _pending_submissions(processed_root: Path, b: str, e: str) -> list[dict[str, Any]]:
    """BRW-018R2 WAITING submissions — same service the Assistant uses."""
    path = processed_root / "parameter_submissions" / b / e / "submissions.json"
    data = _read_json(path) or {}
    pending: list[dict[str, Any]] = []
    for sub in data.values():
        if not isinstance(sub, dict):
            continue
        if sub.get("save_status") == "SAVED" and not sub.get("pending_action_resolved"):
            pending.append(
                {
                    "submission_id": sub.get("submission_id"),
                    "parameter_set_id": sub.get("parameter_set_id"),
                    "fs_value": sub.get("fs_value"),
                    "fs_unit": sub.get("fs_unit"),
                    "resume_status": sub.get("resume_status"),
                }
            )
    return pending


def _target_step(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Target readiness from canonical artifacts (same join as /targets)."""
    events_path = processed_root / "multimodal" / b / e / "measurement_events.parquet"
    labels_path = processed_root / "labels" / b / e / "event_labels.parquet"
    if not events_path.is_file() or not labels_path.is_file():
        return {
            "status": "BLOCKED",
            "committed": None,
            "blocking": {
                "blocking_code": "CANONICAL_EVENTS_MISSING",
                "blocking_message": "measurement_events/event_labels 不可用",
                "required_action": "REVIEW_ALIGNMENT",
                "scientific_reason": "目标就绪需要规范化事件与标签产物",
            },
        }
    import pandas as pd

    events = pd.read_parquet(events_path)
    labels = pd.read_parquet(labels_path)
    joined = events.merge(labels, on="measurement_event_id", how="left", suffixes=("", "_label"))
    eligible = joined["analysis_eligible"] if "analysis_eligible" in joined.columns else None
    soc = joined.get("soc_reference_percent")
    target_count = 0
    if soc is not None and eligible is not None:
        target_count = int(soc[eligible.astype(bool)].notna().sum())
    status = "COMPLETE" if target_count > 0 else "BLOCKED"
    out: dict[str, Any] = {
        "status": status,
        "committed": {"target_id": "soc_reference_percent", "coverage_eligible": target_count},
    }
    if status == "BLOCKED":
        out["blocking"] = {
            "blocking_code": "TARGET_COVERAGE_EMPTY",
            "blocking_message": "无 SOC 参考标签覆盖",
            "required_action": "REVIEW_ALIGNMENT",
            "scientific_reason": "特征-目标数据集要求 eligible 事件上有参考 SOC",
        }
    return out


def _alignment_step(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    manifest = _read_json(
        processed_root / "synchronization" / b / e / "synchronization_manifest.json"
    ) or {}
    events_path = processed_root / "multimodal" / b / e / "measurement_events.parquet"
    if not events_path.is_file():
        return {
            "status": "BLOCKED",
            "committed": None,
            "blocking": {
                "blocking_code": "CANONICAL_EVENTS_MISSING",
                "blocking_message": "measurement_events 不可用",
                "required_action": "REVIEW_ALIGNMENT",
                "scientific_reason": "对齐状态依赖规范化事件产物",
            },
        }
    import pandas as pd

    events = pd.read_parquet(events_path)
    total = len(events)
    if "analysis_eligible" in events.columns:
        eligible = int(events["analysis_eligible"].sum())
    else:
        eligible = 0
    matched = matched_unique = 0
    if "match_status" in events.columns:
        matched_unique = int((events["match_status"] == "MATCHED_UNIQUE").sum())
        matched = matched_unique + int((events["match_status"] == "MATCHED_AMBIGUOUS").sum())
    status = "COMPLETE" if total > 0 else "NOT_STARTED"
    return {
        "status": status,
        "committed": {
            "timebase_status": manifest.get("timebase_status", "PROVISIONAL"),
            "total_frames": total,
            "matched": matched,
            "matched_unique": matched_unique,
            "eligible": eligible,
            "excluded": total - eligible,
        },
    }


def _feature_analysis_latest(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    root = processed_root / "feature_analysis" / b / e
    if not root.is_dir():
        return None
    manifests = list(root.rglob("analysis_manifest.json"))
    latest = _latest_by_mtime(manifests)
    if latest is None:
        return None
    return _read_json(latest)


def _dataset_latest(processed_root: Path, b: str, e: str) -> tuple[dict[str, Any] | None, Path | None]:
    """Latest MATERIALIZED dataset manifest over all families.

    SPEC_PENDING_RUN manifests are drafts (API spec placeholders pending a
    scientific run) — reported via dataset_drafts, never as committed state.
    """
    root = processed_root / "datasets" / b / e
    if not root.is_dir():
        return None, None
    manifests = [
        p for p in root.glob("*/DS::*/dataset_manifest.json")
        if (_read_json(p) or {}).get("dataset_status") not in _SPEC_PENDING_STATUSES
    ]
    latest = _latest_by_mtime(manifests)
    if latest is None:
        return None, None
    return _read_json(latest), latest


def _dataset_drafts(processed_root: Path, b: str, e: str) -> list[dict[str, Any]]:
    """Spec-pending dataset placeholders (drafts, §10 — not committed)."""
    root = processed_root / "datasets" / b / e
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("*/DS::*/dataset_manifest.json")):
        data = _read_json(p) or {}
        if data.get("dataset_status") in _SPEC_PENDING_STATUSES:
            out.append(
                {
                    "dataset_id": data.get("dataset_id"),
                    "dataset_status": data.get("dataset_status"),
                    "target_name": data.get("target_name"),
                    "selected_features": data.get("selected_features"),
                }
            )
    return out


def _split_latest(
    processed_root: Path, b: str, e: str, dataset_id: str | None
) -> dict[str, Any] | None:
    """Latest MATERIALIZED split manifest for the committed dataset.

    Spec-pending split placeholders are drafts (§10) and never committed
    state; a split must belong to the committed dataset_id.
    """
    root = processed_root / "splits" / b / e
    if not root.is_dir() or dataset_id is None:
        return None
    manifests = []
    for m in root.rglob("split_manifest.json"):
        data = _read_json(m) or {}
        if data.get("dataset_id") != dataset_id:
            continue
        if data.get("readiness_status") in _SPEC_PENDING_STATUSES:
            continue
        manifests.append(m)
    latest = _latest_by_mtime(manifests)
    return _read_json(latest) if latest else None


def _models_for_split(
    processed_root: Path, b: str, e: str, dataset_id: str | None
) -> list[dict[str, Any]]:
    """Model manifests for the committed dataset (across all its splits)."""
    root = processed_root / "models" / b / e
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for m in root.rglob("model_manifest.json"):
        data = _read_json(m) or {}
        if dataset_id and data.get("dataset_id") != dataset_id:
            continue
        out.append(data)
    return out


def _report_latest(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    root = processed_root / "artifacts" / b / e / "reports"
    if not root.is_dir():
        return None
    latest = _latest_by_mtime(list(root.rglob("scientific_report.json")))
    if latest is None:
        return None
    data = _read_json(latest) or {}
    data["_path"] = str(latest)
    return data


def _assistant_state(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    root = processed_root / "assistant_sessions" / b / e
    if not root.is_dir():
        return None
    latest = _latest_by_mtime(list(root.glob("RS::*.json")))
    if latest is None:
        return None
    return _read_json(latest)


def _route(b: str, e: str, page: str) -> str:
    return f"/experiments/{b}/{e}/{page}"


def _typed_actions(b: str, e: str, entries: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """Typed actions: action_id → route; labels are bilingual short hints."""
    zh = {
        "REVIEW_TARGET": "选择参考 SOC 目标",
        "REVIEW_ALIGNMENT": "复核同步对齐",
        "CONFIGURE_FEATURES": "选择特征（特征分析）",
        "OPEN_PREVIEW": "查看 Feature–Label 预览",
        "BUILD_DATASET": "构建（物化）数据集",
        "CREATE_SPLIT": "建立分组划分",
        "TRAIN_MODELS": "训练并对比基线模型",
        "OPEN_REPORT": "查看研究报告",
        "RESOLVE_PENDING_ACTION": "处理待办参数提交",
    }
    return [
        {"action_id": aid, "label": zh.get(aid, aid), "route": _route(b, e, page)}
        for aid, page, _ in entries
    ]


def _freshness_of_dataset(dm: dict[str, Any] | None) -> str:
    """§23 freshness for the dataset artifact (definitions/TOF provenance).

    LEGACY = materialized before BRW-017R2 canonical TOF provenance
    (manifest lacks tof_method_id) — refresh required, not silently reused.
    """
    if dm is None:
        return "MISSING"
    if "tof_method_id" not in dm:
        return "LEGACY"
    return "CURRENT"


def build_workflow_context(
    processed_root: Path, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Assemble the ScientificWorkflowContext (pure read; no artifact writes)."""
    b, e = battery_id, experiment_id
    validate_id(b, "battery_id")
    validate_id(e, "experiment_id")
    _require_experiment(processed_root, b, e)

    fs_state = _fs_state(processed_root, b, e)
    pending = _pending_submissions(processed_root, b, e)

    target = _target_step(processed_root, b, e)
    alignment = _alignment_step(processed_root, b, e)
    fa = _feature_analysis_latest(processed_root, b, e)
    dm, _ds_path = _dataset_latest(processed_root, b, e)
    dataset_id = (dm or {}).get("dataset_id")
    split = _split_latest(processed_root, b, e, dataset_id)
    split_id = (split or {}).get("split_id")
    models = _models_for_split(processed_root, b, e, dataset_id)
    report = _report_latest(processed_root, b, e)
    assistant = _assistant_state(processed_root, b, e)

    dataset_freshness = _freshness_of_dataset(dm)
    # §23 stale chain: definitions/TOF change → dataset legacy → models/report stale
    model_freshness = "MISSING" if not models else ("STALE" if dataset_freshness in {"STALE", "LEGACY"} else "CURRENT")
    report_freshness = "MISSING" if report is None else ("STALE" if model_freshness in {"STALE", "LEGACY"} else "CURRENT")

    # ---------- per-step statuses ----------
    steps: dict[str, dict[str, Any]] = {}

    steps["TARGET"] = target
    steps["ALIGNMENT"] = alignment

    if fa is None:
        steps["FEATURES"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "FEATURE_ANALYSIS_MISSING", "特征分析未物化", "CONFIGURE_FEATURES",
                "特征-目标研究需要先物化一份特征分析（含选择集）",
            ),
        }
    else:
        selection = fa.get("selection") or {}
        selected = selection.get("selected_features") or []
        steps["FEATURES"] = {
            "status": "COMPLETE" if selected else "LIMITED",
            "committed": {
                "analysis_id": fa.get("analysis_id"),
                "analysis_mode": fa.get("analysis_mode"),
                "target": fa.get("target"),
                "selected_features": selected,
                "selection_basis": selection.get("selection_basis"),
            },
        }

    features_selected = bool((steps["FEATURES"].get("committed") or {}).get("selected_features"))
    if not features_selected:
        steps["PREVIEW"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "FEATURE_SELECTION_MISSING", "未选择特征", "CONFIGURE_FEATURES",
                "Feature–Label 预览要求先有已选特征",
            ),
        }
    elif dm is not None:
        # a materialized dataset implies a confirmed preview (§19: preview
        # spec_hash / target / features hand off to the dataset build)
        steps["PREVIEW"] = {
            "status": "COMPLETE",
            "committed": None,
            "note": "preview 是页面内 draft；物化数据集即确认完成（不自动 materialize）",
        }
    else:
        steps["PREVIEW"] = {
            "status": "READY",
            "committed": None,
            "note": "preview 为页面内 draft；确认后由 Dataset step 物化 spec（不自动）",
        }

    if dm is None:
        steps["DATASET"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "draft": _dataset_drafts(processed_root, b, e) or None,
            "blocking": _block(
                "DATASET_MISSING", "未物化数据集", "BUILD_DATASET",
                "分组划分与建模要求已物化数据集",
            ),
        }
    else:
        status = "COMPLETE"
        if dm.get("dataset_status") == "NOT_READY_FOR_MODEL_EVALUATION":
            status = "LIMITED"
        steps["DATASET"] = {
            "status": status,
            "committed": {
                "dataset_id": dataset_id,
                "dataset_status": dm.get("dataset_status"),
                "target_name": dm.get("target_name"),
                "selected_features": dm.get("selected_features"),
                "eligible_rows": dm.get("eligible_rows"),
                "feature_set_id": dm.get("feature_set_id"),
                "analysis_slice_id": dm.get("analysis_slice_id"),
            },
        }

    if dataset_id is None:
        steps["SPLIT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "DATASET_MISSING", "数据集未物化", "BUILD_DATASET",
                "分组划分必须建立在已物化数据集上",
            ),
        }
    elif split is None:
        steps["SPLIT"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "SPLIT_MISSING", "未建立分组划分", "CREATE_SPLIT",
                "ML-safe 建模与模型对比要求 grouped split（按 cycle 分组）",
            ),
        }
    else:
        status = "COMPLETE"
        if split.get("readiness_status") == "NOT_READY_FOR_MODEL_EVALUATION":
            status = "LIMITED"
        steps["SPLIT"] = {
            "status": status,
            "committed": {
                "split_id": split_id,
                "strategy": split.get("strategy"),
                "readiness_status": split.get("readiness_status"),
                "fold_count": split.get("fold_count"),
                "dataset_id": split.get("dataset_id"),
            },
        }

    split_ready = bool(
        split is not None and split.get("readiness_status") == "READY_FOR_LIMITED_EVALUATION"
    )
    if not split_ready:
        steps["MODELS"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "VALID_SPLIT_REQUIRED",
                "无合法 grouped split" if split is None else "split 就绪状态不足",
                "CREATE_SPLIT",
                "ML-safe 建模必须建立在合法分组划分（按 cycle 分组）上",
            ),
        }
    elif not models:
        steps["MODELS"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "MODELS_MISSING", "未训练基线模型", "TRAIN_MODELS",
                "Dummy-first 基线对比是结论的前提",
            ),
        }
    else:
        steps["MODELS"] = {
            "status": "COMPLETE",
            "committed": {
                "model_count": len(models),
                "model_ids": [m.get("model_id") for m in models],
                "split_ids": sorted({m.get("split_id") for m in models if m.get("split_id")}),
                "dataset_id": dataset_id,
            },
        }

    if not models:
        steps["REPORT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "MODELS_MISSING", "无模型结果", "TRAIN_MODELS",
                "报告需要至少一组基线模型对比结果",
            ),
        }
    elif report is None:
        steps["REPORT"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "REPORT_MISSING", "未生成报告", "OPEN_REPORT",
                "所有前置已满足，可生成研究报告",
            ),
        }
    else:
        steps["REPORT"] = {
            "status": "COMPLETE",
            "committed": {
                "report_id": report.get("report_id"),
            },
        }

    # ---------- current step + recommended next action ----------
    # current = latest COMPLETE step (workflow position); recommended = first
    # non-complete actionable step (§24: all pages consume the same answer).
    current_step = None
    for s in ("REPORT", "MODELS", "SPLIT", "DATASET", "FEATURES", "ALIGNMENT", "TARGET"):
        if steps[s]["status"] in ("COMPLETE", "LIMITED"):
            current_step = s
            break

    _page_by_step = {
        "TARGET": "analysis",
        "ALIGNMENT": "analysis",
        "FEATURES": "analysis",
        "PREVIEW": "analysis",
        "DATASET": "analysis",
        "SPLIT": "dataset-split",
        "MODELS": "models",
        "REPORT": "report",
    }
    _first_action = {
        "TARGET": ("REVIEW_TARGET", "选择参考 SOC 目标"),
        "ALIGNMENT": ("REVIEW_ALIGNMENT", "复核同步对齐"),
        "FEATURES": ("CONFIGURE_FEATURES", "选择特征（特征分析）"),
        "PREVIEW": ("OPEN_PREVIEW", "查看 Feature–Label 预览"),
        "DATASET": ("BUILD_DATASET", "构建（物化）数据集"),
        "SPLIT": ("CREATE_SPLIT", "建立分组划分"),
        "MODELS": ("TRAIN_MODELS", "训练并对比基线模型"),
        "REPORT": ("OPEN_REPORT", "查看研究报告"),
    }
    recommended = None
    all_complete = all(steps[s]["status"] == "COMPLETE" for s in _STEPS)
    if not fs_state["sampling_rate_verified"]:
        # BLOCKED prerequisite dominates every downstream step (§26/§27)
        recommended = {
            "step": "TARGET",
            "action_id": "PROVIDE_SAMPLING_RATE",
            "label": "填写并验证采样频率（参数注册表；绝不猜测）",
        }
    elif pending:
        recommended = {
            "step": "TARGET",
            "action_id": "RESOLVE_PENDING_ACTION",
            "label": "处理待恢复的参数提交（same-run resume）",
        }
    elif all_complete and dataset_freshness in ("STALE", "LEGACY"):
        # §23 stale chain: definitions/TOF changed → dataset (and downstream
        # models/report) were built against superseded provenance
        recommended = {
            "step": "DATASET",
            "action_id": "BUILD_DATASET",
            "label": "用 canonical TOF 特征重物化数据集（当前为 legacy/stale）",
        }
    else:
        for s in _STEPS:
            st = steps[s]["status"]
            if st == "COMPLETE":
                continue
            if st in ("READY", "NOT_STARTED", "BLOCKED", "STALE", "LIMITED"):
                action_id, label = _first_action[s]
                recommended = {"step": s, "action_id": action_id, "label": label}
                break
    if recommended is None:
        recommended = {"step": "REPORT", "action_id": "OPEN_REPORT", "label": "查看研究报告"}

    # ---------- pending / waiting (§26/§27/§28) ----------
    pending_action = None
    if not fs_state["sampling_rate_verified"]:
        pending_action = {
            "action_id": "PROVIDE_SAMPLING_RATE",
            "status": "WAITING_FOR_USER",
            "label": "填写并验证采样频率（参数注册表；绝不猜测）",
            "route": _route(b, e, "overview"),
            "scientific_reason": "canonical TOF 需要 VERIFIED 采样频率",
        }
    elif pending:
        pending_action = {
            "action_id": "RESOLVE_PENDING_ACTION",
            "status": "WAITING_FOR_USER",
            "label": "有待恢复的参数提交（same-run resume）",
            "route": _route(b, e, "overview"),
            "scientific_reason": "BRW-018R2 提交等待恢复",
            "submissions": pending,
        }

    # ---------- scientific context (§3) ----------
    ds_committed = steps["DATASET"].get("committed") or {}
    features_committed = (steps["FEATURES"].get("committed") or {})
    # first structured blocking among incomplete steps (§25)
    blocking_reason = None
    for s in _STEPS:
        st = steps[s].get("blocking")
        if st:
            blocking_reason = {"step": s, **st}
            break
    scientific_context = {
        "experiment_id": e,
        "battery_id": b,
        "target_id": (target.get("committed") or {}).get("target_id"),
        "target_status": target["status"],
        "alignment_status": alignment["status"],
        "eligible_count": (alignment.get("committed") or {}).get("eligible"),
        "excluded_count": (alignment.get("committed") or {}).get("excluded"),
        "selected_feature_locators": features_committed.get("selected_features") or [],
        "feature_selection_source": "FEATURE_ANALYSIS" if fa else None,
        "feature_selection_status": steps["FEATURES"]["status"],
        "preview_spec_hash": None,
        "preview_mode": None,
        "dataset_id": ds_committed.get("dataset_id"),
        "dataset_status": ds_committed.get("dataset_status"),
        "split_id": (steps["SPLIT"].get("committed") or {}).get("split_id"),
        "split_status": steps["SPLIT"]["status"],
        "model_run_id": None,
        "model_ids": [m.get("model_id") for m in models],
        "model_status": steps["MODELS"]["status"],
        "report_id": (steps["REPORT"].get("committed") or {}).get("report_id"),
        "report_status": steps["REPORT"]["status"],
        "pending_action": pending_action,
        "blocking_reason": blocking_reason,
        "recommended_next_action": {
            "action_id": recommended["action_id"],
            "step": recommended["step"],
        },
        "artifact_freshness": {
            "dataset": dataset_freshness,
            "models": model_freshness,
            "report": report_freshness,
        },
        "limitations": [
            "PROVISIONAL_TIMEBASE",
            "LIMITED_CROSS_CYCLE_GENERALIZATION",
            "ONE_BATTERY_ONLY",
        ],
    }

    # ---------- assistant context (§32) ----------
    assistant_context = None
    if assistant:
        assistant_context = {
            "session_id": assistant.get("session_id"),
            "phase": assistant.get("phase"),
            "pending_user_action": assistant.get("pending_user_action"),
            "next_actions": assistant.get("next_actions") or [],
        }

    return {
        "schema_version": _SCHEMA_VERSION,
        "battery_id": b,
        "experiment_id": e,
        "current_step": current_step,
        "step_statuses": {s: steps[s]["status"] for s in _STEPS},
        "steps": {s: steps[s] for s in _STEPS},
        "recommended_next_action": {
            "action_id": recommended["action_id"],
            "step": recommended["step"],
            "label": recommended.get("label"),
            "route": (
                _route(b, e, "overview")
                if recommended["action_id"] in ("PROVIDE_SAMPLING_RATE", "RESOLVE_PENDING_ACTION")
                else _route(b, e, _page_by_step[recommended["step"]])
            ),
        },
        "pending_action": pending_action,
        "artifact_freshness": {
            "dataset": dataset_freshness,
            "models": model_freshness,
            "report": report_freshness,
        },
        "scientific_context": scientific_context,
        "assistant_context": assistant_context,
        "typed_actions": _typed_actions(b, e, [
            ("REVIEW_TARGET", "analysis", ""),
            ("REVIEW_ALIGNMENT", "analysis", ""),
            ("CONFIGURE_FEATURES", "analysis", ""),
            ("OPEN_PREVIEW", "analysis", ""),
            ("BUILD_DATASET", "analysis", ""),
            ("CREATE_SPLIT", "dataset-split", ""),
            ("TRAIN_MODELS", "models", ""),
            ("OPEN_REPORT", "report", ""),
        ]),
        "meta": {
            "read_only": True,
            "no_recomputation": True,
            "notes": "只聚合已物化产物；不重算 TOF/CE/相关性/模型指标/split",
        },
    }


def _block(
    code: str, message: str, action: str, reason: str
) -> dict[str, str]:
    return {
        "blocking_code": code,
        "blocking_message": message,
        "required_action": action,
        "scientific_reason": reason,
    }

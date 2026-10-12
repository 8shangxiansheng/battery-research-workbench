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

import hashlib
import json
from pathlib import Path
from typing import Any

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.event_label_join import merge_event_labels
from battery_workbench.api.integrity import assert_processed_artifact_integrity
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
    "READY_FOR_SPLIT",
    "READY_WITH_LIMITATIONS",
    "NOT_READY_FOR_MODEL_EVALUATION",
    "EMPTY",
    "FAILED",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# Experiment bases that establish identity (same set as WorkbenchService).
_EXPERIMENT_BASES = (
    "datasets",
    "labels",
    "synchronization",
    "parameters",
    "splits",
    "models",
    "gated_features",
    "feature_analysis",
    "features",
    "multimodal",
    "measurement_events",
    "electrical",
    "artifacts",
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
        if sub.get("save_status") != "SAVED" or sub.get("pending_action_resolved"):
            continue
        # A SAVED submission only blocks the workflow when a run is actually
        # attached to resume. Run-less inspection/acceptance probes (BRW-018R2
        # visual-accept, inspect-probe) were completed at save time — surface
        # them as informational no-ops, not WAITING_FOR_USER dead ends.
        if not sub.get("run_id"):
            continue
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
    event_manifest_path = events_path.parent / "measurement_event_manifest.json"
    label_manifest_path = labels_path.parent / "label_manifest.json"
    try:
        assert_processed_artifact_integrity(
            processed_root,
            event_manifest_path,
            battery_id=b,
            experiment_id=e,
            required_outputs={"events", "candidates"},
            required_inputs={"aligned", "sync_candidates", "electrical_records"},
        )
        assert_processed_artifact_integrity(
            processed_root,
            label_manifest_path,
            battery_id=b,
            experiment_id=e,
            required_outputs={"event_labels"},
            required_inputs={"measurement_events", "records", "cycles", "steps"},
            required_manifest_fields={"label_set_id"},
            recovery_action="REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
        )
    except APIError as exc:
        reasons = exc.details.get("integrity_reasons") or ["CANONICAL_ARTIFACT_INVALID"]
        return {
            "status": "BLOCKED",
            "committed": None,
            "blocking": {
                "blocking_code": "TARGET_ARTIFACT_INTEGRITY_INVALID",
                "blocking_message": "目标所依赖的 MeasurementEvent 或 label 工件完整性校验失败",
                "required_action": str(exc.details.get("recovery_action") or "REVIEW_TARGET"),
                "scientific_reason": ";".join(str(reason) for reason in reasons),
            },
        }
    import pandas as pd

    events = pd.read_parquet(events_path)
    labels = pd.read_parquet(labels_path)
    try:
        joined = merge_event_labels(events, labels)
    except APIError as exc:
        reasons = exc.details.get("integrity_reasons") or ["MEASUREMENT_EVENT_LABEL_JOIN_INVALID"]
        return {
            "status": "BLOCKED",
            "committed": None,
            "blocking": {
                "blocking_code": "TARGET_EVENT_LABEL_JOIN_INVALID",
                "blocking_message": (
                    "MeasurementEvent 与标签 ID 必须一对一且有效；请重建事件和标签后复核。"
                ),
                "required_action": (
                    "REBUILD_MEASUREMENT_EVENTS_AND_LABELS_FROM_VERIFIED_INPUTS"
                ),
                "scientific_reason": ";".join(str(reason) for reason in reasons),
            },
        }
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


def _alignment_step(
    processed_root: Path,
    b: str,
    e: str,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    sync_manifest_path = processed_root / "synchronization" / b / e / "synchronization_manifest.json"
    manifest = _read_json(sync_manifest_path) or {}
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
    event_manifest_path = events_path.parent / "measurement_event_manifest.json"
    try:
        if raw_root is not None:
            from battery_workbench.api.integrity import assert_current_timebase_chain

            assert_current_timebase_chain(
                processed_root,
                raw_root,
                battery_id=b,
                experiment_id=e,
            )
        assert_processed_artifact_integrity(
            processed_root,
            sync_manifest_path,
            battery_id=b,
            experiment_id=e,
            required_outputs={"aligned", "candidates"},
            required_inputs={"ultrasound_timestamped", "electrical_records"},
        )
        assert_processed_artifact_integrity(
            processed_root,
            event_manifest_path,
            battery_id=b,
            experiment_id=e,
            required_outputs={"events", "candidates"},
            required_inputs={"aligned", "sync_candidates", "electrical_records"},
        )
    except APIError as exc:
        reasons = exc.details.get("integrity_reasons") or ["CANONICAL_ARTIFACT_INVALID"]
        recovery_action = str(exc.details.get("recovery_action") or "REVIEW_ALIGNMENT")
        blocking_message = (
            "时间锚点或 timestamp 来源/输出已过期；需要重建时间基准与下游同步链"
            if recovery_action == "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT"
            else "同步或 MeasurementEvent 工件完整性校验失败"
        )
        return {
            "status": "BLOCKED",
            "committed": None,
            "blocking": {
                "blocking_code": "ALIGNMENT_ARTIFACT_INTEGRITY_INVALID",
                "blocking_message": blocking_message,
                "required_action": recovery_action,
                "scientific_reason": ";".join(str(reason) for reason in reasons),
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


def _feature_analysis_latest(
    processed_root: Path, b: str, e: str
) -> tuple[dict[str, Any] | None, Path | None]:
    root = processed_root / "feature_analysis" / b / e
    if not root.is_dir():
        return None, None
    manifests = list(root.rglob("analysis_manifest.json"))
    latest = _latest_by_mtime(manifests)
    if latest is None:
        return None, None
    return _read_json(latest), latest


def _freshness_of_feature_analysis(
    processed_root: Path,
    manifest: Any,
    manifest_path: Path | None,
    battery_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    if manifest is None or manifest_path is None:
        return {"status": "MISSING", "reasons": []}
    if not isinstance(manifest, dict):
        return {"status": "INTEGRITY_BLOCKED", "reasons": ["ANALYSIS_MANIFEST_INVALID"]}
    try:
        resolved = manifest_path.resolve(strict=True)
        relative = resolved.relative_to(Path(processed_root).resolve())
    except (OSError, RuntimeError, ValueError):
        return {"status": "INTEGRITY_BLOCKED", "reasons": ["ANALYSIS_MANIFEST_OUTSIDE_ROOT"]}
    if (
        len(relative.parts) < 5
        or relative.parts[0] != "feature_analysis"
        or relative.parts[1] != battery_id
        or relative.parts[2] != experiment_id
        or relative.parent.name != manifest.get("analysis_id")
        or manifest.get("battery_id", battery_id) != battery_id
        or manifest.get("experiment_id", experiment_id) != experiment_id
    ):
        return {"status": "INTEGRITY_BLOCKED", "reasons": ["ANALYSIS_IDENTITY_MISMATCH"]}
    from battery_workbench.feature_analysis.output import (
        verify_analysis_input_checksums,
        verify_analysis_output_checksums,
    )

    output_status, output_reasons = verify_analysis_output_checksums(
        manifest_path.parent, manifest
    )
    input_status, input_reasons = verify_analysis_input_checksums(processed_root, manifest)
    reasons = output_reasons + input_reasons
    if "INTEGRITY_BLOCKED" in (output_status, input_status):
        status = "INTEGRITY_BLOCKED"
    elif input_status == "STALE_SOURCE":
        status = "STALE"
    elif "LEGACY_UNVERIFIED" in (output_status, input_status):
        status = "LEGACY"
    else:
        status = "CURRENT"
    return {"status": status, "reasons": list(dict.fromkeys(reasons))}


def _dataset_latest(
    processed_root: Path, b: str, e: str
) -> tuple[dict[str, Any] | None, Path | None]:
    """Latest MATERIALIZED dataset manifest over all families.

    SPEC_PENDING_RUN manifests are drafts (API spec placeholders pending a
    scientific run) — reported via dataset_drafts, never as committed state.
    """
    root = processed_root / "datasets" / b / e
    if not root.is_dir():
        return None, None
    manifests = [
        p
        for p in root.glob("*/DS::*/dataset_manifest.json")
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
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    """Latest MATERIALIZED split manifest for the committed dataset.

    Spec-pending split placeholders are drafts (§10) and never committed
    state; a split must belong to the committed dataset_id.
    """
    root = processed_root / "splits" / b / e
    if not root.is_dir() or dataset_id is None:
        return None, None, None
    manifests: list[tuple[Path, dict[str, Any]]] = []
    for m in root.rglob("split_manifest.json"):
        data = _read_json(m) or {}
        if data.get("dataset_id") != dataset_id:
            continue
        if data.get("split_id") != m.parent.name:
            continue
        if data.get("readiness_status") in _SPEC_PENDING_STATUSES:
            continue
        manifests.append((m, data))
    ids = [data.get("split_id") for _, data in manifests]
    duplicates = sorted(
        {split_id for split_id in ids if isinstance(split_id, str) and ids.count(split_id) > 1}
    )
    if duplicates:
        return None, None, "SPLIT_ID_AMBIGUOUS"
    latest = _latest_by_mtime([path for path, _ in manifests])
    if latest is None:
        return None, None, None
    return _read_json(latest), latest, None


def _split_output_integrity_reasons(
    processed_root: Path,
    manifest: dict[str, Any] | None,
    manifest_path: Path | None,
    battery_id: str,
    experiment_id: str,
    dataset_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
) -> list[str]:
    """Verify Split identity, confinement, and all generation-time outputs."""
    if manifest is None or manifest_path is None:
        return []
    reasons: list[str] = []
    root = Path(processed_root).resolve()
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
        relative = resolved_manifest.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["SPLIT_MANIFEST_PATH_INVALID"]
    if (
        len(relative.parts) != 6
        or relative.parts[0] != "splits"
        or relative.parts[1] != battery_id
        or relative.parts[2] != experiment_id
        or relative.parts[-1] != "split_manifest.json"
        or relative.parts[-2] != manifest.get("split_id")
        or relative.parts[-3] != manifest.get("dataset_id")
        or manifest.get("battery_id", battery_id) != battery_id
        or manifest.get("experiment_id", experiment_id) != experiment_id
    ):
        reasons.append("SPLIT_IDENTITY_MISMATCH")
    output_names = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    checksums = manifest.get("output_checksums")
    if not isinstance(checksums, dict) or set(checksums) != set(output_names):
        return list(dict.fromkeys(reasons + ["SPLIT_OUTPUT_CHECKSUMS_MISSING_OR_INVALID"]))
    split_dir = resolved_manifest.parent
    for key, filename in output_names.items():
        expected = checksums.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            reasons.append(f"SPLIT_OUTPUT_CHECKSUM_INVALID:{key}")
            continue
        try:
            output = (split_dir / filename).resolve(strict=True)
            output.relative_to(split_dir)
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"SPLIT_OUTPUT_MISSING_OR_PATH_INVALID:{key}")
            continue
        if not output.is_file():
            reasons.append(f"SPLIT_OUTPUT_MISSING_OR_PATH_INVALID:{key}")
            continue
        digest = hashlib.sha256()
        try:
            with output.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            reasons.append(f"SPLIT_OUTPUT_UNREADABLE:{key}")
            continue
        if digest.hexdigest().lower() != expected.lower():
            reasons.append(f"SPLIT_OUTPUT_CHECKSUM_MISMATCH:{key}")
    if dataset_path is not None or dataset_manifest_path is not None:
        if dataset_path is None or dataset_manifest_path is None:
            reasons.append("SPLIT_DATASET_SOURCE_PATH_MISSING")
        else:
            from battery_workbench.splits.integrity import split_dataset_source_reasons

            reasons.extend(
                split_dataset_source_reasons(
                    root,
                    manifest,
                    dataset_path=dataset_path,
                    dataset_manifest_path=dataset_manifest_path,
                )
            )
            from battery_workbench.splits.integrity import split_assignment_reasons

            reasons.extend(
                split_assignment_reasons(
                    root,
                    manifest,
                    assignments_path=resolved_manifest.parent / "split_assignments.parquet",
                    dataset_path=dataset_path,
                )
            )
    return list(dict.fromkeys(reasons))


def _models_for_experiment(processed_root: Path, b: str, e: str) -> list[dict[str, Any]]:
    """All model manifests for freshness comparison; no model artifacts are changed."""
    root = processed_root / "models" / b / e
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for m in root.rglob("model_manifest.json"):
        out.append(_read_json(m) or {})
    return out


def _models_for_split(
    processed_root: Path, b: str, e: str, dataset_id: str | None, split_id: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Model manifests bound to the exact committed dataset and split."""
    if dataset_id is None or split_id is None:
        return [], []
    root = processed_root / "models" / b / e
    if not root.is_dir():
        return [], []
    out: list[dict[str, Any]] = []
    reasons: list[str] = []
    for manifest_path in root.rglob("model_manifest.json"):
        try:
            relative = manifest_path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) < 2 or relative.parts[:2] != (dataset_id, split_id):
            continue
        model = _read_json(manifest_path)
        if not isinstance(model, dict):
            reasons.append("MODEL_MANIFEST_UNREADABLE")
            continue
        reasons.extend(
            _model_output_integrity_reasons(
                processed_root,
                manifest_path,
                model,
                battery_id=b,
                experiment_id=e,
                dataset_id=dataset_id,
                split_id=split_id,
            )
        )
        out.append(model)
    model_ids = [model.get("model_id") for model in out]
    duplicate_ids = {
        model_id
        for model_id in model_ids
        if isinstance(model_id, str) and model_ids.count(model_id) > 1
    }
    if duplicate_ids:
        reasons.append("MODEL_ID_AMBIGUOUS")
    if reasons:
        return [], list(dict.fromkeys(reasons))
    return out, []


def _model_output_integrity_reasons(
    processed_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    battery_id: str,
    experiment_id: str,
    dataset_id: str,
    split_id: str,
) -> list[str]:
    """Verify model identity, confinement, and estimator/prediction checksums."""
    root = Path(processed_root).resolve()
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
        relative = resolved_manifest.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["MODEL_MANIFEST_PATH_INVALID"]
    model_id = manifest.get("model_id")
    if (
        len(relative.parts) != 7
        or relative.parts[0] != "models"
        or relative.parts[1] != battery_id
        or relative.parts[2] != experiment_id
        or relative.parts[3] != dataset_id
        or relative.parts[4] != split_id
        or relative.parts[5] != model_id
        or relative.parts[6] != "model_manifest.json"
        or manifest.get("dataset_id") != dataset_id
        or manifest.get("split_id") != split_id
    ):
        return ["MODEL_IDENTITY_MISMATCH"]
    checksums = manifest.get("output_checksums")
    if not isinstance(checksums, dict):
        return ["MODEL_OUTPUT_CHECKSUMS_MISSING"]
    output_names = {
        "model": "model.joblib",
        "held_out_predictions": "held_out_predictions.parquet",
    }
    reasons: list[str] = []
    model_dir = resolved_manifest.parent
    for key, filename in output_names.items():
        expected = checksums.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            reasons.append(f"MODEL_OUTPUT_CHECKSUM_INVALID:{key}")
            continue
        try:
            output = (model_dir / filename).resolve(strict=True)
            output.relative_to(model_dir)
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"MODEL_OUTPUT_MISSING_OR_PATH_INVALID:{key}")
            continue
        if not output.is_file():
            reasons.append(f"MODEL_OUTPUT_MISSING_OR_PATH_INVALID:{key}")
            continue
        digest = hashlib.sha256()
        try:
            with output.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            reasons.append(f"MODEL_OUTPUT_UNREADABLE:{key}")
            continue
        if digest.hexdigest().lower() != expected.lower():
            reasons.append(f"MODEL_OUTPUT_CHECKSUM_MISMATCH:{key}")
    return list(dict.fromkeys(reasons))


def _report_dataset_id(report: dict[str, Any] | None) -> str | None:
    if report is None:
        return None
    canonical = (report.get("experiment_record") or {}).get("latest_canonical_artifacts") or {}
    value = canonical.get("dataset_id")
    return value if isinstance(value, str) and value else None


def _report_split_id(report: dict[str, Any] | None) -> str | None:
    if report is None:
        return None
    canonical = (report.get("experiment_record") or {}).get("latest_canonical_artifacts") or {}
    value = canonical.get("split_id")
    return value if isinstance(value, str) and value else None


def _report_latest(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    root = processed_root / "artifacts" / b / e / "reports"
    if not root.is_dir():
        return None
    latest = _latest_by_mtime(list(root.rglob("scientific_report.json")))
    if latest is None:
        return None
    data = _read_json(latest)
    if not isinstance(data, dict):
        data = {"report_id": latest.parent.name}
    data["_path"] = str(latest)
    return data


def _freshness_of_report(
    report: dict[str, Any] | None,
    battery_id: str,
    experiment_id: str,
    processed_root: Path,
) -> dict[str, Any]:
    if report is None:
        return {"status": "MISSING", "reasons": []}
    raw_path = report.get("_path")
    if not isinstance(raw_path, str) or not raw_path:
        return {"status": "INTEGRITY_BLOCKED", "reasons": ["REPORT_PATH_MISSING"]}
    from battery_workbench.reporting.report import verify_report_outputs

    status, reasons = verify_report_outputs(
        Path(raw_path),
        battery_id=battery_id,
        experiment_id=experiment_id,
        reports_root=(
            processed_root / "artifacts" / battery_id / experiment_id / "reports"
        ),
    )
    return {"status": status, "reasons": reasons}


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
        "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE": "重新解析并复核来源链",
    }
    return [
        {"action_id": aid, "label": zh.get(aid, aid), "route": _route(b, e, page)}
        for aid, page, _ in entries
    ]


def _freshness_of_dataset(
    processed_root: Path,
    dm: dict[str, Any] | None,
    manifest_path: Path | None,
    *,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    """Assess byte-level sources plus the canonical TOF definition generation."""
    if dm is None:
        return {"status": "MISSING", "reasons": []}
    from battery_workbench.datasets.freshness import dataset_freshness

    integrity = (
        dataset_freshness(processed_root, manifest_path, dm, raw_root=raw_root)
        if manifest_path is not None
        else {"freshness_status": "STALE_SOURCE", "freshness_reasons": ["DATASET_MANIFEST_MISSING"]}
    )
    selected_features = set(dm.get("selected_features") or [])
    if not selected_features:
        selected_features = set(dm.get("predictor_columns") or [])
    if (
        integrity["freshness_reasons"] == ["CANONICAL_TOF_PROVENANCE_MISSING"]
        and "tof_us" in selected_features
        and not dm.get("tof_method_id")
    ):
        return {"status": "LEGACY", "reasons": ["CANONICAL_TOF_PROVENANCE_MISSING"]}
    if integrity["freshness_status"] != "FRESH":
        return {"status": "STALE", "reasons": integrity["freshness_reasons"]}
    if "tof_us" in selected_features and not dm.get("tof_method_id"):
        return {"status": "LEGACY", "reasons": ["CANONICAL_TOF_PROVENANCE_MISSING"]}
    return {"status": "CURRENT", "reasons": []}


def build_workflow_context(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    *,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    """Assemble the ScientificWorkflowContext (pure read; no artifact writes)."""
    b, e = battery_id, experiment_id
    validate_id(b, "battery_id")
    validate_id(e, "experiment_id")
    _require_experiment(processed_root, b, e)

    from battery_workbench.reporting.collector import invalid_parser_manifest_modalities

    invalid_modalities = invalid_parser_manifest_modalities(processed_root, b, e)
    if raw_root is not None:
        from battery_workbench.provenance.parser_manifest import (
            parser_manifest_raw_source_mismatches,
        )

        invalid_modalities = sorted(
            set(invalid_modalities)
            | set(parser_manifest_raw_source_mismatches(processed_root, raw_root, b, e))
        )
    if invalid_modalities:
        action_id = "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        message = (
            "Parser 来源清单无效，旧 Dataset、模型和报告不能作为当前研究链状态；"
            "请先重新解析相关来源并复核 lineage。"
        )
        blocking = _block(
            "SOURCE_PROVENANCE_INVALID",
            message,
            action_id,
            f"以下模态的 parser provenance 无效：{', '.join(invalid_modalities)}",
        )
        steps = {
            step: {"status": "BLOCKED", "committed": None, "blocking": blocking}
            for step in _STEPS
        }
        route = _route(b, e, "runs")
        return {
            "schema_version": _SCHEMA_VERSION,
            "battery_id": b,
            "experiment_id": e,
            "current_step": "TARGET",
            "step_statuses": {step: "BLOCKED" for step in _STEPS},
            "steps": steps,
            "recommended_next_action": {
                "action_id": action_id,
                "step": "TARGET",
                "label": "重新解析并复核来源链",
                "route": route,
            },
            "pending_action": None,
            "artifact_freshness": {
                "feature_analysis": "INTEGRITY_BLOCKED",
                "dataset": "INTEGRITY_BLOCKED",
                "split": "INTEGRITY_BLOCKED",
                "models": "INTEGRITY_BLOCKED",
                "report": "INTEGRITY_BLOCKED",
            },
            "scientific_context": {
                "experiment_id": e,
                "battery_id": b,
                "target_id": None,
                "target_status": "BLOCKED",
                "alignment_status": "BLOCKED",
                "eligible_count": None,
                "excluded_count": None,
                "selected_feature_locators": [],
                "feature_selection_source": None,
                "feature_selection_status": "INTEGRITY_BLOCKED",
                "dataset_id": None,
                "dataset_status": "INTEGRITY_BLOCKED",
                "split_id": None,
                "split_status": "INTEGRITY_BLOCKED",
                "model_status": "INTEGRITY_BLOCKED",
                "report_id": None,
                "report_status": "INTEGRITY_BLOCKED",
                "pending_action": None,
                "blocking_reason": {"step": "TARGET", **blocking},
                "recommended_next_action": {
                    "action_id": action_id,
                    "step": "TARGET",
                    "label": "重新解析并复核来源链",
                    "route": route,
                },
                "artifact_freshness": {
                    "feature_analysis": "INTEGRITY_BLOCKED",
                    "dataset": "INTEGRITY_BLOCKED",
                    "split": "INTEGRITY_BLOCKED",
                    "models": "INTEGRITY_BLOCKED",
                    "report": "INTEGRITY_BLOCKED",
                },
                "limitations": ["SOURCE_PROVENANCE_INVALID"],
                "source_integrity_status": "INTEGRITY_BLOCKED",
                "invalid_modalities": invalid_modalities,
            },
            "assistant_context": None,
            "typed_actions": [
                {
                    "action_id": action_id,
                    "label": "重新解析并复核来源链",
                    "route": route,
                }
            ],
            "meta": {
                "read_only": True,
                "no_recomputation": True,
                "source_integrity_status": "INTEGRITY_BLOCKED",
                "invalid_modalities": invalid_modalities,
                "notes": "来源完整性失效；隐藏已物化科学链状态，不重新计算任何工件",
            },
        }

    fs_state = _fs_state(processed_root, b, e)
    pending = _pending_submissions(processed_root, b, e)

    target = _target_step(processed_root, b, e)
    alignment = _alignment_step(processed_root, b, e, raw_root)
    fa, fa_path = _feature_analysis_latest(processed_root, b, e)
    fa_assessment = _freshness_of_feature_analysis(processed_root, fa, fa_path, b, e)
    fa_freshness = fa_assessment["status"]
    dm, ds_path = _dataset_latest(processed_root, b, e)
    dataset_assessment = _freshness_of_dataset(
        processed_root, dm, ds_path, raw_root=raw_root
    )
    dataset_freshness = dataset_assessment["status"]
    dataset_id = (dm or {}).get("dataset_id")
    split, split_path, split_lookup_error = _split_latest(
        processed_root, b, e, dataset_id
    )
    split_integrity_reasons = (
        [split_lookup_error]
        if split_lookup_error
        else _split_output_integrity_reasons(
            processed_root,
            split,
            split_path,
            b,
            e,
            dataset_path=(ds_path.parent / "dataset.parquet") if ds_path else None,
            dataset_manifest_path=ds_path,
        )
    )
    split_dataset_changed = any(
        reason.startswith("SPLIT_SOURCE_DATASET_CHANGED:")
        for reason in split_integrity_reasons
    )
    split_freshness = (
        "STALE"
        if dataset_freshness in {"STALE", "LEGACY"} or split_dataset_changed
        else "INTEGRITY_BLOCKED"
        if split_integrity_reasons
        else "CURRENT"
        if split
        else "MISSING"
    )
    split_id = (split or {}).get("split_id") if split_freshness == "CURRENT" else None
    split_ready = bool(
        dataset_freshness == "CURRENT"
        and split is not None
        and split_freshness == "CURRENT"
        and split_id
        and split.get("readiness_status") == "READY_FOR_LIMITED_EVALUATION"
    )
    if split_ready:
        models, model_integrity_reasons = _models_for_split(
            processed_root, b, e, dataset_id, split_id
        )
    else:
        models, model_integrity_reasons = [], []
    report = _report_latest(processed_root, b, e)
    report_output_assessment = _freshness_of_report(report, b, e, processed_root)
    assistant = _assistant_state(processed_root, b, e)

    all_models = _models_for_experiment(processed_root, b, e)
    # §23 stale chain: upstream dataset changes invalidate downstream models.
    # Historic metrics are not "missing" when they exist; they are stale relative
    # to the newly committed dataset and must not satisfy the current workflow.
    if split_freshness == "INTEGRITY_BLOCKED" or model_integrity_reasons:
        model_freshness = "INTEGRITY_BLOCKED"
    elif not split_ready or not models:
        model_freshness = "STALE" if all_models and dataset_id else "MISSING"
    else:
        model_freshness = "CURRENT"
    if report is None:
        report_freshness = "MISSING"
    elif report_output_assessment["status"] == "INTEGRITY_BLOCKED" or (
        model_freshness == "INTEGRITY_BLOCKED"
        and split_freshness != "INTEGRITY_BLOCKED"
    ):
        report_freshness = "INTEGRITY_BLOCKED"
    elif model_freshness in {"STALE", "LEGACY", "MISSING"} or (
        _report_dataset_id(report) is not None and _report_dataset_id(report) != dataset_id
    ) or (
        _report_split_id(report) is not None and _report_split_id(report) != split_id
    ):
        report_freshness = "STALE"
    elif (
        _report_dataset_id(report) is None
        or _report_split_id(report) is None
        or report_output_assessment["status"] == "LEGACY"
    ):
        report_freshness = "LEGACY"
    else:
        report_freshness = "CURRENT"

    # ---------- per-step statuses ----------
    steps: dict[str, dict[str, Any]] = {}

    steps["TARGET"] = target
    steps["ALIGNMENT"] = alignment

    dataset_selected = list((dm or {}).get("selected_features") or [])
    if fa is None and dataset_selected:
        steps["FEATURES"] = {
            "status": "COMPLETE",
            "committed": {
                "analysis_id": None,
                "analysis_mode": "DATASET_SPEC_COMMITTED",
                "target": (dm or {}).get("target_name"),
                "selected_features": dataset_selected,
                "selection_basis": "MATERIALIZED_DATASET_SPEC",
            },
        }
    elif fa is None:
        steps["FEATURES"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "FEATURE_ANALYSIS_MISSING",
                "特征分析未物化",
                "CONFIGURE_FEATURES",
                "特征-目标研究需要先物化一份特征分析（含选择集）",
            ),
        }
    else:
        selection = fa.get("selection") or {}
        selected = (
            selection.get("selected_features") or []
            if fa_freshness == "CURRENT"
            else []
        )
        if fa_freshness == "INTEGRITY_BLOCKED":
            feature_status = "BLOCKED"
        elif fa_freshness in {"STALE", "LEGACY"}:
            feature_status = "STALE"
        else:
            feature_status = "COMPLETE" if selected else "LIMITED"
        steps["FEATURES"] = {
            "status": feature_status,
            "committed": (
                {
                    "analysis_id": fa.get("analysis_id"),
                    "analysis_mode": fa.get("analysis_mode"),
                    "target": fa.get("target"),
                    "selected_features": selected,
                    "selection_basis": selection.get("selection_basis")
                    if fa_freshness == "CURRENT"
                    else None,
                    "freshness_status": fa_freshness,
                    "freshness_reasons": fa_assessment["reasons"],
                }
                if fa_freshness != "INTEGRITY_BLOCKED"
                else None
            ),
        }
        if fa_freshness in {"STALE", "LEGACY", "INTEGRITY_BLOCKED"}:
            steps["FEATURES"]["blocking"] = _block(
                "FEATURE_ANALYSIS_" + fa_freshness,
                "特征分析产物已过期、属于未验证旧格式或完整性校验失败",
                "CONFIGURE_FEATURES",
                "重新运行特征分析以校验当前输入和选择结果；未核验的历史选择不能作为当前工作流输入",
            )

    features_selected = bool((steps["FEATURES"].get("committed") or {}).get("selected_features"))
    if not features_selected:
        steps["PREVIEW"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "FEATURE_SELECTION_MISSING",
                "未选择特征",
                "CONFIGURE_FEATURES",
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
                "DATASET_MISSING",
                "未物化数据集",
                "BUILD_DATASET",
                "分组划分与建模要求已物化数据集",
            ),
        }
    else:
        status = "COMPLETE"
        if dataset_freshness in {"STALE", "LEGACY"}:
            status = "STALE"
        elif dm.get("dataset_status") == "NOT_READY_FOR_MODEL_EVALUATION":
            status = "LIMITED"
        steps["DATASET"] = {
            "status": status,
            "committed": {
                "dataset_id": dataset_id,
                "dataset_status": "STALE_SOURCE"
                if dataset_freshness == "STALE"
                else dm.get("dataset_status"),
                "declared_dataset_status": dm.get("dataset_status"),
                "freshness_status": dataset_freshness,
                "freshness_reasons": dataset_assessment["reasons"],
                "target_name": dm.get("target_name"),
                "selected_features": dm.get("selected_features"),
                "eligible_rows": dm.get("eligible_rows"),
                "feature_set_id": dm.get("feature_set_id"),
                "analysis_slice_id": dm.get("analysis_slice_id"),
            },
        }
        if dataset_freshness in {"STALE", "LEGACY"}:
            steps["DATASET"]["blocking"] = _block(
                "DATASET_STALE_SOURCE",
                "已物化数据集的来源已变化或无法验证",
                "BUILD_DATASET",
                "必须用当前 feature/label 来源重新构建数据集，旧拆分、模型和报告不能作为当前证据",
            )

    if dataset_id is None:
        steps["SPLIT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "DATASET_MISSING",
                "数据集未物化",
                "BUILD_DATASET",
                "分组划分必须建立在已物化数据集上",
            ),
        }
    elif dataset_freshness in {"STALE", "LEGACY"}:
        steps["SPLIT"] = {
            "status": "STALE",
            "committed": {
                "split_id": split_id,
                "dataset_id": dataset_id,
                "readiness_status": split.get("readiness_status") if split else None,
            },
            "blocking": _block(
                "DATASET_STALE_SOURCE",
                "数据集来源过期，关联划分不能继续使用",
                "BUILD_DATASET",
                "先重建 Dataset，再为新 Dataset 建立 grouped split",
            ),
        }
    elif split_freshness == "INTEGRITY_BLOCKED":
        steps["SPLIT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "SPLIT_ARTIFACT_INTEGRITY_INVALID",
                "分组划分的来源清单或输出 checksum 校验失败",
                "CREATE_SPLIT",
                ";".join(split_integrity_reasons),
            ),
        }
    elif split_freshness == "STALE":
        steps["SPLIT"] = {
            "status": "STALE",
            "committed": None,
            "blocking": _block(
                "SPLIT_DATASET_SOURCE_CHANGED",
                "Dataset 内容版本已变化，原分组划分不能继续使用",
                "CREATE_SPLIT",
                ";".join(split_integrity_reasons),
            ),
        }
    elif split is None:
        steps["SPLIT"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "SPLIT_MISSING",
                "未建立分组划分",
                "CREATE_SPLIT",
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

    if not split_ready:
        stale_dataset = dataset_freshness in {"STALE", "LEGACY"}
        stale_split_source = split_freshness == "STALE"
        split_blocked = split_freshness == "INTEGRITY_BLOCKED"
        steps["MODELS"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "DATASET_STALE_SOURCE"
                if stale_dataset
                else "SPLIT_DATASET_SOURCE_CHANGED"
                if stale_split_source
                else "SPLIT_ARTIFACT_INTEGRITY_INVALID"
                if split_blocked
                else "VALID_SPLIT_REQUIRED",
                "数据集来源过期"
                if stale_dataset
                else "Dataset 内容版本已变化"
                if stale_split_source
                else "分组划分完整性校验失败"
                if split_blocked
                else ("无合法 grouped split" if split is None else "split 就绪状态不足"),
                "BUILD_DATASET" if stale_dataset else "CREATE_SPLIT",
                "先用当前来源重建 Dataset；旧模型和 split 不可作为当前证据"
                if stale_dataset
                else ";".join(split_integrity_reasons)
                if split_blocked
                else "ML-safe 建模必须建立在合法分组划分（按 cycle 分组）上",
            ),
        }
    elif model_freshness == "INTEGRITY_BLOCKED":
        steps["MODELS"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "MODEL_ARTIFACT_INTEGRITY_INVALID",
                "模型或 held-out prediction 输出完整性校验失败",
                "TRAIN_MODELS",
                ";".join(model_integrity_reasons),
            ),
        }
    elif not models:
        steps["MODELS"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "MODELS_MISSING",
                "未训练基线模型",
                "TRAIN_MODELS",
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

    if report_output_assessment["status"] == "INTEGRITY_BLOCKED":
        steps["REPORT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "REPORT_OUTPUT_INTEGRITY_INVALID",
                "报告文件缺失、身份不匹配或 checksum 校验失败",
                "OPEN_REPORT",
                "不要使用损坏的冻结报告；修复来源后重新生成报告",
            ),
        }
    elif (
        model_freshness == "INTEGRITY_BLOCKED"
        and split_freshness != "INTEGRITY_BLOCKED"
    ):
        steps["REPORT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "MODEL_ARTIFACT_INTEGRITY_INVALID",
                "关联模型结果不完整，不能作为报告证据",
                "TRAIN_MODELS",
                ";".join(model_integrity_reasons),
            ),
        }
    elif not split_ready:
        stale_dataset = dataset_freshness in {"STALE", "LEGACY"}
        stale_split_source = split_freshness == "STALE"
        split_blocked = split_freshness == "INTEGRITY_BLOCKED"
        steps["REPORT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "DATASET_STALE_SOURCE"
                if stale_dataset
                else "SPLIT_DATASET_SOURCE_CHANGED"
                if stale_split_source
                else "SPLIT_ARTIFACT_INTEGRITY_INVALID"
                if split_blocked
                else "VALID_SPLIT_REQUIRED",
                "数据集来源过期"
                if stale_dataset
                else "Dataset 内容版本已变化"
                if stale_split_source
                else "分组划分完整性校验失败"
                if split_blocked
                else "当前数据集尚无可用 grouped split",
                "BUILD_DATASET" if stale_dataset else "CREATE_SPLIT",
                "先用当前来源重建 Dataset，之后再生成有效的 split 和报告"
                if stale_dataset
                else ";".join(split_integrity_reasons)
                if split_blocked
                else "报告中的模型证据必须来自当前已提交数据集的合法 grouped split",
            ),
        }
    elif not models:
        steps["REPORT"] = {
            "status": "BLOCKED",
            "committed": None,
            "blocking": _block(
                "MODELS_MISSING",
                "无模型结果",
                "TRAIN_MODELS",
                "报告需要至少一组基线模型对比结果",
            ),
        }
    elif report is None:
        steps["REPORT"] = {
            "status": "NOT_STARTED",
            "committed": None,
            "blocking": _block(
                "REPORT_MISSING",
                "未生成报告",
                "OPEN_REPORT",
                "所有前置已满足，可生成研究报告",
            ),
        }
    elif report_freshness in {"STALE", "LEGACY", "SUPERSEDED"}:
        steps["REPORT"] = {
            "status": "STALE",
            "committed": {"report_id": report.get("report_id")},
            "blocking": _block(
                "REPORT_STALE",
                "现有报告基于旧数据集或旧模型结果",
                "OPEN_REPORT",
                "重新生成报告以绑定当前数据集和模型证据",
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
    features_committed = steps["FEATURES"].get("committed") or {}
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
        "feature_selection_source": (
            "FEATURE_ANALYSIS" if fa else "MATERIALIZED_DATASET_SPEC" if dataset_selected else None
        ),
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
            "feature_analysis": fa_freshness,
            "dataset": dataset_freshness,
            "split": split_freshness,
            "models": model_freshness,
            "report": report_freshness,
            "report_output": report_output_assessment["status"],
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
            "feature_analysis": fa_freshness,
            "dataset": dataset_freshness,
            "split": split_freshness,
            "models": model_freshness,
            "report": report_freshness,
            "report_output": report_output_assessment["status"],
        },
        "scientific_context": scientific_context,
        "assistant_context": assistant_context,
        "typed_actions": _typed_actions(
            b,
            e,
            [
                ("REVIEW_TARGET", "analysis", ""),
                ("REVIEW_ALIGNMENT", "analysis", ""),
                ("CONFIGURE_FEATURES", "analysis", ""),
                ("OPEN_PREVIEW", "analysis", ""),
                ("BUILD_DATASET", "analysis", ""),
                ("CREATE_SPLIT", "dataset-split", ""),
                ("TRAIN_MODELS", "models", ""),
                ("OPEN_REPORT", "report", ""),
            ],
        ),
        "meta": {
            "read_only": True,
            "no_recomputation": True,
            "notes": "只聚合已物化产物；不重算 TOF/CE/相关性/模型指标/split",
        },
    }


def _block(code: str, message: str, action: str, reason: str) -> dict[str, str]:
    return {
        "blocking_code": code,
        "blocking_message": message,
        "required_action": action,
        "scientific_reason": reason,
    }

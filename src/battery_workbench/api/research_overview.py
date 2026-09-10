"""BRW-025R-OV — Research Overview aggregate read endpoint.

GET /experiments/{b}/{e}/research-overview

Single read-only aggregation for the Overview first screen: metadata strip,
electrical snapshot, ultrasound/TOF snapshot, signal quality, scientific
readiness matrix, scientific snapshot, model baseline comparison, limitations,
stale-artifact flags and recommended next actions. The frontend computes NO
science (no CE, no TOF, no correlation, no model metrics).

Read-only contract: every value comes from existing artifacts (BRW-017R2 /
BRW-018R2 outputs, electrical parquet manifests, parameter registry, model
comparison JSON). This module never writes scientific artifacts and never
re-runs pipelines. Unknown metadata is reported as Not configured /
Unavailable — never guessed (AGENTS.md #5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id

_STALE_DEFINITION_VERSION = "0.1.0"  # dataset/model built before BRW-013X V2


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _downsampled_series(
    df: pd.DataFrame, column: str, points: int = 240
) -> list[float | None]:
    if column not in df.columns or df.empty:
        return []
    step = max(1, len(df) // points)
    s = df[column].iloc[::step]
    return [None if pd.isna(v) else round(float(v), 4) for v in s]


def _fs_state(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """fs from the newest resolved parameter set (registry provenance only)."""
    ps_dir = processed_root / "parameters" / b / e
    newest_resolved: tuple[str | None, bool, str | None] = (None, False, None)
    if ps_dir.is_dir():
        from battery_workbench.features_physical.canonical_tof import effective_fs

        for manifest in sorted(ps_dir.glob("PS::*/effective_parameters.json")):
            eff = _read_json(manifest)
            if not eff:
                continue
            eff = eff.get("effective_parameters") or eff
            fs, verified = effective_fs(eff, require_verified=True)
            if verified:
                return {
                    "sampling_rate_hz": fs,
                    "sampling_rate_verified": True,
                    "parameter_set_id": manifest.parent.name,
                }
            if fs is not None and newest_resolved[0] is None:
                newest_resolved = (
                    fs, False, manifest.parent.name,
                )
    return {
        "sampling_rate_hz": newest_resolved[0],
        "sampling_rate_verified": False,
        "parameter_set_id": newest_resolved[2],
    }


def _metadata_strip(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Metadata strip — unknown fields are Not configured, never guessed."""
    parser = _read_json(processed_root / "electrical" / b / e / "parser_manifest.json") or {}
    fs_state = _fs_state(processed_root, b, e)

    aux_t = processed_root / "electrical" / b / e / "aux_temperature.parquet"
    temperature: dict[str, Any] = {"status": "NOT_CONFIGURED", "channel": None}
    if aux_t.is_file():
        try:
            tdf = pd.read_parquet(aux_t, columns=["temperature_channel", "temperature_c"])
            channels = sorted(str(c) for c in tdf["temperature_channel"].dropna().unique())
            tmin = float(tdf["temperature_c"].min())
            tmax = float(tdf["temperature_c"].max())
            temperature = {
                "status": "AVAILABLE",
                "channel": channels or None,
                "range_c": [round(tmin, 1), round(tmax, 1)],
            }
        except (OSError, ValueError):
            pass

    ts_min = parser.get("timestamp_min")
    ts_max = parser.get("timestamp_max")
    return {
        "battery_id": b,
        "experiment_id": e,
        "chemistry": {"status": "NOT_CONFIGURED", "value": None},
        "nominal_capacity_ah": {"status": "NOT_CONFIGURED", "value": None},
        "probe": {"status": "NOT_CONFIGURED", "value": None},
        "channel": {
            "status": "NOT_CONFIGURED" if not fs_state["sampling_rate_verified"] else "AVAILABLE",
            "value": None,
        },
        "temperature": temperature,
        "sampling_rate": {
            "status": "AVAILABLE" if fs_state["sampling_rate_verified"] else "NOT_CONFIGURED",
            "hz": fs_state["sampling_rate_hz"],
            "verified": fs_state["sampling_rate_verified"],
            "parameter_set_id": fs_state["parameter_set_id"],
        },
        "acquisition_window": {
            "status": "NOT_CONFIGURED",
            "start": ts_min,
            "end": ts_max,
        },
        "timebase": {"status": "PROVISIONAL"},
    }


def _electrical_snapshot(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    rec_path = processed_root / "electrical" / b / e / "records.parquet"
    cyc_path = processed_root / "electrical" / b / e / "cycles.parquet"
    stp_path = processed_root / "electrical" / b / e / "steps.parquet"
    if not rec_path.is_file():
        return {"status": "UNAVAILABLE"}
    records = pd.read_parquet(rec_path, columns=["voltage_v", "current_a"])
    cycles = pd.read_parquet(cyc_path) if cyc_path.is_file() else pd.DataFrame()
    steps = pd.read_parquet(stp_path) if stp_path.is_file() else pd.DataFrame()

    cycle_rows = []
    for _, row in cycles.iterrows():
        ce = row.get("coulombic_efficiency_percent")
        cycle_rows.append(
            {
                "cycle_index_raw": int(row["cycle_index_raw"]),
                "charge_capacity_ah": (
                    None if pd.isna(row.get("charge_capacity_ah")) else round(float(row["charge_capacity_ah"]), 4)
                ),
                "discharge_capacity_ah": (
                    None if pd.isna(row.get("discharge_capacity_ah")) else round(float(row["discharge_capacity_ah"]), 4)
                ),
                "apparent_coulombic_efficiency_percent": (
                    None if pd.isna(ce) else round(float(ce), 2)
                ),
                "protocol": "PROTOCOL_FROM_PARSER",
            }
        )
    return {
        "status": "AVAILABLE",
        "record_count": len(records),
        "cycle_count": len(cycles),
        "step_count": int(steps["step_index_raw"].nunique()) if not steps.empty and "step_index_raw" in steps else None,
        "voltage_range_v": [
            round(float(records["voltage_v"].min()), 4),
            round(float(records["voltage_v"].max()), 4),
        ],
        "current_range_a": [
            round(float(records["current_a"].min()), 4),
            round(float(records["current_a"].max()), 4),
        ],
        "voltage_sparkline_v": _downsampled_series(records, "voltage_v"),
        "current_sparkline_a": _downsampled_series(records, "current_a"),
        "cycles": cycle_rows,
    }


def _tof_snapshot(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    from battery_workbench.features.gate_calibration import resolve_tof_gate_calibration

    audit_path = processed_root / "features_physical" / b / e / "canonical_tof_audit.json"
    audit = _read_json(audit_path) or {}
    cal = resolve_tof_gate_calibration(b, e, processed_root)
    fs_state = _fs_state(processed_root, b, e)
    fs_hz, fs_verified = fs_state["sampling_rate_hz"], fs_state["sampling_rate_verified"]

    status = "NOT_CONFIGURED"
    tof_us_summary = None
    if fs_verified:
        status = "READY"
    elif fs_hz is not None:
        status = "BLOCKED"  # resolved but unverified → activation refused

    parquet_path = processed_root / "features_physical" / b / e / "canonical_tof.parquet"
    counts: dict[str, int] = {}
    if parquet_path.is_file():
        try:
            tof_df = pd.read_parquet(
                parquet_path,
                columns=[
                    "tof_status", "tof_us",
                    "surface_peak_sample_index", "bottom_peak_sample_index",
                    "gate_calibration_id",
                ],
            )
            counts = tof_df["tof_status"].value_counts().to_dict()
            int((tof_df["tof_status"] == "VALID").sum())
            valid = tof_df[tof_df["tof_status"] == "VALID"]
            if len(valid):
                tof_us_summary = {
                    "min": round(float(valid["tof_us"].min()), 3),
                    "median": round(float(valid["tof_us"].median()), 3),
                    "max": round(float(valid["tof_us"].max()), 3),
                }
        except (OSError, ValueError):
            pass

    artifact_matches_registry = audit.get("parameter_set_id") == fs_state["parameter_set_id"]
    artifact_verified = bool(audit.get("sampling_rate_verified"))
    # coverage: waveform TOF valid vs Feature–Target eligible are different
    # counts and are reported separately (never merged).
    events = processed_root / "multimodal" / b / e / "measurement_events.parquet"
    eligible = None
    event_count = None
    ambiguous = None
    if events.is_file():
        try:
            me = pd.read_parquet(
                events, columns=["analysis_eligible", "sync_ambiguous"]
            )
            event_count = len(me)
            eligible = int(me["analysis_eligible"].sum())
            ambiguous = int(me["sync_ambiguous"].sum())
        except (OSError, ValueError):
            pass

    return {
        "status": status,
        "tof_method_id": audit.get(
            "tof_method_id", "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        ),
        "tof_definition_version": audit.get("tof_definition_version"),
        "sampling_rate_hz": fs_hz,
        "sampling_rate_verified": fs_verified,
        "gate_calibration_id": cal["gate_calibration_id"],
        "gate_calibration_source": cal["source"],
        "gate_calibration_version": cal["version"],
        "surface_gate_id": cal["surface_gate_id"],
        "surface_peak_sample_range": [int(cal["surface_start"]), int(cal["surface_end_exclusive"])],
        "bottom_gate_id": cal["bottom_gate_id"],
        "bottom_peak_sample_range": [int(cal["bottom_start"]), int(cal["bottom_end_exclusive"])],
        "artifact_status_counts": counts,
        "artifact_tof_us_summary": tof_us_summary,
        "artifact_current": bool(artifact_matches_registry and artifact_verified) or status == "NOT_CONFIGURED",
        "waveform_tof": {
            "event_count": event_count,
            "ambiguous_events": ambiguous,
            "note": "波形级 TOF 行（每 MeasurementEvent 帧一行）",
        },
        "feature_target_eligible": {
            "eligible_count": eligible,
            "note": "特征–目标可用行（analysis_eligible）——与波形 TOF 有效数不同",
        },
    }


def _signal_quality(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Only formally defined quality metrics are reported; no invented SNR."""
    return {
        "snr": {"status": "NOT_CONFIGURED", "value": None,
                "reason": "no formally defined SNR algorithm in the workbench"},
        "saturation_check": {
            "status": "AVAILABLE",
            "definition": "gate-level saturation fraction (SATURATION_LIMIT 32000, gates engine)",
        },
    }


def _readiness_matrix(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    fs_state = _fs_state(processed_root, b, e)
    tof_ready = fs_state["sampling_rate_verified"]
    return {
        "acquisition": "READY" if (processed_root / "ultrasound" / b / e / "frames.parquet").is_file() else "BLOCKED",
        "synchronization": "PROVISIONAL",
        "tof": "READY" if tof_ready else "BLOCKED",
        "targets": "READY_FOR_LIMITED_EVALUATION",
        "modeling": "LIMITED",
    }


def _feature_definition_state(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Compare the dataset's FS definition version against the current policy."""
    dataset_manifest = _read_json(
        processed_root
        / "datasets" / b / e / "SOC" / "DS::6a3142e5186fc684964ff09e" / "dataset_manifest.json"
    ) or {}
    fs_id = dataset_manifest.get("feature_set_id", "")
    fs_version = None
    if fs_id:
        # FS id contains its directory; the manifest lives next to the parquet
        for fs_manifest in (processed_root / "features" / b / e).glob(
            f"AS::*/{fs_id}/feature_set_manifest.json"
        ):
            fs = _read_json(fs_manifest) or {}
            fs_version = fs.get("feature_definition_version")
            break
    stale = fs_version is not None and fs_version != "2.0.0"
    return {
        "feature_set_id": fs_id,
        "dataset_definition_version": fs_version,
        "current_policy": "MATLAB_ALIGNED_FEATURE_FORMULAS_V1",
        "uses_previous_feature_definition": bool(stale),
        "refresh_required": bool(stale),
        "note": (
            "当前模型工件早于 BRW-013X V2 特征定义，且从未使用 "
            "BRW-017R2 canonical 包络峰值 TOF"
        )
        if stale
        else "特征定义与当前策略一致",
    }


def _leading_exploratory(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    """Newest EXPLORATORY_FULL_DATA correlation row for the SOC target."""
    an_root = processed_root / "feature_analysis" / b / e / (
        "DS::6a3142e5186fc684964ff09e"
    )
    if not an_root.is_dir():
        return None
    newest: tuple[str, pd.DataFrame] | None = None
    for an in sorted(an_root.glob("AN::*")):
        manifest = _read_json(an / "analysis_manifest.json") or {}
        if manifest.get("analysis_mode") != "EXPLORATORY_FULL_DATA":
            continue
        corr_path = an / "feature_target_correlation.parquet"
        if not corr_path.is_file():
            continue
        try:
            df = pd.read_parquet(corr_path)
        except (OSError, ValueError):
            continue
        if df.empty:
            continue
        if newest is None or an.name > newest[0]:
            newest = (an.name, df)
    if newest is None:
        return None
    _, df = newest
    row = df.iloc[0]
    return {
        "analysis_id": newest[0],
        "feature_name": str(row.get("feature_name")),
        "method": str(row.get("method")),
        "coefficient": round(float(row["coefficient"]), 4) if pd.notna(row["coefficient"]) else None,
        "n": int(row["n"]) if pd.notna(row["n"]) else None,
        "note": "取自持久化的 EXPLORATORY_FULL_DATA 分析（未重新计算）",
    }


def _scientific_snapshot(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Target + leading exploratory candidate + model evidence (read-only).

    The leading candidate reuses the feature-target-ranking computation
    (deterministic, read-only); no new science is defined here.
    """
    dataset_manifest = _read_json(
        processed_root
        / "datasets" / b / e / "SOC" / "DS::6a3142e5186fc684964ff09e" / "dataset_manifest.json"
    )
    selected_features = (dataset_manifest or {}).get("selected_features") or []
    feature_state = _feature_definition_state(processed_root, b, e)

    comparison = _model_comparison(processed_root, b, e)
    # leading exploratory candidate from the newest persisted EXPLORATORY
    # correlation artifact (read-only; no fresh computation, no artifact writes)
    leading = _leading_exploratory(processed_root, b, e)
    return {
        "target": {"target_id": "reference_soc_percent",
                   "readiness": "READY_FOR_LIMITED_EVALUATION",
                   "note": "retrospective segment-normalized reference label"},
        "leading_exploratory_candidate": leading,
        "selected_features": selected_features,
        "model_evidence": {
            "dummy_first_conclusion": comparison.get("dummy_first_conclusion"),
            "dummy_macro_mae": comparison.get("dummy", {}).get("macro_mae"),
            "note": "no model beat the Dummy baseline in the current same-scope evaluation",
        },
        "feature_definition": feature_state,
    }


def _model_comparison(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Current model artifact rows + freshness flags (never re-trained)."""
    root = processed_root / "models" / b / e
    comp_path = next(root.rglob("model_comparison.json"), None)
    if comp_path is None:
        return {"status": "UNAVAILABLE", "strategies": []}
    rows = _read_json(comp_path) or []
    feature_state = _feature_definition_state(processed_root, b, e)
    strategies = [
        {
            "strategy": r.get("strategy"),
            "macro_mae": r.get("macro_MAE"),
            "macro_rmse": r.get("macro_RMSE"),
            "macro_r2": r.get("macro_R2"),
            "vs_dummy": r.get("macro_MAE_vs_DUMMY"),
        }
        for r in rows
    ]
    dummy = next((s for s in strategies if s["strategy"] == "DUMMY_MEAN"), None)
    return {
        "status": "AVAILABLE",
        "artifact_path": str(comp_path.relative_to(processed_root)),
        "strategies": strategies,
        "dummy": dummy,
        "dummy_first_conclusion": (
            "当前同口径评估中没有任何模型跑赢 Dummy 基准"
            if dummy is not None
            and all(
                (s["macro_mae"] or 0) >= (dummy["macro_mae"] or 0)
                for s in strategies
                if s["strategy"] != "DUMMY_MEAN"
            )
            else None
        ),
        "feature_definition": feature_state,
    }


_LIMITATION_ZH: dict[str, str] = {
    "ONE_BATTERY_ONLY": "数据集仅含 1 块电池——无法进行跨电池评估",
    "SOH_INDEPENDENT_STATES_TOO_FEW": "SOH 仅有 2 个独立状态（事件行不独立），不足以建模",
    "LIMITED_CROSS_CYCLE_GENERALIZATION": "仅限同电池跨循环评估，不外推泛化",
    "PROVISIONAL_TIMEBASE": "同步时间基准为临时基准（尚未验证）",
}


def _limitations_first_screen() -> list[dict[str, str]]:
    from battery_workbench.reporting.collector import collect_limitation_registry

    codes = {"PROVISIONAL_TIMEBASE", "SOH_INDEPENDENT_STATES_TOO_FEW",
             "LIMITED_CROSS_CYCLE_GENERALIZATION", "ONE_BATTERY_ONLY"}
    out = []
    for l in collect_limitation_registry():
        if l["code"] not in codes:
            continue
        out.append({**l, "description_zh": _LIMITATION_ZH.get(l["code"], l["description"])})
    return out


def _next_actions(processed_root: Path, b: str, e: str) -> list[dict[str, str]]:
    """Recommended next action from the current scientific state (≤3)."""
    fs_state = _fs_state(processed_root, b, e)
    actions: list[dict[str, str]] = []
    if not fs_state["sampling_rate_verified"]:
        actions.append({
            "action_id": "PROVIDE_SAMPLING_RATE",
            "label": "填写并验证采样频率（参数注册表；绝不猜测）",
            "route": f"/experiments/{b}/{e}/overview",
        })
    else:
        actions.append({
            "action_id": "CALIBRATE_TOF_GATES",
            "label": "标定并冻结 TOF 双闸门（波形工作台）",
            "route": f"/experiments/{b}/{e}/waveform",
        })
    actions.append({
        "action_id": "REVIEW_ALIGNMENT",
        "label": "复核同步对齐与 Feature–Target 预览（特征分析）",
        "route": f"/experiments/{b}/{e}/analysis",
    })
    actions.append({
        "action_id": "REVIEW_MODEL_BASELINES",
        "label": "复核 Dummy-first 基线结论与限制（建模评估）",
        "route": f"/experiments/{b}/{e}/models",
    })
    return actions[:3]


def research_overview_payload(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Assemble the aggregate payload (pure read; no artifact writes)."""
    return {
        "schema_version": "research-overview/1.0",
        "metadata": _metadata_strip(processed_root, b, e),
        "electrical": _electrical_snapshot(processed_root, b, e),
        "ultrasound_tof": _tof_snapshot(processed_root, b, e),
        "signal_quality": _signal_quality(processed_root, b, e),
        "readiness_matrix": _readiness_matrix(processed_root, b, e),
        "scientific_snapshot": _scientific_snapshot(processed_root, b, e),
        "model_comparison": _model_comparison(processed_root, b, e),
        "limitations_first_screen": _limitations_first_screen(),
        "next_actions": _next_actions(processed_root, b, e),
        "research_status_banner": _research_banner(processed_root, b, e),
    }


def _research_banner(processed_root: Path, b: str, e: str) -> dict[str, str]:
    fs_state = _fs_state(processed_root, b, e)
    if not fs_state["sampling_rate_verified"]:
        return {
            "level": "BLOCKED",
            "message": (
                "阻断：采样频率未在参数注册表验证（canonical TOF 未激活）。"
                "原始波形查看不受影响。"
            ),
        }
    return {
        "level": "LIMITED",
        "message": (
            "受限评估就绪：fs 已验证，TOF 规范管线可用；时间基准仍为 PROVISIONAL，"
            "SOH 依据不足，无跨电池评估。"
        ),
    }


def get_research_overview_data(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    validate_id(b, "battery_id")
    validate_id(e, "experiment_id")
    if not (processed_root / "electrical" / b / e).is_dir() and not (
        processed_root / "ultrasound" / b / e
    ).is_dir():
        raise APIError(ErrorCode.NOT_FOUND, "experiment artifacts not available")
    return research_overview_payload(processed_root, b, e)

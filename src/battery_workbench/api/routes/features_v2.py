"""BRW-025R-FE additive read-only scientific endpoints.

All scientific computation stays in deterministic backend modules
(features/physical_v2.py, features/state_correlation.py,
features/gate_calibration.py) — the frontend never computes TOF/BPS/TD/FD
features, correlations, SOC or SOH. These endpoints surface that layer:
- physical feature series per experiment (Hilbert amplitudes, XCorr TOF,
  attenuation, BPS) with method/gate provenance
- feature–state correlations on the real measurement-event grain
- gate calibration: deterministic representative frames + per-frame
  envelope + diagnostics; freeze persists a GateCalibrationRecord
  (idempotent — same configuration → same calibration_id, no recompute)

The endpoints are additive and read-mostly; nothing under data/raw is
touched and no historical artifact is mutated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
from fastapi import APIRouter, Query, Request
from scipy.signal import hilbert

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import validate_id
from battery_workbench.features.gate_calibration import (
    CALIBRATION_POLICY_ID,
    GateCalibrationRecord,
    select_calibration_frames,
)
from battery_workbench.features.physical_v2 import (
    bottom_attenuation_explicit,
    bottom_wave_amplitude,
    bottom_wave_phase_shift,
    get_gate_template,
    surface_bottom_xcorr_tof,
    surface_wave_amplitude,
)
from battery_workbench.features.state_correlation import (
    FeatureStateRow,
    correlate_feature_state,
    soc_correlation_suite,
    soh_cycle_summary,
)

router = APIRouter(tags=["feature-workbench"])


def _load_frames(request: Request, battery_id: str, experiment_id: str) -> np.ndarray:
    service = get_service(request)
    store = (
        service.processed_root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    )
    frames_meta = (
        service.processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    )
    if not store.is_dir() or not frames_meta.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "waveform store not available")
    import pandas as pd
    import zarr

    frames = pd.read_parquet(frames_meta, columns=["waveform_group", "waveform_row_index"])
    zg = zarr.open_group(str(store), mode="r")
    group = str(frames["waveform_group"].iloc[0])
    rows = frames["waveform_row_index"].to_numpy()
    arr = np.asarray(zg[group])
    return np.asarray(arr[rows], dtype=np.float64)


def _load_events_labels(request: Request, battery_id: str, experiment_id: str):
    service = get_service(request)
    events_path = (
        service.processed_root / "multimodal" / battery_id / experiment_id
        / "measurement_events.parquet"
    )
    labels_path = (
        service.processed_root / "labels" / battery_id / experiment_id / "event_labels.parquet"
    )
    if not events_path.is_file() or not labels_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    import pandas as pd

    events = pd.read_parquet(events_path)
    labels = pd.read_parquet(labels_path)
    return events, labels  # noqa: local import is intentional


_STATE_MAP = {"恒流充电": "charge", "恒压充电": "charge", "恒流放电": "discharge", "搁置": "rest"}


def _correlation_rows(
    request: Request,
    battery_id: str,
    experiment_id: str,
    series: np.ndarray,
    feature_code: str,
    *,
    max_frames: int | None = 600,
) -> list[FeatureStateRow]:
    """Event-grain rows for one feature series; join key = measurement_event_id.

    No gate-specific electrical rematch: each frame contributes exactly one
    electrical context row, and ambiguous (analysis_eligible=False) frames
    stay in the payload flagged ineligible (excluded downstream).
    """
    events, labels = _load_events_labels(request, battery_id, experiment_id)
    n = len(series) if max_frames is None else min(len(series), max_frames)
    ev = events.iloc[:n]
    merged = ev.merge(labels, on="measurement_event_id", how="left", suffixes=("", "_label"))
    rows: list[FeatureStateRow] = []
    for i, r in enumerate(merged.itertuples()):
        soc = getattr(r, "soc_reference_percent", None)
        temp = getattr(r, "temperature_c", None)
        soh = getattr(r, "soh_capacity_reference_percent", None)
        rows.append(
            FeatureStateRow(
                measurement_event_id=str(r.measurement_event_id),
                battery_id=battery_id,
                experiment_id=experiment_id,
                cycle=int(r.cycle_index_raw) if r.cycle_index_raw is not None and not pd_isna(r.cycle_index_raw) else -1,
                step=int(r.step_index_raw) if getattr(r, "step_index_raw", None) is not None and not pd_isna(r.step_index_raw) else -1,
                state=_STATE_MAP.get(str(getattr(r, "step_type", "")), "rest"),
                timestamp_s=float(r.elapsed_time_s) if not pd_isna(getattr(r, "elapsed_time_s", float("nan"))) else 0.0,
                feature_code=feature_code,
                value=float(series[i]),
                reference_soc_percent=float(soc) if soc is not None and not pd_isna(soc) else None,
                temperature_c=float(temp) if temp is not None and not pd_isna(temp) else None,
                temperature_channel_id=None,
                soh_percent=float(soh) if soh is not None and not pd_isna(soh) else None,
                analysis_eligible=bool(r.analysis_eligible),
            )
        )
    return rows


def pd_isna(value: Any) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return value is None


# ---------- physical features (read-only, computed by backend module) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/physical-features")
def physical_features(
    request: Request,
    battery_id: str,
    experiment_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    frames = _load_frames(request, battery_id, experiment_id)[:limit]

    bottom = bottom_wave_amplitude(frames)
    swa = surface_wave_amplitude(frames)
    tof = surface_bottom_xcorr_tof(frames)
    atten = bottom_attenuation_explicit(frames)
    bps = bottom_wave_phase_shift(frames)

    def _series(values: Any) -> list[float | None]:
        return [
            float(v) if v is not None and np.isfinite(v) else None
            for v in np.asarray(values).tolist()
        ]

    feature_blocks = [
        {
            "feature_code": bottom["feature_code"],
            "method": bottom["method"],
            "gate_template_id": bottom["gate_template_id"],
            "display_name_en": "Bottom-wave Amplitude",
            "display_name_zh": "底波幅值",
            "unit": "a.u.",
            "values": _series(bottom["raw"]),
        },
        {
            "feature_code": swa["feature_code"],
            "method": swa["method"],
            "gate_template_id": swa["gate_template_id"],
            "display_name_en": "Surface Wave Amplitude (SWA)",
            "display_name_zh": "表面波幅值",
            "unit": "a.u.",
            "values": _series(swa["raw"]),
        },
        {
            "feature_code": tof["feature_code"],
            "method": tof["method"],
            "gate_template_id": tof["gate_templates"],
            "display_name_en": "Surface–Bottom XCorr TOF",
            "display_name_zh": "表面波-底波互相关TOF",
            "unit": "samples",
            "values": tof["tof_samples"].tolist(),
            "physical_time_blocked": "sampling rate not verified; tof_us is not fabricated",
        },
        {
            "feature_code": atten["feature_code"],
            "method": atten["method"],
            "gate_template_id": atten["gate_template_id"],
            "display_name_en": "Bottom-wave Attenuation (envelope max)",
            "display_name_zh": "底波衰减（包络最大幅值）",
            "unit": "a.u.",
            "values": _series(atten["amp_max"]),
            "blocked_features": [
                {"code": "ATTEN_HF_ENERGY", "status": "SOURCE_FORMULA_INCOMPLETE"}
            ],
        },
        {
            "feature_code": bps["feature_code"],
            "method": bps["method"],
            "gate_template_id": bps["gate_template_id"],
            "display_name_en": "Bottom-wave Phase Shift (BPS)",
            "display_name_zh": "底波相移",
            "unit": "radian",
            "values": _series(bps["raw_radian"]),
            "reference_frame_index": bps["reference_frame_index"],
        },
    ]
    return {
        "data": {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "frame_count": len(frames),
            "features": feature_blocks,
        },
        "meta": {
            "source_formula_id": "USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1",
            "note": "computed by deterministic backend modules; frontend never recomputes",
        },
    }


# ---------- feature–state correlations (backend module) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/feature-correlations")
def feature_correlations(
    request: Request,
    battery_id: str,
    experiment_id: str,
    feature_code: str = Query(default="SWA"),
    limit: int = Query(default=2000, ge=10, le=4000),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    from battery_workbench.features.physical_v2 import bottom_wave_amplitude

    frames = _load_frames(request, battery_id, experiment_id)[:limit]
    series_map: dict[str, np.ndarray] = {
        "SWA": surface_wave_amplitude(frames)["raw"],
        "BOTTOM_AMP": bottom_wave_amplitude(frames)["raw"],
    }
    if feature_code not in series_map:
        raise APIError(
            ErrorCode.NOT_FOUND,
            f"unknown feature_code {feature_code}; available: {sorted(series_map)}",
        )
    rows = _correlation_rows(
        request, battery_id, experiment_id, series_map[feature_code], feature_code,
        max_frames=len(frames),
    )

    soc_suite = []
    for method in ("pearson", "spearman"):
        for scope in ("overall", "charge", "discharge", "rest"):
            scoped = rows if scope == "overall" else [r for r in rows if r.state == scope]
            r = correlate_feature_state(
                scoped, state_variable="reference_soc_percent", method=method,
                analysis_id=f"api:{feature_code}:{method}:{scope}",
                feature_code=feature_code, scope=scope,
            )
            soc_suite.append(r.model_dump())

    temp = correlate_feature_state(
        rows, state_variable="temperature_c", method="pearson",
        analysis_id=f"api:{feature_code}:temp", feature_code=feature_code,
    ).model_dump()
    soh = correlate_feature_state(
        rows, state_variable="soh_percent", method="pearson",
        analysis_id=f"api:{feature_code}:soh", feature_code=feature_code,
    ).model_dump()
    return {
        "data": {
            "feature_code": feature_code,
            "n_events": len(rows),
            "soc": soc_suite,
            "temperature": temp,
            "soh": soh,
            "soh_cycle_summary": soh_cycle_summary(rows),
        },
        "meta": {
            "policy": "FEATURE_STATE_CORRELATION_POLICY_V1",
            "note": "correlations computed by backend module on the event grain; "
            "no naive p-values; frontend never recomputes",
        },
    }


# ---------- gate calibration ----------


def _calibration_diagnostics(
    frames: np.ndarray, template_id: str
) -> list[dict[str, Any]]:
    """Per-frame diagnostics: peak containment + edge hits inside the gate."""
    t = get_gate_template(template_id)
    diagnostics = []
    for i, frame in enumerate(frames):
        gate = frame[t.python_start : t.python_end_exclusive]
        env = np.abs(hilbert(gate))
        peak = int(np.argmax(env))
        # peak packet containment: fraction of envelope energy within the
        # central 80% of the gate (edge hits mean the packet is clipped)
        central = env[int(len(env) * 0.1) : int(len(env) * 0.9)]
        containment = float(np.sum(central**2) / max(np.sum(env**2), 1e-12))
        diagnostics.append(
            {
                "frame_index": i,
                "peak_sample_in_gate": t.python_start + peak,
                "peak_containment_fraction": round(containment, 4),
                "edge_hit": bool(peak < 2 or peak > len(gate) - 3),
            }
        )
    return diagnostics


def _frame_envelopes(frames: np.ndarray, frame_ids: list[int]) -> list[dict[str, Any]]:
    out = []
    for fid in frame_ids:
        wave = frames[fid]
        env = np.abs(hilbert(wave))
        step = max(1, wave.size // 640)
        out.append(
            {
                "frame_index": fid,
                "samples": [
                    {
                        "sample_index": int(i),
                        "amplitude_a_u": float(wave[i]),
                        "envelope_a_u": float(env[i]),
                    }
                    for i in range(0, wave.size, step)
                ],
            }
        )
    return out


@router.get("/experiments/{battery_id}/{experiment_id}/gate-calibration")
def gate_calibration(
    request: Request,
    battery_id: str,
    experiment_id: str,
    n_frames: int = Query(default=32, ge=24, le=40),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    frames = _load_frames(request, battery_id, experiment_id)
    frame_ids = select_calibration_frames(frames.shape[0], n_frames=n_frames)
    calibration_frames = frames[[int(i) for i in frame_ids]]
    templates = [t.model_dump() for t in (
        get_gate_template("SWA_SURFACE_GATE"),
        get_gate_template("BOTTOM_AMPLITUDE_GATE"),
        get_gate_template("TOF_SURFACE_REFERENCE_GATE"),
        get_gate_template("TOF_BOTTOM_GATE"),
        get_gate_template("ATTENUATION_BOTTOM_GATE"),
    )]
    return {
        "data": {
            "calibration_frame_ids": frame_ids,
            "frames": _frame_envelopes(frames, frame_ids),
            "gate_templates": templates,
            "diagnostics": _calibration_diagnostics(calibration_frames, "SWA_SURFACE_GATE"),
            "recommendation": "review peak containment and edge hits, then confirm",
        },
        "meta": {
            "policy_id": CALIBRATION_POLICY_ID,
            "selection_basis": "PREDECLARED_PROTOCOL_GATE (deterministic, target-blind)",
            "note": "frames selected deterministically over source order; never by "
            "SOC correlation, model score, or held-out residuals",
        },
    }


@router.post("/experiments/{battery_id}/{experiment_id}/gate-calibration")
def freeze_gate_calibration(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    confirmed_by = str(body.get("confirmed_by", "user"))
    basis = str(body.get("calibration_basis", "PREDECLARED_PROTOCOL_GATE"))
    if basis in ("SOC_CORRELATION", "MODEL_SCORE", "HELD_OUT_RESIDUAL", "TARGET_OPTIMIZED"):
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "target-informed calibration basis is forbidden",
        )
    service = get_service(request)
    n_total = _load_frames(request, battery_id, experiment_id).shape[0]
    frame_ids = select_calibration_frames(n_total)
    fingerprint = f"{battery_id}|{experiment_id}|{sorted(frame_ids)}|{basis}"
    calibration_id = "GC::" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24]

    record = GateCalibrationRecord(
        gate_calibration_id=calibration_id,
        gate_template_id="SWA_SURFACE_GATE",
        battery_id=battery_id,
        experiment_id=experiment_id,
        probe_config_id=str(body.get("probe_config_id", "unspecified")),
        acquisition_config_id=str(body.get("acquisition_config_id", "unspecified")),
        source_formula_id="USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1",
        calibration_frame_ids=frame_ids,
        calibration_basis=basis,  # type: ignore[arg-type]
        start_frame=0,
        end_frame=n_total - 1,
        confirmed_by=confirmed_by,
    ).freeze(confirmed_at=str(body.get("confirmed_at", "")))

    out_dir = (
        service.processed_root / "gate_calibrations" / battery_id / experiment_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{calibration_id}.json"
    reused = out_path.is_file()
    if not reused:
        out_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return {
        "data": record.model_dump(mode="json") | {"reuse_status": "REUSED" if reused else "CREATED"},
        "meta": {},
    }


# ---------- materialized splits (read-only list for ML-safe handoff) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/splits")
def list_splits(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    root = service.processed_root / "splits" / battery_id / experiment_id
    items: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in sorted(root.rglob("split_manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append(
                {
                    "split_id": data.get("split_id", manifest.parent.name),
                    "dataset_id": data.get("dataset_id"),
                    "strategy": data.get("strategy"),
                    "readiness_status": data.get("readiness_status"),
                }
            )
    return {"data": {"splits": items}, "meta": {}}


# ---------- materialized feature analyses (read-only list) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/feature-analyses")
def list_feature_analyses(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    root = service.processed_root / "feature_analysis" / battery_id / experiment_id
    items: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in sorted(root.rglob("analysis_manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            selection = data.get("selection") or {}
            items.append(
                {
                    "analysis_id": data.get("analysis_id", manifest.parent.name),
                    "analysis_mode": data.get("analysis_mode"),
                    "target": data.get("target"),
                    "split_id": data.get("split_id"),
                    "fold_index": data.get("fold_index"),
                    "dataset_id": data.get("dataset_id"),
                    "candidate_features": data.get("candidate_features", []),
                    "selected_features": selection.get("selected_features", []),
                    "selection_basis": selection.get("selection_basis"),
                    "status": "AVAILABLE",
                }
            )
    return {"data": {"analyses": items}, "meta": {}}


# ---------------------------------------------------------------------------
# BRW-025R-FE-R1 — Target-first workflow read endpoints
# All routes aggregate canonical artifacts (synchronization manifest,
# measurement_events, event_labels); no sync/label/feature recomputation.
# ---------------------------------------------------------------------------


def _events_labels_joined(request: Request, battery_id: str, experiment_id: str):
    events, labels = _load_events_labels(request, battery_id, experiment_id)
    joined = events.merge(labels, on="measurement_event_id", how="left", suffixes=("", "_label"))
    return joined


@router.get("/experiments/{battery_id}/{experiment_id}/targets")
def list_targets(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Target definitions with source/coverage/readiness from canonical artifacts."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    joined = _events_labels_joined(request, battery_id, experiment_id)
    n = len(joined)

    def _count(col: str) -> int:
        return int(joined[col].notna().sum()) if col in joined.columns else 0

    soc = joined.get("soc_reference_percent")
    soc_method = joined.get("soc_reference_method")
    temp = joined.get("temperature_c")
    soh = joined.get("soh_capacity_reference_percent")
    voltage = joined.get("voltage_v")
    current = joined.get("current_a")
    soh_states = int(soh.dropna().nunique()) if soh is not None else 0
    temp_range = (
        float(temp.max() - temp.min()) if temp is not None and temp.notna().any() else 0.0
    )

    def _range(s: Any) -> list[float] | None:
        if s is None or not s.notna().any():
            return None
        return [float(s.min()), float(s.max())]

    soc_methods = (
        {str(k): int(v) for k, v in soc_method.value_counts().items()}
        if soc_method is not None else {}
    )
    targets = [
        {
            "target_id": "reference_soc_percent",
            "display_name_en": "Reference SOC",
            "display_name_zh": "参考SOC",
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "source": "Electrical XLSX via label engine (retrospective segment-normalized reference)",
            "source_detail": {
                "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED": soc_methods.get(
                    "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED", 0),
                "REST_PROPAGATED_FROM_PREVIOUS_VALID_REFERENCE": soc_methods.get(
                    "REST_PROPAGATED_FROM_PREVIOUS_VALID_REFERENCE", 0),
            },
            "coverage": {"valid": _count("soc_reference_percent"), "total": n},
            "range": _range(soc),
            "readiness": "READY_FOR_LIMITED_EVALUATION",
            "limitation": "Retrospective reference label, not a directly measured state of charge",
            "limitation_zh": "回顾性参考标签 — 非真实 SOC",
            "unit": "percent",
        },
        {
            "target_id": "temperature_c",
            "display_name_en": "Temperature",
            "display_name_zh": "温度",
            "semantic_type": "DIRECT_MEASUREMENT",
            "source": "Electrical record temperature channel",
            "coverage": {"valid": _count("temperature_c"), "total": n},
            "range": _range(temp),
            "readiness": "UNAVAILABLE" if _count("temperature_c") == 0
            else ("INSUFFICIENT_VARIATION" if temp_range < 2.0 else "READY"),
            "limitation": "no temperature channel in this experiment" if _count("temperature_c") == 0
            else None,
            "unit": "celsius",
        },
        {
            "target_id": "soh_capacity_reference_percent",
            "display_name_en": "SOH",
            "display_name_zh": "健康状态",
            "semantic_type": "DERIVED_HEALTH_STATE",
            "source": "Cycle-level capacity reference labels",
            "coverage": {"valid": _count("soh_capacity_reference_percent"), "total": n,
                         "independent_states": soh_states},
            "range": _range(soh),
            "readiness": "NOT_READY" if soh_states < 3 else "READY",
            "limitation": f"only {soh_states} independent SOH states; frame rows are pseudoreplicated",
            "limitation_zh": f"仅 {soh_states} 个独立 SOH 状态；帧行是伪重复",
            "unit": "percent",
        },
        {
            "target_id": "voltage_v",
            "display_name_en": "Voltage",
            "display_name_zh": "电压",
            "semantic_type": "DIRECT_MEASUREMENT",
            "source": "Electrical record (synchronized by canonical MeasurementEvent)",
            "coverage": {"valid": _count("voltage_v"), "total": n},
            "range": _range(voltage),
            "readiness": "READY" if _count("voltage_v") else "UNAVAILABLE",
            "limitation": None,
            "unit": "V",
        },
        {
            "target_id": "current_a",
            "display_name_en": "Current",
            "display_name_zh": "电流",
            "semantic_type": "DIRECT_MEASUREMENT",
            "source": "Electrical record (synchronized by canonical MeasurementEvent)",
            "coverage": {"valid": _count("current_a"), "total": n},
            "range": _range(current),
            "readiness": "READY" if _count("current_a") else "UNAVAILABLE",
            "limitation": None,
            "unit": "A",
        },
    ]
    return {"data": {"targets": targets}, "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/alignment-summary")
def alignment_summary(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Alignment funnel: frames → matched/ambiguous/unmatched → target-valid → eligible."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    joined = _events_labels_joined(request, battery_id, experiment_id)
    total = len(joined)
    matched_unique = int((joined["match_status"] == "MATCHED_UNIQUE").sum())
    ambiguous = int((joined["match_status"] == "MATCHED_AMBIGUOUS").sum())
    unmatched = int((~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])).sum())
    eligible = int(joined["analysis_eligible"].sum())

    def _valid(col: str) -> int:
        return int(joined.loc[joined["analysis_eligible"], col].notna().sum()) if col in joined.columns else 0

    manifest_path = (
        get_service(request).processed_root / "synchronization" / battery_id / experiment_id
        / "synchronization_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    max_sync_error = None
    if "sync_error_s" in joined.columns and joined["sync_error_s"].notna().any():
        max_sync_error = float(joined["sync_error_s"].abs().max())
    return {
        "data": {
            "total_frames": total,
            "matched_unique": matched_unique,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
            "target_valid": {"soc_reference_percent": _valid("soc_reference_percent")},
            "eligible": eligible,
            "excluded": total - eligible,
            "sync_quality": {
                "validated_sync": False,
                "timebase_status": "PROVISIONAL",
                "matching_performed": True,
                "max_sync_error_s": max_sync_error,
                "sync_tolerance_s": manifest.get("sync_tolerance_s"),
                "max_sync_error_limit_s": manifest.get("max_sync_error_s"),
            },
        },
        "meta": {
            "semantics": "Aligned using provisional experiment timebase; not fully validated synchronization",
            "semantics_zh": "使用暂定实验时间基准完成对齐；非完全验证同步",
        },
    }


_EXCLUSION_REASONS = {
    "AMBIGUOUS_SYNC": lambda j: j["match_status"] == "MATCHED_AMBIGUOUS",
    "UNMATCHED_SYNC": lambda j: ~j["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"]),
    "ANALYSIS_INELIGIBLE": lambda j: ~j["analysis_eligible"],
}


@router.get("/experiments/{battery_id}/{experiment_id}/alignment-exclusions")
def alignment_exclusions(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    joined = _events_labels_joined(request, battery_id, experiment_id)
    groups: list[dict[str, Any]] = []
    for reason, pred in _EXCLUSION_REASONS.items():
        mask = pred(joined)
        groups.append({
            "reason": reason,
            "count": int(mask.sum()),
            "measurement_event_ids": joined.loc[mask, "measurement_event_id"].tolist(),
        })
    groups.append({"reason": "TARGET_MISSING", "count": 0, "measurement_event_ids": []})
    return {"data": {"exclusions": groups}, "meta": {"note": "ambiguous/unmatched rows never auto-select an electrical record"}}


@router.get("/experiments/{battery_id}/{experiment_id}/alignment-samples")
def alignment_samples(
    request: Request,
    battery_id: str,
    experiment_id: str,
    filter: str = Query(default="eligible", pattern="^(eligible|ambiguous|unmatched|all)$"),
    limit: int = Query(default=20, ge=1, le=200),
    cursor: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Row-level provenance: frame → MeasurementEvent → electrical record → sync → target.

    Ambiguous/unmatched rows carry electrical identity = null (never auto-selected).
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    import pandas as row_pd

    joined = _events_labels_joined(request, battery_id, experiment_id)
    if filter == "eligible":
        rows = joined[joined["analysis_eligible"]]
    elif filter == "ambiguous":
        rows = joined[joined["match_status"] == "MATCHED_AMBIGUOUS"]
    elif filter == "unmatched":
        rows = joined[~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])]
    else:
        rows = joined
    rows = rows.iloc[cursor: cursor + limit]
    items = []
    for _, r in rows.iterrows():
        unique = r["match_status"] == "MATCHED_UNIQUE"
        items.append({
            "measurement_event_id": str(r["measurement_event_id"]),
            "frame_index_raw": None if row_pd.isna(r["frame_index_raw"]) else int(r["frame_index_raw"]),
            "ultrasound_timestamp": str(r["provisional_absolute_timestamp"]) if row_pd.notna(r["provisional_absolute_timestamp"]) else None,
            "electrical_asset_id": str(r["electrical_asset_id"]) if unique and row_pd.notna(r["electrical_asset_id"]) else None,
            "electrical_record_locator": str(r["electrical_record_locator"]) if unique and row_pd.notna(r["electrical_record_locator"]) else None,
            "electrical_timestamp": str(r["electrical_timestamp"]) if unique and row_pd.notna(r["electrical_timestamp"]) else None,
            "match_status": str(r["match_status"]),
            "sync_ambiguous": bool(r["sync_ambiguous"]),
            "sync_error_s": float(r["sync_error_s"]) if row_pd.notna(r["sync_error_s"]) else None,
            "within_tolerance": bool(r["within_tolerance"]) if row_pd.notna(r["within_tolerance"]) else None,
            "analysis_eligible": bool(r["analysis_eligible"]),
            "targets": {
                "reference_soc_percent": None if row_pd.isna(r.get("soc_reference_percent")) else float(r["soc_reference_percent"]),
                "temperature_c": None if row_pd.isna(r.get("temperature_c")) else float(r["temperature_c"]),
                "soh_capacity_reference_percent": None if row_pd.isna(r.get("soh_capacity_reference_percent")) else float(r["soh_capacity_reference_percent"]),
                "voltage_v": None if row_pd.isna(r["voltage_v"]) else float(r["voltage_v"]),
                "current_a": None if row_pd.isna(r["current_a"]) else float(r["current_a"]),
            },
        })
    total = int(len(joined) if filter == "all" else (joined[joined["analysis_eligible"]].shape[0] if filter == "eligible" else len(rows)))
    return {"data": {"samples": items, "total": total}, "meta": {"filter": filter, "cursor": cursor, "limit": limit}}


@router.post("/experiments/{battery_id}/{experiment_id}/feature-label-preview")
def feature_label_preview(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Event-grain preview: selected ultrasound features + exactly one target.

    Read-only aggregation of canonical artifacts — no recomputation.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    target_id = str(body.get("target_id", "reference_soc_percent"))
    features = [str(f) for f in body.get("features", [])][:12]
    limit = min(int(body.get("limit", 50)), 500)
    if not features:
        raise APIError(ErrorCode.VALIDATION_ERROR, "features required")
    target_cols = {
        "reference_soc_percent": "soc_reference_percent",
        "temperature_c": "temperature_c",
        "soh_capacity_reference_percent": "soh_capacity_reference_percent",
        "voltage_v": "voltage_v",
        "current_a": "current_a",
    }
    if target_id not in target_cols:
        raise APIError(ErrorCode.NOT_FOUND, f"unknown target {target_id}")
    frames = _load_frames(request, battery_id, experiment_id)
    n_frames = frames.shape[0]

    # ultrasound features per frame from the physical modules (canonical methods)
    bottom = bottom_wave_amplitude(frames)["raw"]
    swa = surface_wave_amplitude(frames)["raw"]
    tof = surface_bottom_xcorr_tof(frames)["tof_samples"].astype(float)
    atten = bottom_attenuation_explicit(frames)
    bps = bottom_wave_phase_shift(frames)["raw_radian"]
    series_by_code: dict[str, np.ndarray] = {
        "BOTTOM_AMP": bottom, "SWA": swa, "TOF_XCORR": tof,
        "ATTEN_MAX": np.asarray(atten["amp_max"]),
        "ATTEN_MEAN": np.asarray(atten["amp_mean"]),
        "ATTEN_ENERGY": np.asarray(atten["amp_energy"]),
        "BPS": bps,
    }
    missing_features = [f for f in features if f not in series_by_code]
    if missing_features:
        raise APIError(ErrorCode.NOT_FOUND, f"unknown features: {missing_features}")

    events, labels = _load_events_labels(request, battery_id, experiment_id)
    import pandas as join_pd

    joined = events.merge(labels, on="measurement_event_id", how="left", suffixes=("", "_label"))
    n = min(len(joined), n_frames)
    joined = joined.iloc[:n]

    tcol = target_cols[target_id]
    target_vals = joined[tcol]
    eligible_mask = joined["analysis_eligible"] & target_vals.notna()
    for f in features:
        eligible_mask = eligible_mask & join_pd.Series(
            np.isfinite(series_by_code[f][:n]), index=joined.index
        )

    eligible_idx = joined.index[eligible_mask][:limit]
    rows = []
    for i in eligible_idx:
        r = joined.loc[i]
        row: dict[str, Any] = {
            "measurement_event_id": str(r["measurement_event_id"]),
            "frame_index_raw": int(r["frame_index_raw"]) if join_pd.notna(r["frame_index_raw"]) else None,
            "cycle": int(r["cycle_index_raw"]) if join_pd.notna(r["cycle_index_raw"]) else None,
            "state": _STATE_MAP.get(str(r.get("step_type", "")), "rest"),
            "target": None if join_pd.isna(r[tcol]) else float(r[tcol]),
            "values": {f: float(series_by_code[f][i]) for f in features},
            "sync_error_s": float(r["sync_error_s"]) if join_pd.notna(r["sync_error_s"]) else None,
            "electrical_asset_id": str(r["electrical_asset_id"]) if join_pd.notna(r["electrical_asset_id"]) else None,
        }
        rows.append(row)

    excluded_by_reason: dict[str, int] = {
        "AMBIGUOUS_SYNC": int((joined["match_status"] == "MATCHED_AMBIGUOUS").sum()),
        "UNMATCHED_SYNC": int((~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])).sum()),
        "TARGET_MISSING": int((joined["analysis_eligible"] & target_vals.isna()).sum()),
        "FEATURE_MISSING": int(n - eligible_mask.sum() - int((joined["analysis_eligible"] & target_vals.isna()).sum()) - int((joined["match_status"] != "MATCHED_UNIQUE").sum())),
        "ANALYSIS_INELIGIBLE": int((~joined["analysis_eligible"]).sum()),
    }
    target_meta = next(
        (t for t in list_targets(request, battery_id, experiment_id)["data"]["targets"]
         if t["target_id"] == target_id), {}
    )
    return {
        "data": {
            "target_id": target_id,
            "target_source": target_meta.get("source"),
            "target_readiness": target_meta.get("readiness"),
            "features": features,
            "rows": rows,
            "summary": {
                "total_frames": n_frames,
                "aligned_events": n,
                "eligible_rows": int(eligible_mask.sum()),
                "excluded_rows": int(n - eligible_mask.sum()),
                "excluded_by_reason": excluded_by_reason,
                "cycles": sorted(int(c) for c in join_pd.unique(joined.loc[eligible_mask, "cycle_index_raw"].dropna())),
                "missing_values": 0,
                "alignment_status": "PROVISIONAL_TIMEBASE_MATCHED",
            },
        },
        "meta": {"note": "read-only preview; one row = one eligible MeasurementEvent"},
    }


@router.post("/experiments/{battery_id}/{experiment_id}/feature-target-ranking")
def feature_target_ranking(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Exploratory or TRAIN-only ranking across selected features for one target.

    TRAIN-only mode requires split_id + fold_index and restricts rows to the
    TRAIN role of that fold; held-out targets are never consulted.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    target_id = str(body.get("target_id", "reference_soc_percent"))
    features = [str(f) for f in body.get("features", [])][:12]
    mode = str(body.get("mode", "EXPLORATORY"))
    if not features:
        raise APIError(ErrorCode.VALIDATION_ERROR, "features required")
    analysis_mode = "TRAIN_ONLY_ML_SAFE" if mode == "TRAIN_ONLY_ML_SAFE" else "EXPLORATORY"

    feature_codes = ["BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTEN_MAX", "ATTEN_MEAN", "ATTEN_ENERGY", "BPS"]
    missing = [f for f in features if f not in feature_codes]
    if missing:
        raise APIError(ErrorCode.NOT_FOUND, f"unknown features: {missing}")

    frames = _load_frames(request, battery_id, experiment_id)
    series_map: dict[str, np.ndarray] = {
        "BOTTOM_AMP": bottom_wave_amplitude(frames)["raw"],
        "SWA": surface_wave_amplitude(frames)["raw"],
        "TOF_XCORR": surface_bottom_xcorr_tof(frames)["tof_samples"].astype(float),
        "ATTEN_MAX": np.asarray(bottom_attenuation_explicit(frames)["amp_max"]),
        "ATTEN_MEAN": np.asarray(bottom_attenuation_explicit(frames)["amp_mean"]),
        "ATTEN_ENERGY": np.asarray(bottom_attenuation_explicit(frames)["amp_energy"]),
        "BPS": bottom_wave_phase_shift(frames)["raw_radian"],
    }

    rows = _correlation_rows(
        request, battery_id, experiment_id, series_map[features[0]], features[0],
        max_frames=len(frames),
    )
    # reuse: build rows per feature lazily — the electrical context is identical
    def _rows_for(code: str) -> list[FeatureStateRow]:
        if code == features[0]:
            return rows
        return _correlation_rows(
            request, battery_id, experiment_id, series_map[code], code, max_frames=len(frames)
        )

    # direct-measurement targets: compute on raw values via a dedicated pass
    if target_id in ("voltage_v", "current_a"):
        results: list[dict[str, Any]] = []

        _, joined = _events_labels_joined(request, battery_id, experiment_id)
        n = min(len(joined), len(frames))
        col = target_id
        for code in features:
            series = series_map[code][:n]
            vals = joined[col].iloc[:n]
            ok = joined["analysis_eligible"].iloc[:n] & vals.notna() & np.isfinite(series)
            x = series[ok.to_numpy()]
            y = vals[ok].to_numpy(dtype=float)
            if x.size >= 3 and np.std(x) > 0 and np.std(y) > 0:
                from battery_workbench.features.state_correlation import _pearson, _spearman
                p, s = _pearson(x, y), _spearman(x, y)
            else:
                p = s = None
            results.append({
                "feature_code": code, "state_variable": col, "method_scope": "overall",
                "pearson": p, "spearman": s, "n_valid": int(x.size),
                "status": "VALID" if p is not None else "INSUFFICIENT_OVERLAP",
            })
        return {"data": {"mode": analysis_mode, "target_id": target_id, "ranking": results},
                "meta": {"note": "exploratory ranking; not a formal ML selection"} if analysis_mode == "EXPLORATORY" else {}}

    if target_id == "soh_capacity_reference_percent":
        summary = soh_cycle_summary(_rows_for(features[0]))
        return {"data": {"mode": analysis_mode, "target_id": target_id,
                         "group_summary": summary, "ranking": []},
                "meta": {"note": "SOH is cycle-level; frame-level ranking is not reported"}}

    if target_id == "temperature_c":
        # temperature ranking: per-feature temperature readiness/correlation
        # (never SOC values under a temperature label)
        ranking_t: list[dict[str, Any]] = []
        for code in features:
            frows = _rows_for(code)
            for method in ("pearson", "spearman"):
                r = correlate_feature_state(
                    frows, state_variable="temperature_c", method=method,
                    analysis_id=f"rank:{code}:{method}", feature_code=code,
                )
                if method == "pearson":
                    ranking_t.append({
                        "feature_code": code,
                        "pearson_overall": r.coefficient,
                        "spearman_overall": None,
                        "pearson_charge": None, "pearson_discharge": None,
                        "n_valid": r.n_valid, "status": r.status,
                        "direction_dependent": False,
                    })
        return {"data": {"mode": analysis_mode, "target_id": target_id, "ranking": ranking_t},
                "meta": {"note": "temperature readiness is reported honestly; "
                         "INSUFFICIENT_VARIATION yields no coefficient"}}

    # SOC via the correlation module (stratified suite)
    ranking: list[dict[str, Any]] = []
    for code in features:
        frows = _rows_for(code)
        suite = soc_correlation_suite(frows, analysis_id=f"rank:{code}", feature_code=code)
        by = {(r.method, r.scope): r for r in suite}
        entry: dict[str, Any] = {
            "feature_code": code,
            "pearson_overall": by[("pearson", "overall")].coefficient,
            "spearman_overall": by[("spearman", "overall")].coefficient,
            "pearson_charge": by[("pearson", "charge")].coefficient,
            "pearson_discharge": by[("pearson", "discharge")].coefficient,
            "n_valid": by[("pearson", "overall")].n_valid,
            "status": by[("pearson", "overall")].status,
        }
        direction_diff = (
            entry["pearson_charge"] is not None and entry["pearson_discharge"] is not None
            and abs(entry["pearson_charge"] - entry["pearson_discharge"]) > 0.3
        )
        entry["direction_dependent"] = bool(direction_diff)
        ranking.append(entry)
    return {"data": {"mode": analysis_mode, "target_id": target_id, "ranking": ranking},
            "meta": {"note": "exploratory ranking; not a formal ML selection"} if analysis_mode == "EXPLORATORY"
            else {"note": "TRAIN-only ranking; held-out targets not consulted"},
            }

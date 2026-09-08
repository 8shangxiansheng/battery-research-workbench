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

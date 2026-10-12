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
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from scipy.signal import hilbert

from battery_workbench.analysis.plan_registry import resolve_experiment_analysis_plan
from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.event_label_join import merge_event_labels
from battery_workbench.api.integrity import (
    assert_canonical_tof_integrity,
    assert_current_timebase_chain,
    assert_processed_artifact_integrity,
)
from battery_workbench.api.schemas import FeatureCorrelationsEnvelope
from battery_workbench.api.service import validate_id
from battery_workbench.conditions.assignment import assign_condition_segments_to_events
from battery_workbench.conditions.segments import load_condition_segments
from battery_workbench.features.gate_calibration import (
    CALIBRATION_POLICY_ID,
    GateBoundPair,
    GateCalibrationRecord,
    resolved_gate_bounds,
    select_calibration_frames,
)
from battery_workbench.features.physical_v2 import (
    bottom_attenuation_explicit,
    bottom_wave_amplitude,
    bottom_wave_phase_shift,
    get_gate_template,
    resolve_gate_bounds,
    surface_bottom_xcorr_tof,
    surface_wave_amplitude,
)
from battery_workbench.features.selected_series import (
    ALIAS_TO_RAW as _ALIAS_TO_RAW,
)
from battery_workbench.features.selected_series import (
    FEATURE_GATE_TEMPLATES,
    load_waveform_frames,
    selected_feature_series,
)
from battery_workbench.features.state_correlation import (
    CORRELATION_POLICY_ID,
    CORRELATION_POLICY_VERSIONS,
    FeatureStateRow,
    battery_condition_stratified_soc,
    battery_decomposed_soc_correlation,
    battery_scatter_diagnostic,
    condition_stratified_soc,
    correlate_feature_state,
    cycle_decomposed_soc_correlation,
    cycle_stratified_soc,
    exploratory_inference_assessment,
    soc_correlation_suite,
    soh_cycle_summary,
)
from battery_workbench.features_physical.canonical_tof import (
    canonical_tof_values_by_event,
    effective_fs,
)
from battery_workbench.io.experiment.manifest_loader import (
    data_asset_matches,
    load_data_assets,
)
from battery_workbench.multimodal.event_id import build_measurement_event_id
from battery_workbench.multimodal.schemas import CanonicalMeasurementEvent

router = APIRouter(tags=["feature-workbench"])


def _resolved_sampling_rate(
    processed_root: Path, battery_id: str, experiment_id: str
) -> tuple[float | None, bool, str | None]:
    """Resolve fs and its parameter-set identity using canonical TOF policy."""
    parameter_root = Path(processed_root) / "parameters" / battery_id / experiment_id
    fallback: tuple[float | None, bool, str | None] = (None, False, None)
    for manifest_path in sorted(parameter_root.glob("PS::*/parameter_set_manifest.json")):
        manifest = _read_json_local(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("sampling_rate_status") != "RESOLVED":
            continue
        parameter_set_id = manifest.get("parameter_set_id")
        if not isinstance(parameter_set_id, str) or parameter_set_id != manifest_path.parent.name:
            continue
        effective_path = manifest_path.parent / "effective_parameters.json"
        effective = _read_json_local(effective_path) if effective_path.is_file() else {}
        if not isinstance(effective, dict):
            effective = {}
        effective = effective.get("effective_parameters") or effective
        fs_hz, verified = effective_fs(effective, require_verified=False)
        candidate = (fs_hz, verified, parameter_set_id)
        if verified:
            return candidate
        if candidate[0] is not None and fallback[0] is None:
            fallback = candidate
    return fallback


def _canonical_tof_sampling_rate_matches(
    canonical_manifest: dict[str, Any],
    current: tuple[float | None, bool, str | None],
) -> bool:
    """Require matching parameter identity, verified state and physical value."""
    current_fs, current_verified, current_parameter_set_id = current
    try:
        artifact_fs = float(canonical_manifest.get("sampling_rate_hz"))
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        current_verified
        and current_fs is not None
        and current_parameter_set_id is not None
        and canonical_manifest.get("sampling_rate_verified") is True
        and canonical_manifest.get("parameter_set_id") == current_parameter_set_id
        and np.isclose(artifact_fs, current_fs, rtol=1e-12, atol=0.0)
    )


def _assert_source_provenance(
    request: Request,
    battery_id: str,
    experiment_id: str,
    *,
    modalities: tuple[str, ...] = ("electrical", "ultrasound"),
) -> None:
    service = get_service(request)
    from battery_workbench.provenance.parser_manifest import (
        invalid_parser_source_modalities,
        parser_output_integrity_reasons,
    )

    output_reasons = parser_output_integrity_reasons(
        service.processed_root, battery_id, experiment_id
    )
    invalid_modalities = [
        modality
        for modality in invalid_parser_source_modalities(
            service.processed_root,
            service.raw_root,
            battery_id,
            experiment_id,
        )
        if modality in modalities
    ]
    if invalid_modalities:
        integrity_reasons = {
            modality: output_reasons[modality]
            for modality in invalid_modalities
            if output_reasons.get(modality)
        }
        details: dict[str, Any] = {
            "invalid_modalities": invalid_modalities,
            "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
        }
        if integrity_reasons:
            details["integrity_reasons"] = integrity_reasons
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source provenance is invalid; scientific feature outputs are blocked",
            details,
        )
    # Validate nested source-to-asset mappings before output checks so malformed
    # provenance remains the primary, actionable error when both are invalid.
    _parser_source_assets(
        service.processed_root, battery_id, experiment_id, modalities=modalities
    )
    invalid_outputs = {
        modality: reasons
        for modality, reasons in output_reasons.items()
        if modality in modalities and reasons
    }
    if invalid_outputs:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser output integrity is invalid; scientific feature outputs are blocked",
            {
                "invalid_modalities": list(invalid_outputs),
                "integrity_reasons": invalid_outputs,
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            },
        )


def _require_current_split(request: Request, split_id: str, *, purpose: str) -> None:
    """Require verified Dataset/Split lineage before consuming split roles."""
    assessment = get_service(request).get_artifact(split_id)
    if assessment.get("availability") == "AVAILABLE":
        return
    error_code = (
        ErrorCode.INTEGRITY_ERROR
        if assessment.get("availability") == "BLOCKED"
        else ErrorCode.SCIENTIFIC_READINESS_BLOCKED
    )
    raise APIError(
        error_code,
        f"split source is not current; {purpose} is unavailable",
        {
            "split_id": split_id,
            "status": assessment.get("status"),
            **(assessment.get("fields") or {}),
        },
    )


def _load_frames(request: Request, battery_id: str, experiment_id: str) -> np.ndarray:
    _assert_source_provenance(
        request, battery_id, experiment_id, modalities=("ultrasound",)
    )
    service = get_service(request)
    store = service.processed_root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    frames_meta = (
        service.processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    )
    if not store.is_dir() or not frames_meta.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "waveform store not available")
    return load_waveform_frames(store, frames_meta)


def _experiment_gate_context(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Resolve the persisted generic gate calibration for this experiment."""
    service = get_service(request)
    calibration_id, bounds = resolved_gate_bounds(battery_id, experiment_id, service.processed_root)
    return {"gate_calibration_id": calibration_id, "gate_bounds": bounds}


def _validate_experiment_gate_context(context: dict[str, Any], frames: np.ndarray) -> None:
    """Reject corrupt or stale persisted bounds before feature calculations."""
    for template_id in context["gate_bounds"]:
        try:
            resolve_gate_bounds(
                template_id,
                context["gate_bounds"],
                sample_count=int(frames.shape[1]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                f"invalid frozen gate calibration for {template_id}: {exc}",
            ) from exc


def _load_events_labels(request: Request, battery_id: str, experiment_id: str):
    _assert_source_provenance(request, battery_id, experiment_id)
    service = get_service(request)
    events_path = (
        service.processed_root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_events.parquet"
    )
    labels_path = (
        service.processed_root / "labels" / battery_id / experiment_id / "event_labels.parquet"
    )
    if not events_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    event_manifest_path = (
        service.processed_root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_event_manifest.json"
    )
    if not event_manifest_path.is_file():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "measurement event provenance is required before feature analysis",
            {
                "integrity_reasons": ["MEASUREMENT_EVENT_MANIFEST_MISSING"],
                "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            },
        )
    assert_processed_artifact_integrity(
        service.processed_root,
        event_manifest_path,
        battery_id=battery_id,
        experiment_id=experiment_id,
        required_outputs={"events", "candidates"},
        required_inputs={"aligned", "sync_candidates", "electrical_records"},
    )
    label_manifest_path = labels_path.parent / "label_manifest.json"
    if not labels_path.is_file() and label_manifest_path.exists():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "label manifest exists but event labels are missing",
            {
                "integrity_reasons": ["LABEL_OUTPUT_MISSING:event_labels"],
                "recovery_action": "REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
            },
        )
    if not labels_path.is_file():
        raise APIError(
            ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
            "当前实验没有可用的标签工件；确认电学记录后运行 FULL_PRE_MODEL 标签生成流程。",
            {
                "target_id": "reference_soc_percent",
                "recovery_action": "RUN_LABEL_GENERATION",
                "recommended_profile": "FULL_PRE_MODEL",
            },
        )
    if not label_manifest_path.is_file():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "label provenance is required before feature analysis",
            {
                "integrity_reasons": ["LABEL_MANIFEST_MISSING"],
                "recovery_action": "REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
            },
        )
    assert_processed_artifact_integrity(
        service.processed_root,
        label_manifest_path,
        battery_id=battery_id,
        experiment_id=experiment_id,
        required_outputs={"event_labels"},
        required_inputs={"measurement_events", "records", "cycles", "steps"},
        required_manifest_fields={"label_set_id"},
        recovery_action="REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
    )
    import pandas as pd

    events = pd.read_parquet(events_path)
    labels = pd.read_parquet(labels_path)
    return events, labels


def _merge_event_labels(events: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Compatibility wrapper for the shared identity-safe label join."""
    return merge_event_labels(events, labels)


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
    joined_events = _merge_event_labels(events, labels)
    frames_meta_path = (
        get_service(request).processed_root
        / "ultrasound"
        / battery_id
        / experiment_id
        / "frames.parquet"
    )
    try:
        frame_metadata = pd.read_parquet(
            frames_meta_path, columns=["ultrasound_asset_id", "frame_index_raw"]
        )
    except (OSError, ValueError, KeyError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "waveform frame identity metadata is unavailable or invalid",
            {
                "integrity_reasons": ["WAVEFORM_FRAME_IDENTITY_METADATA_INVALID"],
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            },
        ) from exc
    series_by_event = _align_feature_series_to_event_frames(events, frame_metadata, series)
    n = len(series_by_event) if max_frames is None else min(len(series_by_event), max_frames)
    merged = joined_events.iloc[:n]
    rows: list[FeatureStateRow] = []
    for i, r in enumerate(merged.itertuples()):
        soc = getattr(r, "soc_reference_percent", None)
        temp = getattr(r, "temperature_c", None)
        temp_channel = getattr(r, "temperature_channel_id", None)
        soh = getattr(r, "soh_capacity_reference_percent", None)
        rows.append(
            FeatureStateRow(
                measurement_event_id=str(r.measurement_event_id),
                battery_id=battery_id,
                experiment_id=experiment_id,
                cycle=int(r.cycle_index_raw)
                if r.cycle_index_raw is not None and not pd_isna(r.cycle_index_raw)
                else -1,
                step=int(r.step_index_raw)
                if getattr(r, "step_index_raw", None) is not None and not pd_isna(r.step_index_raw)
                else -1,
                state=_STATE_MAP.get(str(getattr(r, "step_type", "")), "rest"),
                timestamp_s=float(r.elapsed_time_s)
                if not pd_isna(getattr(r, "elapsed_time_s", float("nan")))
                else 0.0,
                feature_code=feature_code,
                # NaN series values are missing, not data — keep the
                # correlation input finite so n_valid/n_missing stay honest.
                value=float(series_by_event[i]) if np.isfinite(series_by_event[i]) else None,
                reference_soc_percent=float(soc) if soc is not None and not pd_isna(soc) else None,
                temperature_c=float(temp) if temp is not None and not pd_isna(temp) else None,
                temperature_channel_id=(
                    str(temp_channel)
                    if temp_channel is not None and not pd_isna(temp_channel)
                    else None
                ),
                soh_percent=float(soh) if soh is not None and not pd_isna(soh) else None,
                analysis_eligible=bool(r.analysis_eligible),
            )
        )
    return rows


def _align_feature_series_to_event_frames(
    events: pd.DataFrame,
    frame_metadata: pd.DataFrame,
    series: np.ndarray,
) -> np.ndarray:
    """Associate waveform values with MeasurementEvents by asset/frame identity.

    Parquet row order is an implementation detail, not a cross-artifact key.
    This explicit join protects multi-asset analysis from positional drift.
    """
    required_event = {"ultrasound_asset_id", "frame_index_raw"}
    required_frame = {"ultrasound_asset_id", "frame_index_raw"}
    if not required_event.issubset(events.columns) or not required_frame.issubset(
        frame_metadata.columns
    ):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "waveform and MeasurementEvent identity columns are required",
            {
                "integrity_reasons": ["FRAME_EVENT_IDENTITY_COLUMNS_MISSING"],
                "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            },
        )
    values = np.asarray(series, dtype=np.float64)
    if len(frame_metadata) != len(values) or len(events) != len(values):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "waveform, frame metadata, and MeasurementEvent row counts differ",
            {
                "integrity_reasons": ["FRAME_EVENT_ROW_COUNT_MISMATCH"],
                "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            },
        )

    def identities(frame: pd.DataFrame, artifact_name: str) -> list[tuple[str, int]]:
        keys: list[tuple[str, int]] = []
        try:
            for asset_id, frame_index in frame[
                ["ultrasound_asset_id", "frame_index_raw"]
            ].itertuples(index=False, name=None):
                if pd.isna(asset_id) or pd.isna(frame_index):
                    raise ValueError("identity contains null values")
                keys.append((str(asset_id), int(frame_index)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{artifact_name} has invalid waveform frame identities",
                {
                    "integrity_reasons": [f"{artifact_name}_FRAME_IDENTITY_INVALID"],
                    "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
                },
            ) from exc
        if len(set(keys)) != len(keys):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{artifact_name} has duplicate waveform frame identities",
                {
                    "integrity_reasons": [f"{artifact_name}_FRAME_IDENTITY_DUPLICATE"],
                    "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
                },
            )
        return keys

    frame_keys = identities(frame_metadata, "WAVEFORM")
    event_keys = identities(events, "MEASUREMENT_EVENT")
    if set(frame_keys) != set(event_keys):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "waveform frames and MeasurementEvents do not identify the same frame set",
            {
                "integrity_reasons": ["FRAME_EVENT_IDENTITY_SET_MISMATCH"],
                "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            },
        )
    value_by_frame = dict(zip(frame_keys, values, strict=True))
    return np.asarray([value_by_frame[key] for key in event_keys], dtype=np.float64)


def _align_event_series_to_frame_metadata(
    events: pd.DataFrame,
    frame_metadata: pd.DataFrame,
    series: np.ndarray,
) -> np.ndarray:
    """Align an event-keyed series back to canonical waveform metadata order."""
    return _align_feature_series_to_event_frames(frame_metadata, events, series)


def _correlation_alignment_assessment(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    sync_path = (
        get_service(request).processed_root
        / "synchronization"
        / battery_id
        / experiment_id
        / "synchronization_manifest.json"
    )
    manifest = _read_json_local(sync_path) or {}
    validated_sync = manifest.get("validated_sync") is True
    status = (
        "VALIDATED"
        if validated_sync
        else "PROVISIONAL" if manifest else "UNKNOWN"
    )
    limitation = (
        "study protocol is not registered; association remains exploratory"
        if validated_sync
        else "acoustic/electrical absolute timebase is not validated; "
        "associations with electrical labels are exploratory and cannot support confirmatory claims"
    )
    return {
        "status": status,
        "validated_sync": validated_sync,
        "association_scope": "EXPLORATORY_ONLY",
        "confirmatory_inference_allowed": False,
        "limitation": limitation,
    }


def _experiment_analysis_plan_assessment(
    request: Request, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    service = get_service(request)
    return resolve_experiment_analysis_plan(
        service.raw_root, battery_id=battery_id, experiment_id=experiment_id
    )


def _declared_condition_analysis(
    request: Request,
    battery_id: str,
    experiment_id: str,
    feature_rows: list[FeatureStateRow],
) -> dict[str, Any]:
    """Read declared condition segments and return event-grain SOC slices."""
    service = get_service(request)
    # Condition intervals are user-maintained annotations, not immutable raw
    # manifests. Keep declarations outside raw while referenced evidence stays raw.
    manifest_path = (
        service.raw_root.parent
        / "annotations"
        / battery_id
        / experiment_id
        / "condition_segments.csv"
    )
    common = {
        "absolute_timebase_status": "NOT_ASSESSED",
        "synchronization_status": "NOT_ASSESSED",
    }
    if not manifest_path.is_file():
        return {
            **common,
            "status": "NOT_CONFIGURED",
            "declaration_status": "NOT_CONFIGURED",
            "segment_count": 0,
            "events_assessed": 0,
            "assignment_status_counts": {},
            "results": [],
            "limitations": [
                "no condition_segments.csv manifest; no condition-stratified SOC results are available"
            ],
        }

    events_path = (
        service.processed_root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_events.parquet"
    )
    if not events_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    assert_processed_artifact_integrity(
        service.processed_root,
        events_path.parent / "measurement_event_manifest.json",
        battery_id=battery_id,
        experiment_id=experiment_id,
        required_outputs={"events", "candidates"},
        required_inputs={"aligned", "sync_candidates", "electrical_records"},
        required_manifest_fields={"builder_version"},
        recovery_action="REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
    )

    try:
        assets_path = service.raw_root / "manifests" / "data_assets.csv"
        assets = load_data_assets(assets_path)
        segments = load_condition_segments(
            manifest_path,
            raw_root=service.raw_root,
            data_assets=assets,
        )
        event_frame = pd.read_parquet(events_path)
        identity_columns = {
            "measurement_event_id",
            "battery_id",
            "experiment_id",
            "ultrasound_asset_id",
            "frame_index_raw",
        }
        missing_identity_columns = sorted(identity_columns - set(event_frame.columns))
        if missing_identity_columns:
            raise ValueError(
                "canonical MeasurementEvent is missing identity columns: "
                f"{missing_identity_columns}"
            )
        event_ids = event_frame["measurement_event_id"]
        invalid_event_ids = event_ids.map(
            lambda value: not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        )
        if invalid_event_ids.any() or event_ids.duplicated().any():
            raise ValueError(
                "canonical MeasurementEvent measurement_event_id values must be "
                "non-empty, trimmed, and unique"
            )
        registered_ultrasound_assets = {
            (battery_id, experiment_id, asset.asset_id)
            for asset in assets
            if asset.modality == "ultrasound"
            and data_asset_matches(asset, battery_id, experiment_id)
        }
        for record in event_frame[
            [
                "measurement_event_id",
                "battery_id",
                "experiment_id",
                "ultrasound_asset_id",
                "frame_index_raw",
            ]
        ].to_dict(orient="records"):
            event_battery = record["battery_id"]
            event_experiment = record["experiment_id"]
            asset_id = record["ultrasound_asset_id"]
            raw_frame_index = record["frame_index_raw"]
            if (
                event_battery != battery_id
                or event_experiment != experiment_id
                or not isinstance(asset_id, str)
                or not asset_id.strip()
                or asset_id != asset_id.strip()
                or (event_battery, event_experiment, asset_id)
                not in registered_ultrasound_assets
            ):
                raise ValueError(
                    "canonical MeasurementEvent identity does not match its registered "
                    "Battery/Experiment/Ultrasound DataAsset"
                )
            if isinstance(raw_frame_index, bool):
                raise TypeError(
                    "canonical MeasurementEvent frame_index_raw must be an integer"
                )
            try:
                frame_index = int(raw_frame_index)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "canonical MeasurementEvent frame_index_raw must be an integer"
                ) from exc
            if frame_index < 0 or frame_index != raw_frame_index:
                raise ValueError("canonical MeasurementEvent frame_index_raw must be non-negative")
            expected_event_id = build_measurement_event_id(
                battery_id, experiment_id, asset_id, frame_index
            )
            if record["measurement_event_id"] != expected_event_id:
                raise ValueError(
                    "MeasurementEvent ID does not match its composite frame identity"
                )
        feature_event_ids = {row.measurement_event_id for row in feature_rows}
        canonical_event_ids = set(event_ids)
        unknown_feature_event_count = len(feature_event_ids - canonical_event_ids)
        if unknown_feature_event_count:
            raise ValueError(
                "feature rows reference unknown MeasurementEvent identities "
                f"(count={unknown_feature_event_count})"
            )
        event_frame = event_frame[
            event_frame["measurement_event_id"].astype(str).isin(feature_event_ids)
        ]
        events: list[CanonicalMeasurementEvent] = []
        for record in event_frame.to_dict(orient="records"):
            timestamp = record.get("provisional_absolute_timestamp")
            if pd_isna(timestamp):
                timestamp = None
            events.append(
                CanonicalMeasurementEvent.model_validate(
                    {
                        "measurement_event_id": str(record["measurement_event_id"]),
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "ultrasound_asset_id": str(record["ultrasound_asset_id"]),
                        "frame_index_raw": int(record["frame_index_raw"]),
                        "event_order_index": int(record["event_order_index"]),
                        "provisional_absolute_timestamp": timestamp,
                        "match_status": str(record["match_status"]),
                        "event_quality_status": str(record["event_quality_status"]),
                        "analysis_eligible": bool(record["analysis_eligible"]),
                    }
                )
            )
    except APIError:
        raise
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "condition segment evidence or canonical MeasurementEvent is invalid",
            {"reason": str(exc)},
        ) from exc

    assignments = assign_condition_segments_to_events(segments, events)
    status_counts = dict(sorted(Counter(item.status for item in assignments).items()))
    return {
        **common,
        "status": "AVAILABLE" if segments else "NO_SEGMENTS",
        "declaration_status": "OPERATOR_DECLARED" if segments else "NOT_APPLICABLE",
        "segment_count": len(segments),
        "events_assessed": len(events),
        "assignment_status_counts": status_counts,
        "results": [
            result.model_dump()
            for result in condition_stratified_soc(feature_rows, assignments)
        ],
        "limitations": [
            "condition values and intervals are OPERATOR_DECLARED, not independently verified",
            "absolute timebase and cross-modal synchronization remain NOT_ASSESSED",
            "descriptive associations only; no confidence interval or p-value is estimated",
        ],
    }


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
    ultrasound_asset_id: str | None = Query(default=None),
    frame_index_raw: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    import pandas as pd

    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    _assert_source_provenance(
        request, battery_id, experiment_id, modalities=("ultrasound",)
    )
    electrical_source_blocked = False
    try:
        _assert_source_provenance(
            request, battery_id, experiment_id, modalities=("electrical",)
        )
    except APIError:
        # Frame-local ultrasound features remain inspectable, but event-linked
        # canonical TOF is not attributable while electrical lineage is invalid.
        electrical_source_blocked = True
    gate_context = _experiment_gate_context(request, battery_id, experiment_id)
    bounds = gate_context["gate_bounds"]
    frame_meta_path = (
        get_service(request).processed_root
        / "ultrasound"
        / battery_id
        / experiment_id
        / "frames.parquet"
    )
    if not frame_meta_path.is_file():
        raise APIError(
            ErrorCode.ARTIFACT_NOT_AVAILABLE,
            "ultrasound frame metadata is not available; parse the registered Ultrasound DataAsset first",
            {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "recovery_action": "RUN_ULTRASOUND_PARSE",
            },
        )
    frame_meta = pd.read_parquet(
        frame_meta_path,
        columns=["ultrasound_asset_id", "frame_index_raw", "waveform_group", "waveform_row_index"],
    )
    if (ultrasound_asset_id is None) != (frame_index_raw is None):
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "ultrasound_asset_id and frame_index_raw must be provided together",
        )
    if ultrasound_asset_id is not None and frame_index_raw is not None:
        frame_meta = frame_meta[
            (frame_meta["ultrasound_asset_id"].astype(str) == ultrasound_asset_id)
            & (frame_meta["frame_index_raw"].astype("Int64") == frame_index_raw)
        ]
        if len(frame_meta) > 1:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "frame identity is duplicated within one Ultrasound DataAsset",
                {"ultrasound_asset_id": ultrasound_asset_id, "frame_index_raw": frame_index_raw},
            )
        if frame_meta.empty:
            raise APIError(ErrorCode.NOT_FOUND, "frame not found in Ultrasound DataAsset")
        store_path = frame_meta_path.parent / "waveforms.zarr"
        frames = load_waveform_frames(store_path, frame_meta)
    else:
        frame_meta = frame_meta.head(limit)
        frames = load_waveform_frames(
            frame_meta_path.parent / "waveforms.zarr", frame_meta
        )
    frame_locators = [
        {
            "ultrasound_asset_id": str(row.ultrasound_asset_id),
            "frame_index_raw": int(row.frame_index_raw),
        }
        for row in frame_meta.itertuples(index=False)
    ]
    _validate_experiment_gate_context(gate_context, frames)

    bottom = bottom_wave_amplitude(frames, bounds)
    swa = surface_wave_amplitude(frames, bounds)
    tof = surface_bottom_xcorr_tof(frames, bounds)
    atten = bottom_attenuation_explicit(frames, gate_bounds=bounds)
    bps = bottom_wave_phase_shift(frames, bounds)

    # canonical envelope-peak TOF block — read from the materialized artifact
    canonical_tof_block: dict[str, Any] | None = None
    canonical_tof_integrity_warning: dict[str, Any] | None = None
    ct_path = (
        get_service(request).processed_root
        / "features_physical"
        / battery_id
        / experiment_id
        / "canonical_tof.parquet"
    )
    if ct_path.is_file() and not electrical_source_blocked:
        import pandas as ct_pd
        try:
            assert_canonical_tof_integrity(
                get_service(request).processed_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
        except APIError as exc:
            canonical_tof_integrity_warning = {
                "integrity_reasons": exc.details.get("integrity_reasons", []),
                "recovery_action": exc.details.get("recovery_action"),
            }
        else:
            ct = ct_pd.read_parquet(
                ct_path, columns=["measurement_event_id", "tof_us", "tof_status"]
            )
            event_path = (
                get_service(request).processed_root
                / "multimodal"
                / battery_id
                / experiment_id
                / "measurement_events.parquet"
            )
            event_values: dict[tuple[str, int], float] = {}
            if event_path.is_file():
                event_meta = ct_pd.read_parquet(
                    event_path,
                    columns=["measurement_event_id", "ultrasound_asset_id", "frame_index_raw"],
                ).dropna(subset=["ultrasound_asset_id", "frame_index_raw"])
                valid_tof = ct[ct["tof_status"] == "VALID"].dropna(subset=["tof_us"])
                try:
                    joined_tof = event_meta.merge(
                        valid_tof,
                        on="measurement_event_id",
                        how="inner",
                        validate="one_to_one",
                    )
                except pd.errors.MergeError as exc:
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "canonical TOF must contain at most one row per MeasurementEvent",
                    ) from exc
                event_values = {
                    (str(row.ultrasound_asset_id), int(row.frame_index_raw)): float(row.tof_us)
                    for row in joined_tof.itertuples(index=False)
                }
            canonical_tof_block = {
                "feature_code": "tof_us",
                "method": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
                "gate_template_id": "TOF_SURFACE_PEAK_GATE→TOF_BOTTOM_PEAK_GATE",
                "display_name_en": "Canonical Envelope-Peak TOF",
                "display_name_zh": "规范包络峰TOF（表面→底波）",
                "unit": "µs",
                "values": [event_values.get((item["ultrasound_asset_id"], item["frame_index_raw"])) for item in frame_locators],
                "artifact_read_only": True,
            }
    elif not electrical_source_blocked and any(
        path.exists()
        for path in (
            ct_path,
            ct_path.with_name("canonical_tof_manifest.json"),
            ct_path.with_name("canonical_tof_audit.json"),
        )
    ):
        try:
            assert_canonical_tof_integrity(
                get_service(request).processed_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
        except APIError as exc:
            canonical_tof_integrity_warning = {
                "integrity_reasons": exc.details.get("integrity_reasons", []),
                "recovery_action": exc.details.get("recovery_action"),
            }

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
    if canonical_tof_block is not None:
        feature_blocks.insert(0, canonical_tof_block)
    for block in feature_blocks:
        block["frame_locators"] = frame_locators
    return {
        "data": {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "frame_count": len(frames),
            "features": feature_blocks,
        },
        "meta": {
            "source_formula_id": "USER_MATLAB_GATE_LOCAL_PHYSICAL_FEATURES_V1",
            "gate_calibration_id": gate_context["gate_calibration_id"],
            "note": "computed by deterministic backend modules; frontend never recomputes",
            "canonical_tof_status": (
                "BLOCKED_BY_ELECTRICAL_SOURCE_INTEGRITY"
                if electrical_source_blocked
                else "BLOCKED_BY_ARTIFACT_INTEGRITY"
                if canonical_tof_integrity_warning
                else "AVAILABLE" if canonical_tof_block is not None else "UNAVAILABLE"
            ),
            "source_integrity_warning": (
                "电学 parser provenance 无效；仍显示超声帧内特征，已隐藏依赖事件关联的 canonical TOF。"
                if electrical_source_blocked
                else None
            ),
            "canonical_tof_integrity_warning": canonical_tof_integrity_warning,
        },
    }


# ---------- feature–state correlations (backend module) ----------


@router.get(
    "/experiments/{battery_id}/{experiment_id}/feature-correlations",
    response_model=FeatureCorrelationsEnvelope,
)
def feature_correlations(
    request: Request,
    battery_id: str,
    experiment_id: str,
    feature_code: str = Query(default="SWA"),
    limit: int = Query(
        default=2000,
        ge=10,
        le=4000,
        description=(
            "Maximum event points in the diagnostic scatter plot. All joined events "
            "are used for correlation statistics regardless of this display limit."
        ),
    ),
) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    from battery_workbench.features.physical_v2 import bottom_wave_amplitude

    gate_context = _experiment_gate_context(request, battery_id, experiment_id)
    bounds = gate_context["gate_bounds"]
    frames = _load_frames(request, battery_id, experiment_id)
    _validate_experiment_gate_context(gate_context, frames)
    series_map: dict[str, np.ndarray] = {
        "SWA": surface_wave_amplitude(frames, bounds)["raw"],
        "BOTTOM_AMP": bottom_wave_amplitude(frames, bounds)["raw"],
    }
    if feature_code not in series_map:
        raise APIError(
            ErrorCode.NOT_FOUND,
            f"unknown feature_code {feature_code}; available: {sorted(series_map)}",
        )
    rows = _correlation_rows(
        request,
        battery_id,
        experiment_id,
        series_map[feature_code],
        feature_code,
        max_frames=None,
    )

    soc_suite = []
    for method in ("pearson", "spearman"):
        for scope in ("overall", "charge", "discharge", "rest"):
            scoped = rows if scope == "overall" else [r for r in rows if r.state == scope]
            r = correlate_feature_state(
                scoped,
                state_variable="reference_soc_percent",
                method=method,
                analysis_id=f"api:{feature_code}:{method}:{scope}",
                feature_code=feature_code,
                scope=scope,
            )
            soc_suite.append(r.model_dump())

    temp_result = correlate_feature_state(
        rows,
        state_variable="temperature_c",
        method="pearson",
        analysis_id=f"api:{feature_code}:temp",
        feature_code=feature_code,
    )
    temp = temp_result.model_dump()
    # A numerical coefficient is not evidence that the temperature channel is
    # a validated scientific target. Keep the descriptive value available, but
    # make the same calibration/location gate used by target readiness explicit.
    if temp_result.status == "VALID":
        temp["status"] = "BLOCKED_BY_VALIDATION"
        temp["limitations"].append(
            "temperature association is exploratory only: sensor location and "
            "calibration evidence are not verified; this is not an eligible "
            "temperature target"
        )
    soh = correlate_feature_state(
        rows,
        state_variable="soh_percent",
        method="pearson",
        analysis_id=f"api:{feature_code}:soh",
        feature_code=feature_code,
    ).model_dump()
    diagnostic = battery_scatter_diagnostic(
        rows, feature_code=feature_code, max_points=limit
    )
    return {
        "data": {
            "feature_code": feature_code,
            "n_events": len(rows),
            "soc": soc_suite,
            "soc_battery_decomposition": battery_decomposed_soc_correlation(rows),
            "soc_diagnostic_scatter": diagnostic,
            "soc_by_battery_condition": battery_condition_stratified_soc(
                rows, analysis_id=f"api:{feature_code}:battery", feature_code=feature_code
            ),
            "soc_by_cycle": [
                result.model_dump()
                for result in cycle_stratified_soc(
                    rows, analysis_id=f"api:{feature_code}:cycle", feature_code=feature_code
                )
            ],
            "soc_cycle_decomposition": cycle_decomposed_soc_correlation(rows),
            "alignment_assessment": _correlation_alignment_assessment(
                request, battery_id, experiment_id
            ),
            "declared_condition_analysis": _declared_condition_analysis(
                request, battery_id, experiment_id, rows
            ),
            "inference_assessment": exploratory_inference_assessment(
                correlation_results_included=True,
                study_protocol_assessment=_experiment_analysis_plan_assessment(
                    request, battery_id, experiment_id
                ),
            ),
            "temperature": temp,
            "soh": soh,
            "soh_cycle_summary": soh_cycle_summary(rows),
        },
        "meta": {
            "policy": CORRELATION_POLICY_ID,
            "policy_versions": CORRELATION_POLICY_VERSIONS,
            "analysis_scope": {
                "diagnostic_point_limit": limit,
                "analyzed_event_rows": len(rows),
                "diagnostic_points_returned": len(diagnostic["points"]),
                "join_key": "measurement_event_id",
                "coefficient_eligibility": "analysis_eligible=true",
                "analysis_mode": "EXPLORATORY",
            },
            "gate_calibration_id": gate_context["gate_calibration_id"],
            "note": "SOC/temperature associations use eligible MeasurementEvents; "
            "SOH associations use Battery/Experiment/Cycle summaries; no naive p-values; "
            "frontend never recomputes",
        },
    }


# ---------- gate calibration ----------


def _calibration_diagnostics(
    frames: np.ndarray,
    template_id: str,
    gate_bounds: dict[str, tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """Per-frame diagnostics: peak containment + edge hits inside the gate."""
    diagnostics = []
    for i, frame in enumerate(frames):
        start, end = resolve_gate_bounds(template_id, gate_bounds, sample_count=int(frame.shape[0]))
        gate = frame[start:end]
        env = np.abs(hilbert(gate))
        peak = int(np.argmax(env))
        # peak packet containment: fraction of envelope energy within the
        # central 80% of the gate (edge hits mean the packet is clipped)
        central = env[int(len(env) * 0.1) : int(len(env) * 0.9)]
        containment = float(np.sum(central**2) / max(np.sum(env**2), 1e-12))
        diagnostics.append(
            {
                "frame_index": i,
                "peak_sample_in_gate": start + peak,
                "peak_containment_fraction": round(containment, 4),
                "edge_hit": bool(peak < 2 or peak > len(gate) - 3),
            }
        )
    return diagnostics


def _tof_gate_diagnostics(frames: np.ndarray, start: int, end_exclusive: int) -> dict[str, Any]:
    """Envelope-peak diagnostics for one TOF gate over calibration frames."""
    peaks_global: list[int] = []
    peaks_local: list[int] = []
    amps: list[float] = []
    containments: list[float] = []
    edge_hits = 0
    width = end_exclusive - start
    for frame in frames:
        segment = frame[start:end_exclusive]
        env = np.abs(hilbert(segment))
        local = int(np.argmax(env))
        peaks_local.append(local)
        peaks_global.append(start + local)
        amps.append(float(env[local]))
        central = env[int(width * 0.1) : int(width * 0.9)]
        containments.append(round(float(np.sum(central**2) / max(np.sum(env**2), 1e-12)), 4))
        if local < 2 or local > width - 3:
            edge_hits += 1
    return {
        "gate_start": start,
        "gate_end_exclusive": end_exclusive,
        "peak_global_indices": peaks_global,
        "peak_local_indices": peaks_local,
        "peak_amplitudes_a_u": amps,
        "peak_containment_fractions": containments,
        "edge_hit_count": edge_hits,
        "spread_samples": int(max(peaks_global) - min(peaks_global)),
    }


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
    templates = [
        t.model_dump()
        for t in (
            get_gate_template("SWA_SURFACE_GATE"),
            get_gate_template("BOTTOM_AMPLITUDE_GATE"),
            get_gate_template("TOF_SURFACE_REFERENCE_GATE"),
            get_gate_template("TOF_BOTTOM_GATE"),
            get_gate_template("ATTENUATION_BOTTOM_GATE"),
        )
    ]
    # BRW-018R2: TOF surface/bottom gate peak diagnostics over the same
    # target-blind calibration frames (A-scan + envelope + per-gate peaks).
    from battery_workbench.features.gate_calibration import (
        SOURCE_TEMPLATE_FROZEN,
        resolve_gate_calibration,
        resolve_tof_gate_calibration,
    )

    service_for_resolve = get_service(request)
    generic_cal = resolve_gate_calibration(
        battery_id, experiment_id, service_for_resolve.processed_root
    )
    for entry in templates:
        entry["bounds_source"] = "SOURCE_TEMPLATE"
        if generic_cal:
            pair = (generic_cal["gate_bounds"] or {}).get(entry["gate_template_id"])
            if pair:
                entry["python_start"] = int(pair["start"])
                entry["python_end_exclusive"] = int(pair["end_exclusive"])
                entry["length_samples"] = int(pair["end_exclusive"]) - int(pair["start"])
                entry["bounds_source"] = "EXPERIMENT_FROZEN"
    tof_cal = resolve_tof_gate_calibration(
        battery_id, experiment_id, service_for_resolve.processed_root
    )
    tof_diagnostics = {
        "surface": _tof_gate_diagnostics(
            calibration_frames, int(tof_cal["surface_start"]), int(tof_cal["surface_end_exclusive"])
        ),
        "bottom": _tof_gate_diagnostics(
            calibration_frames, int(tof_cal["bottom_start"]), int(tof_cal["bottom_end_exclusive"])
        ),
    }
    swa_bounds = None
    if generic_cal and "SWA_SURFACE_GATE" in (generic_cal["gate_bounds"] or {}):
        pair = generic_cal["gate_bounds"]["SWA_SURFACE_GATE"]
        swa_bounds = {
            "SWA_SURFACE_GATE": (
                int(pair["start"]),
                int(pair["end_exclusive"]),
            )
        }
    return {
        "data": {
            "calibration_frame_ids": frame_ids,
            "frames": _frame_envelopes(frames, frame_ids),
            "gate_templates": templates,
            "diagnostics": _calibration_diagnostics(
                calibration_frames, "SWA_SURFACE_GATE", swa_bounds
            ),
            "tof_calibration": tof_cal | {"fallback_identity": SOURCE_TEMPLATE_FROZEN},
            "tof_gate_diagnostics": tof_diagnostics,
            "recommendation": "review peak containment and edge hits, then confirm",
            "generic_calibration": generic_cal,
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
    all_frames = _load_frames(request, battery_id, experiment_id)
    n_total = all_frames.shape[0]
    frame_ids = select_calibration_frames(n_total)

    # user-adjusted template bounds persisted with the freeze (empty = source
    # template bounds stay authoritative); unknown templates / bad ints reject
    raw_bounds = body.get("gate_bounds") or {}
    if not isinstance(raw_bounds, dict):
        raise APIError(ErrorCode.VALIDATION_ERROR, "gate_bounds must be an object")
    gate_bounds: dict[str, GateBoundPair] = {}
    for template_id, pair in raw_bounds.items():
        try:
            template = get_gate_template(str(template_id))
        except Exception as exc:
            raise APIError(
                ErrorCode.VALIDATION_ERROR, f"unknown gate template {template_id!r}"
            ) from exc
        try:
            start = int(pair["start"])
            end = int(pair["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "each gate bound must be {start, end} integers",
            ) from exc
        if start < 0 or end <= start or end > all_frames.shape[1]:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                f"invalid bounds for {template.gate_template_id}: "
                f"require 0<=start<end<={all_frames.shape[1]}",
            )
        gate_bounds[template.gate_template_id] = GateBoundPair(start=start, end_exclusive=end)
    bounds_key = ",".join(
        f"{k}:{v.start}:{v.end_exclusive}" for k, v in sorted(gate_bounds.items())
    )
    fingerprint = f"{battery_id}|{experiment_id}|{sorted(frame_ids)}|{basis}|{bounds_key}"
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
        gate_bounds=gate_bounds,
        confirmed_by=confirmed_by,
    ).freeze(confirmed_at=str(body.get("confirmed_at", "")))

    out_dir = service.processed_root / "gate_calibrations" / battery_id / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{calibration_id}.json"
    reused = out_path.is_file()
    if not reused:
        out_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return {
        "data": record.model_dump(mode="json")
        | {"reuse_status": "REUSED" if reused else "CREATED"},
        "meta": {},
    }


@router.post("/experiments/{battery_id}/{experiment_id}/tof-gate-calibration")
def freeze_tof_gate_calibration(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Freeze a per-experiment TOF surface/bottom calibration record (BRW-018R2).

    Immutable + versioned: identical identity inputs reuse the existing frozen
    record; any changed bound/basis freezes a NEW version (vN+1) linked to the
    prior id. Basis must be target-blind. Saves never silently fall back to
    the source template — failures raise.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    confirmed_by = str(body.get("confirmed_by", "user"))
    basis = str(body.get("calibration_basis", "PREDECLARED_PROTOCOL_GATE"))
    if basis in ("SOC_CORRELATION", "MODEL_SCORE", "HELD_OUT_RESIDUAL", "TARGET_OPTIMIZED"):
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "target-informed calibration basis is forbidden",
        )
    confirmed_at = str(body.get("confirmed_at", "")) or None
    surface = body.get("surface") or {}
    bottom = body.get("bottom") or {}
    if not surface or not bottom:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "surface and bottom gate bounds are required",
        )
    try:
        s_start, s_end = int(surface["start"]), int(surface["end"])
        b_start, b_end = int(bottom["start"]), int(bottom["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "gate bounds must be {start, end} integers",
        ) from exc

    service = get_service(request)
    frames = _load_frames(request, battery_id, experiment_id)
    n_total = frames.shape[0]
    frame_ids = select_calibration_frames(n_total)
    calibration_frames = frames[[int(i) for i in frame_ids]]

    surface_diag = _tof_gate_diagnostics(calibration_frames, s_start, s_end)
    bottom_diag = _tof_gate_diagnostics(calibration_frames, b_start, b_end)

    from battery_workbench.features.gate_calibration import (
        TOFGateCalibrationRecord,
        TOFPeakDiagnostics,
        resolve_tof_gate_calibration,
        tof_calibration_fingerprint,
        tof_calibration_id_from_fingerprint,
    )

    fingerprint = tof_calibration_fingerprint(
        battery_id=battery_id,
        experiment_id=experiment_id,
        frame_ids=list(frame_ids),
        surface_start=s_start,
        surface_end=s_end,
        bottom_start=b_start,
        bottom_end=b_end,
        basis=basis,
    )
    out_dir = service.processed_root / "gate_calibrations" / battery_id / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)

    prior = resolve_tof_gate_calibration(battery_id, experiment_id, service.processed_root)
    prior_version = int(prior.get("version", 0)) if prior["source"] == "EXPERIMENT_CONFIRMED" else 0

    # idempotent: an exact re-freeze of the latest record's identity → reuse it
    # (no version bump, no new id) — checked BEFORE any fingerprint versioning.
    if prior["source"] == "EXPERIMENT_CONFIRMED":
        same_identity = (
            prior["surface_start"] == s_start
            and prior["surface_end_exclusive"] == s_end
            and prior["bottom_start"] == b_start
            and prior["bottom_end_exclusive"] == b_end
        )
        if same_identity:
            calibration_id = prior["gate_calibration_id"]
            version = prior_version
            out_path = out_dir / f"{calibration_id}.json"
            return {
                "data": {
                    "gate_calibration_id": calibration_id,
                    "version": version,
                    "reuse_status": "REUSED",
                    "prior_gate_calibration_id": None,
                    "surface_diagnostics": surface_diag,
                    "bottom_diagnostics": bottom_diag,
                },
                "meta": {
                    "policy_id": "TOF_GATE_CALIBRATION_POLICY_V1",
                    "selection_basis": "PREDECLARED_PROTOCOL_GATE (deterministic, target-blind)",
                    "immutability": "identical identity → existing frozen record reused",
                },
            }

    # new version: changed bounds/basis freeze vN+1 linked to the prior record
    version = prior_version + 1
    calibration_id = tof_calibration_id_from_fingerprint(fingerprint, version)
    out_path = out_dir / f"{calibration_id}.json"

    reused = out_path.is_file()
    if not reused:
        record = TOFGateCalibrationRecord(
            gate_calibration_id=calibration_id,
            battery_id=battery_id,
            experiment_id=experiment_id,
            calibration_frame_ids=list(frame_ids),
            calibration_basis=basis,  # type: ignore[arg-type]
            surface_gate_id=str(body.get("surface_gate_id", "TOF_SURFACE_PEAK_GATE")),
            surface_start_sample=s_start,
            surface_end_sample_exclusive=s_end,
            bottom_gate_id=str(body.get("bottom_gate_id", "TOF_BOTTOM_PEAK_GATE")),
            bottom_start_sample=b_start,
            bottom_end_sample_exclusive=b_end,
            surface_diagnostics=TOFPeakDiagnostics(
                gate_id=str(body.get("surface_gate_id", "TOF_SURFACE_PEAK_GATE")),
                **{
                    k: surface_diag[k]
                    for k in (
                        "peak_global_indices",
                        "peak_local_indices",
                        "peak_amplitudes_a_u",
                        "peak_containment_fractions",
                        "edge_hit_count",
                        "spread_samples",
                    )
                },
            ),
            bottom_diagnostics=TOFPeakDiagnostics(
                gate_id=str(body.get("bottom_gate_id", "TOF_BOTTOM_PEAK_GATE")),
                **{
                    k: bottom_diag[k]
                    for k in (
                        "peak_global_indices",
                        "peak_local_indices",
                        "peak_amplitudes_a_u",
                        "peak_containment_fractions",
                        "edge_hit_count",
                        "spread_samples",
                    )
                },
            ),
            version=version,
            prior_gate_calibration_id=(
                prior["gate_calibration_id"]
                if prior["source"] == "EXPERIMENT_CONFIRMED" and version > 1
                else None
            ),
            confirmed_by=confirmed_by,
            notes=str(body.get("notes", "")),
        ).freeze(confirmed_at=confirmed_at or "user-confirmed")
        out_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return {
        "data": {
            "gate_calibration_id": calibration_id,
            "version": version,
            "reuse_status": "REUSED" if reused else "CREATED",
            "prior_gate_calibration_id": (
                prior["gate_calibration_id"] if prior["source"] == "EXPERIMENT_CONFIRMED" else None
            ),
            "surface_diagnostics": surface_diag,
            "bottom_diagnostics": bottom_diag,
        },
        "meta": {
            "policy_id": "TOF_GATE_CALIBRATION_POLICY_V1",
            "selection_basis": "PREDECLARED_PROTOCOL_GATE (deterministic, target-blind)",
            "immutability": "any bound/basis change freezes a new version; prior records remain",
        },
    }


# ---------- materialized splits (read-only list for ML-safe handoff) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/splits")
def list_splits(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    _assert_source_provenance(request, battery_id, experiment_id)
    service = get_service(request)
    root = service.processed_root / "splits" / battery_id / experiment_id
    items: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in sorted(root.rglob("split_manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            split_id = data.get("split_id", manifest.parent.name)
            assessment = service.get_artifact(str(split_id))
            items.append(
                {
                    "split_id": split_id,
                    "dataset_id": data.get("dataset_id"),
                    "strategy": data.get("strategy"),
                    "readiness_status": data.get("readiness_status"),
                    "availability": assessment.get("availability"),
                    "freshness_status": assessment.get("fields", {}).get("freshness_status"),
                    "status": assessment.get("status"),
                }
            )
    return {"data": {"splits": items}, "meta": {}}


@router.get("/experiments/{battery_id}/{experiment_id}/splits/{split_id}/folds")
def list_split_folds(
    request: Request, battery_id: str, experiment_id: str, split_id: str
) -> dict[str, Any]:
    """Read-only fold inventory of one grouped split (for ML-safe fold choice)."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    validate_id(split_id, "split_id")
    _assert_source_provenance(request, battery_id, experiment_id)
    service = get_service(request)
    root = service.processed_root / "splits" / battery_id / experiment_id
    sa_file = (
        next(root.rglob(f"{split_id}/split_assignments.parquet"), None) if root.is_dir() else None
    )
    if sa_file is None:
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, f"no split assignments for {split_id}")
    _require_current_split(request, split_id, purpose="fold inventory")
    import pandas as fold_pd

    sa = fold_pd.read_parquet(sa_file, columns=["fold", "role"])
    folds = []
    for fold in sorted(sa["fold"].astype(str).unique()):
        sub = sa[sa["fold"].astype(str) == fold]
        folds.append(
            {
                "fold": str(fold),
                "train_rows": int((sub["role"] == "TRAIN").sum()),
                "held_out_rows": int((sub["role"] != "TRAIN").sum()),
            }
        )
    manifest = next(root.rglob(f"{split_id}/split_manifest.json"), None)
    strategy = None
    if manifest is not None:
        try:
            strategy = json.loads(manifest.read_text(encoding="utf-8")).get("strategy")
        except (OSError, json.JSONDecodeError):
            pass
    return {"data": {"split_id": split_id, "strategy": strategy, "folds": folds}, "meta": {}}


# ---------- materialized feature analyses (read-only list) ----------


@router.get("/experiments/{battery_id}/{experiment_id}/feature-analyses")
def list_feature_analyses(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    _assert_source_provenance(request, battery_id, experiment_id)
    service = get_service(request)
    root = service.processed_root / "feature_analysis" / battery_id / experiment_id
    items: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in sorted(root.rglob("analysis_manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            analysis_id = data.get("analysis_id", manifest.parent.name)
            try:
                assessed = service.get_feature_analysis(analysis_id)
            except APIError:
                assessed = {
                    "status": "INTEGRITY_BLOCKED",
                    "availability": "BLOCKED",
                    "freshness_status": "INTEGRITY_BLOCKED",
                    "freshness_reasons": ["ANALYSIS_MANIFEST_INVALID"],
                }
            items.append(
                {
                    "analysis_id": analysis_id,
                    "analysis_mode": assessed.get("analysis_mode"),
                    "target": assessed.get("target"),
                    "split_id": assessed.get("split_id"),
                    "fold_index": assessed.get("fold_index"),
                    "dataset_id": assessed.get("dataset_id"),
                    "candidate_features": assessed.get("candidate_features", []),
                    "methods": assessed.get("methods", []),
                    "selected_features": assessed.get("selected_features", []),
                    "selection_basis": assessed.get("selection_basis"),
                    "selection_policy": assessed.get("selection_policy"),
                    "selection_policy_version": assessed.get("selection_policy_version"),
                    "selection_status": assessed.get("selection_status", "NOT_ASSESSED"),
                    "status": assessed.get("status", "INTEGRITY_BLOCKED"),
                    "availability": assessed.get("availability", "BLOCKED"),
                    "freshness_status": assessed.get("freshness_status", "INTEGRITY_BLOCKED"),
                    "freshness_reasons": assessed.get("freshness_reasons", []),
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
    return _merge_event_labels(events, labels)


def _optional_json_manifest(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            f"{label} manifest is unreadable",
            {"manifest": path.name},
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _alignment_events_joined(request: Request, battery_id: str, experiment_id: str):
    """Load canonical events for alignment QA, with labels only when available."""
    service = get_service(request)
    processed_root = service.processed_root
    assert_current_timebase_chain(
        processed_root,
        service.raw_root,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    experiment_dir = processed_root / "multimodal" / battery_id / experiment_id
    events_path = experiment_dir / "measurement_events.parquet"
    if not events_path.is_file():
        raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "measurement events not available")
    event_manifest_path = experiment_dir / "measurement_event_manifest.json"
    if not event_manifest_path.is_file():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "measurement event provenance is required before target analysis",
            {
                "integrity_reasons": ["MEASUREMENT_EVENT_MANIFEST_MISSING"],
                "recovery_action": "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
            },
        )
    assert_processed_artifact_integrity(
        processed_root,
        event_manifest_path,
        battery_id=battery_id,
        experiment_id=experiment_id,
        required_outputs={"events", "candidates"},
        required_inputs={"aligned", "sync_candidates", "electrical_records"},
    )

    import pandas as pd

    events = pd.read_parquet(events_path)
    labels_path = processed_root / "labels" / battery_id / experiment_id / "event_labels.parquet"
    if not labels_path.is_file():
        if (labels_path.parent / "label_manifest.json").exists():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "label manifest exists but event labels are missing",
                {
                    "integrity_reasons": ["LABEL_OUTPUT_MISSING:event_labels"],
                    "recovery_action": "REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
                },
            )
        return events, False
    label_manifest_path = labels_path.parent / "label_manifest.json"
    if not label_manifest_path.is_file():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "label provenance is required before target analysis",
            {
                "integrity_reasons": ["LABEL_MANIFEST_MISSING"],
                "recovery_action": "REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
            },
        )
    assert_processed_artifact_integrity(
        processed_root,
        label_manifest_path,
        battery_id=battery_id,
        experiment_id=experiment_id,
        required_outputs={"event_labels"},
        required_inputs={"measurement_events", "records", "cycles", "steps"},
        required_manifest_fields={"label_set_id"},
        recovery_action="REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
    )
    labels = pd.read_parquet(labels_path)
    return _merge_event_labels(events, labels), True


def _parser_source_assets(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    *,
    modalities: tuple[str, ...] = ("electrical", "ultrasound"),
):
    """Load parser-recorded source identity, keyed by DataAsset ID."""
    assets: dict[str, dict[str, dict[str, str]]] = {"electrical": {}, "ultrasound": {}}
    root = Path(processed_root).resolve()
    for modality in modalities:
        path = root / modality / battery_id / experiment_id / "parser_manifest.json"
        if not path.exists() and not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                raise TypeError("manifest path is not a file")
            manifest = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise TypeError("manifest root must be an object")
        except (OSError, RuntimeError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{modality} parser source manifest is invalid",
                {"manifest": path.name},
            ) from exc
        raw_hashes = manifest.get("source_sha256", {})
        if not isinstance(raw_hashes, dict):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{modality} parser source manifest has invalid source_sha256 mapping",
                {"manifest": path.name},
            )
        source_files: dict[str, str] = {}
        if modality == "electrical":
            details = manifest.get("source_asset_details", [])
            if not isinstance(details, list) or any(not isinstance(item, dict) for item in details):
                raise APIError(
                    ErrorCode.INTEGRITY_ERROR,
                    "electrical parser source manifest has invalid source_asset_details",
                    {"manifest": path.name},
                )
            source_files = {
                str(item["asset_id"]): str(item["relative_path"])
                for item in details
                if item.get("asset_id") and item.get("relative_path")
            }
        else:
            details = manifest.get("assets", [])
            if not isinstance(details, list) or any(not isinstance(item, dict) for item in details):
                raise APIError(
                    ErrorCode.INTEGRITY_ERROR,
                    "ultrasound parser source manifest has invalid assets list",
                    {"manifest": path.name},
                )
            source_files = {
                str(item["asset_id"]): str(item["source_file"])
                for item in details
                if item.get("asset_id") and item.get("source_file")
            }
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in value)
            for value in raw_hashes.values()
        ):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{modality} parser source manifest contains an invalid SHA-256",
                {"manifest": path.name},
            )
        assets[modality] = {
            str(asset_id): {
                "sha256": value,
                **(
                    {"source_file": source_files[str(asset_id)]}
                    if str(asset_id) in source_files
                    else {}
                ),
            }
            for asset_id, value in raw_hashes.items()
        }
    return assets


def _ultrasound_line_fallbacks(
    processed_root: Path, battery_id: str, experiment_id: str, rows: Any
) -> dict[tuple[str, int], int]:
    """Resolve unique raw TXT line locators from parsed frames for legacy events."""
    needed = {
        (str(row["ultrasound_asset_id"]), int(row["frame_index_raw"]))
        for _, row in rows.iterrows()
        if pd.notna(row.get("ultrasound_asset_id"))
        and pd.notna(row.get("frame_index_raw"))
        and pd.isna(row.get("source_line_index"))
    }
    if not needed:
        return {}
    frames_path = (
        processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    )
    if not frames_path.is_file():
        return {}
    frames = pd.read_parquet(frames_path)
    required = {"ultrasound_asset_id", "frame_index_raw", "source_line_index"}
    if not required.issubset(frames.columns):
        return {}
    frames = frames[["ultrasound_asset_id", "frame_index_raw", "source_line_index"]]
    frames = frames.dropna(subset=["ultrasound_asset_id", "frame_index_raw", "source_line_index"])
    frames["_asset_key"] = frames["ultrasound_asset_id"].astype(str)
    frames["_frame_key"] = frames["frame_index_raw"].astype(int)
    frame_keys = pd.MultiIndex.from_frame(frames[["_asset_key", "_frame_key"]])
    matches = frames[frame_keys.isin(needed)]
    counts = matches.groupby(["_asset_key", "_frame_key"])["source_line_index"].nunique()
    unique_keys = set(counts[counts == 1].index.tolist())
    matched_keys = pd.MultiIndex.from_frame(matches[["_asset_key", "_frame_key"]])
    return {
        (str(asset), int(frame)): int(line)
        for asset, frame, line in matches[
            matched_keys.isin(unique_keys)
        ][["_asset_key", "_frame_key", "source_line_index"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }


@router.get("/experiments/{battery_id}/{experiment_id}/targets")
def list_targets(request: Request, battery_id: str, experiment_id: str) -> dict[str, Any]:
    """Target definitions with source/coverage/readiness from canonical artifacts."""
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    _assert_source_provenance(request, battery_id, experiment_id)
    joined, labels_available = _alignment_events_joined(
        request, battery_id, experiment_id
    )
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
    temp_range = float(temp.max() - temp.min()) if temp is not None and temp.notna().any() else 0.0
    service = get_service(request)
    experiment_dir = service.processed_root / "labels" / battery_id / experiment_id
    label_manifest = _optional_json_manifest(
        experiment_dir / "label_manifest.json", "label provenance"
    )
    label_definitions = _optional_json_manifest(
        experiment_dir / "label_definitions.json", "label definition"
    )
    event_manifest = _optional_json_manifest(
        service.processed_root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_event_manifest.json",
        "measurement event provenance",
    )
    electrical_sources = _parser_source_assets(
        service.processed_root, battery_id, experiment_id
    )["electrical"]
    source_assets = [
        {
            "asset_id": asset_id,
            "source_reference": source.get("source_file"),
            "sha256": source["sha256"],
        }
        for asset_id, source in sorted(electrical_sources.items())
    ]
    observed_temperature_channels = sorted(
        str(value)
        for value in joined.get("temperature_channel_id", pd.Series(dtype=object)).dropna().unique()
    )

    definition_rows = label_definitions.get("labels", [])

    def _definition_for(names: set[str]) -> str | None:
        if not isinstance(definition_rows, list):
            return None
        items = [
            f"{item.get('name')}: {item.get('formula')}"
            for item in definition_rows
            if isinstance(item, dict)
            and item.get("name") in names
            and item.get("formula")
        ]
        return "; ".join(items) if items else None

    def _uncertainty_unknown(reason: str) -> dict[str, str]:
        return {"status": "UNKNOWN", "reason": reason}

    def _range(s: Any) -> list[float] | None:
        if s is None or not s.notna().any():
            return None
        return [float(s.min()), float(s.max())]

    soc_methods = (
        {str(k): int(v) for k, v in soc_method.value_counts().items()}
        if soc_method is not None
        else {}
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
                    "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED", 0
                ),
                "REST_PROPAGATED_FROM_PREVIOUS_VALID_REFERENCE": soc_methods.get(
                    "REST_PROPAGATED_FROM_PREVIOUS_VALID_REFERENCE", 0
                ),
            },
            "provenance": {
                "target_grain": "MEASUREMENT_EVENT",
                "independent_unit": "BATTERY",
                "method_id": label_manifest.get("soc_method"),
                "method_version": label_manifest.get("soc_formula_version"),
                "definition": _definition_for(
                    {
                        "soc_reference_percent_charge",
                        "soc_reference_percent_discharge",
                        "soc_reference_percent_rest",
                    }
                ),
                "source_assets": source_assets,
                "uncertainty": _uncertainty_unknown(
                    "The retrospective reference-label protocol does not provide a validated uncertainty estimate."
                ),
            },
            "coverage": {"valid": _count("soc_reference_percent"), "total": n},
            "range": _range(soc),
            "readiness": (
                "UNAVAILABLE"
                if not labels_available or _count("soc_reference_percent") == 0
                else "READY_FOR_LIMITED_EVALUATION"
            ),
            "limitation": (
                "no reference SOC labels are available for this experiment"
                if not labels_available or _count("soc_reference_percent") == 0
                else "Retrospective reference label, not a directly measured state of charge"
            ),
            "limitation_zh": (
                "当前没有参考 SOC 标签；确认电学记录后，运行标签生成流程。"
                if not labels_available or _count("soc_reference_percent") == 0
                else "回顾性参考标签 — 非真实 SOC"
            ),
            "unit": "percent",
        },
        {
            "target_id": "temperature_c",
            "display_name_en": "Temperature",
            "display_name_zh": "温度",
            "semantic_type": "DIRECT_MEASUREMENT",
            "source": "Electrical record temperature channel",
            "provenance": {
                "target_grain": "MEASUREMENT_EVENT",
                "independent_unit": "BATTERY",
                "method_id": "AUX_TEMP_RECORD_INDEX_JOIN",
                "method_version": event_manifest.get("builder_version"),
                "definition": (
                    "Electrical auxTemp readings are associated by "
                    "(electrical_asset_id, record_index_raw); no sensor location or "
                    "calibration is inferred."
                ),
                "source_assets": source_assets,
                "observed_channels": observed_temperature_channels,
                "uncertainty": _uncertainty_unknown(
                    "Sensor location and calibration evidence are not registered; measurement uncertainty is unknown."
                ),
            },
            "coverage": {"valid": _count("temperature_c"), "total": n},
            "range": _range(temp),
            "readiness": (
                "UNAVAILABLE"
                if _count("temperature_c") == 0
                else (
                    "INSUFFICIENT_VARIATION"
                    if temp_range < 2.0
                    else "BLOCKED_BY_VALIDATION"
                )
            ),
            "limitation": (
                "no temperature readings are linked to measurement events"
                if _count("temperature_c") == 0
                else (
                    "sensor location/calibration evidence is not verified; readings are not an eligible temperature modeling target"
                    if temp_range >= 2.0
                    else "observed temperature variation is below 2 °C"
                )
            ),
            "unit": "celsius",
        },
        {
            "target_id": "soh_capacity_reference_percent",
            "display_name_en": "SOH",
            "display_name_zh": "健康状态",
            "semantic_type": "DERIVED_HEALTH_STATE",
            "source": "Cycle-level capacity reference labels",
            "provenance": {
                "target_grain": "CYCLE",
                "independent_unit": "BATTERY",
                "method_id": label_manifest.get("soh_method"),
                "method_version": label_manifest.get("soh_formula_version"),
                "definition": _definition_for({"soh_capacity_reference_percent"}),
                "source_assets": source_assets,
                "uncertainty": _uncertainty_unknown(
                    "Capacity-test uncertainty and the reference-capacity measurement uncertainty are not characterized."
                ),
            },
            "coverage": {
                "valid": _count("soh_capacity_reference_percent"),
                "total": n,
                "independent_states": soh_states,
            },
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
    _assert_source_provenance(request, battery_id, experiment_id)
    joined, labels_available = _alignment_events_joined(request, battery_id, experiment_id)
    total = len(joined)
    matched_unique = int((joined["match_status"] == "MATCHED_UNIQUE").sum())
    ambiguous = int((joined["match_status"] == "MATCHED_AMBIGUOUS").sum())
    unmatched = int((~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])).sum())
    eligible = int(joined["analysis_eligible"].sum())

    def _valid(col: str) -> int:
        return (
            int(joined.loc[joined["analysis_eligible"], col].notna().sum())
            if col in joined.columns
            else 0
        )

    manifest_path = (
        get_service(request).processed_root
        / "synchronization"
        / battery_id
        / experiment_id
        / "synchronization_manifest.json"
    )
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    )
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
            "target_labels_available": labels_available,
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
    _assert_source_provenance(request, battery_id, experiment_id)
    joined, labels_available = _alignment_events_joined(request, battery_id, experiment_id)
    groups: list[dict[str, Any]] = []
    for reason, pred in _EXCLUSION_REASONS.items():
        mask = pred(joined)
        groups.append(
            {
                "reason": reason,
                "count": int(mask.sum()),
                "measurement_event_ids": joined.loc[mask, "measurement_event_id"].tolist(),
            }
        )
    groups.append({"reason": "TARGET_MISSING", "count": 0, "measurement_event_ids": []})
    return {
        "data": {"exclusions": groups},
        "meta": {
            "note": "ambiguous/unmatched rows never auto-select an electrical record",
            "target_labels_available": labels_available,
        },
    }


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
    _assert_source_provenance(request, battery_id, experiment_id)
    import pandas as row_pd

    joined, labels_available = _alignment_events_joined(request, battery_id, experiment_id)
    service = get_service(request)
    source_assets = _parser_source_assets(
        service.processed_root, battery_id, experiment_id
    )
    candidate_path = (
        service.processed_root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_event_candidates.parquet"
    )
    candidates_by_event: dict[str, list[dict[str, Any]]] = {}
    if candidate_path.is_file():
        candidate_frame = row_pd.read_parquet(candidate_path)
        for _, candidate in candidate_frame.iterrows():
            event_id = str(candidate.get("measurement_event_id", ""))
            if not event_id:
                continue
            asset_id = (
                str(candidate.get("electrical_asset_id"))
                if row_pd.notna(candidate.get("electrical_asset_id"))
                else None
            )
            source = source_assets["electrical"].get(asset_id or "", {})
            timestamp = candidate.get("electrical_timestamp")
            candidates_by_event.setdefault(event_id, []).append(
                {
                    "electrical_asset_id": asset_id,
                    "electrical_source_file": source.get("source_file"),
                    "electrical_source_sha256": source.get("sha256"),
                    "electrical_record_locator": str(candidate.get("electrical_record_locator"))
                    if row_pd.notna(candidate.get("electrical_record_locator"))
                    else None,
                    "electrical_row_index": int(candidate["electrical_row_index"])
                    if row_pd.notna(candidate.get("electrical_row_index"))
                    else None,
                    "electrical_timestamp": str(timestamp) if row_pd.notna(timestamp) else None,
                    "sync_error_s": float(candidate["sync_error_s"])
                    if row_pd.notna(candidate.get("sync_error_s"))
                    else None,
                    "signed_time_delta_s": float(candidate["signed_time_delta_s"])
                    if row_pd.notna(candidate.get("signed_time_delta_s"))
                    else None,
                    "candidate_timestamp_rank": int(candidate["candidate_timestamp_rank"]),
                    "candidate_record_rank": int(candidate["candidate_record_rank"]),
                    "electrical_timestamp_duplicate_count": int(
                        candidate["electrical_timestamp_duplicate_count"]
                    ),
                    "boundary_flag": bool(candidate.get("boundary_flag", False)),
                }
            )
    if filter == "eligible":
        rows = joined[joined["analysis_eligible"]]
    elif filter == "ambiguous":
        rows = joined[joined["match_status"] == "MATCHED_AMBIGUOUS"]
    elif filter == "unmatched":
        rows = joined[~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])]
    else:
        rows = joined
    rows = rows.iloc[cursor : cursor + limit]
    line_fallbacks = _ultrasound_line_fallbacks(
        service.processed_root, battery_id, experiment_id, rows
    )
    items = []
    for _, r in rows.iterrows():
        unique = r["match_status"] == "MATCHED_UNIQUE"
        ultrasound_asset_id = (
            str(r["ultrasound_asset_id"])
            if row_pd.notna(r.get("ultrasound_asset_id"))
            else None
        )
        electrical_asset_id = (
            str(r["electrical_asset_id"])
            if unique and row_pd.notna(r.get("electrical_asset_id"))
            else None
        )
        ultrasound_source = source_assets["ultrasound"].get(ultrasound_asset_id or "", {})
        electrical_source = source_assets["electrical"].get(electrical_asset_id or "", {})
        frame_index = (
            int(r["frame_index_raw"]) if row_pd.notna(r.get("frame_index_raw")) else None
        )
        event_id = str(r["measurement_event_id"])
        declared_candidate_count = (
            int(r["candidate_record_count"])
            if row_pd.notna(r.get("candidate_record_count"))
            else 0
        )
        event_candidates = candidates_by_event.get(event_id, [])
        has_candidate_rows = str(r["match_status"]) in {
            "MATCHED_AMBIGUOUS",
            "OUT_OF_TOLERANCE",
        }
        source_line_index = (
            int(r["source_line_index"])
            if row_pd.notna(r.get("source_line_index"))
            else line_fallbacks.get((ultrasound_asset_id or "", frame_index))
            if frame_index is not None
            else None
        )
        items.append(
            {
                "measurement_event_id": str(r["measurement_event_id"]),
                "frame_index_raw": frame_index,
                "ultrasound_asset_id": ultrasound_asset_id,
                "ultrasound_source_file": str(r["source_file"])
                if row_pd.notna(r.get("source_file"))
                else ultrasound_source.get("source_file"),
                "ultrasound_source_sha256": ultrasound_source.get("sha256"),
                "ultrasound_source_line_index": source_line_index,
                "ultrasound_timestamp": str(r["provisional_absolute_timestamp"])
                if row_pd.notna(r["provisional_absolute_timestamp"])
                else None,
                "electrical_asset_id": electrical_asset_id,
                "electrical_source_file": str(r["electrical_source_file"])
                if unique and row_pd.notna(r.get("electrical_source_file"))
                else electrical_source.get("source_file"),
                "electrical_source_sha256": electrical_source.get("sha256"),
                "electrical_record_locator": str(r["electrical_record_locator"])
                if unique and row_pd.notna(r["electrical_record_locator"])
                else None,
                "electrical_timestamp": str(r["electrical_timestamp"])
                if unique and row_pd.notna(r["electrical_timestamp"])
                else None,
                "match_status": str(r["match_status"]),
                "sync_ambiguous": bool(r["sync_ambiguous"]),
                "ambiguity_type": str(r["ambiguity_type"])
                if row_pd.notna(r.get("ambiguity_type"))
                else None,
                "candidate_timestamp_count": int(r["candidate_timestamp_count"])
                if row_pd.notna(r.get("candidate_timestamp_count"))
                else 0,
                "candidate_record_count": int(r["candidate_record_count"])
                if row_pd.notna(r.get("candidate_record_count"))
                else 0,
                "candidate_details_available": (
                    not has_candidate_rows
                    or (
                        declared_candidate_count > 0
                        and len(event_candidates) == declared_candidate_count
                    )
                ),
                "electrical_candidates": event_candidates
                if has_candidate_rows
                else [],
                "sync_error_s": float(r["sync_error_s"])
                if row_pd.notna(r["sync_error_s"])
                else None,
                "signed_time_delta_s": float(r["signed_time_delta_s"])
                if row_pd.notna(r.get("signed_time_delta_s"))
                else None,
                "within_tolerance": bool(r["within_tolerance"])
                if row_pd.notna(r["within_tolerance"])
                else None,
                "analysis_eligible": bool(r["analysis_eligible"]),
                "targets": {
                    "reference_soc_percent": None
                    if row_pd.isna(r.get("soc_reference_percent"))
                    else float(r["soc_reference_percent"]),
                    "temperature_c": None
                    if row_pd.isna(r.get("temperature_c"))
                    else float(r["temperature_c"]),
                    "soh_capacity_reference_percent": None
                    if row_pd.isna(r.get("soh_capacity_reference_percent"))
                    else float(r["soh_capacity_reference_percent"]),
                    "voltage_v": None if row_pd.isna(r["voltage_v"]) else float(r["voltage_v"]),
                    "current_a": None if row_pd.isna(r["current_a"]) else float(r["current_a"]),
                },
            }
        )
    total = int(
        len(joined)
        if filter == "all"
        else (joined[joined["analysis_eligible"]].shape[0] if filter == "eligible" else len(rows))
    )
    return {
        "data": {"samples": items, "total": total},
        "meta": {
            "filter": filter,
            "cursor": cursor,
            "limit": limit,
            "target_labels_available": labels_available,
        },
    }


# ---------------------------------------------------------------------------
# BRW-018R2 fix — shared feature-series resolver for the full catalogue.
#
# ranking/preview previously accepted only the 7 physical codes while the
# catalogue exposes 33 (19 TD + 14 FD) — selecting any TD/FD feature produced
# NOT_FOUND ("unknown features"). Both endpoints now resolve every catalogue
# code through the same deterministic formula layer (matlab_features +
# spectral_transform + raw/envelope + physical gates). No value is invented
# here; this is a series resolver, not a new science path.
# ---------------------------------------------------------------------------

_PREDEFINED_PHYSICAL_CODES = (
    "BOTTOM_AMP",
    "SWA",
    "TOF_XCORR",
    "ATTEN_MAX",
    "ATTEN_MEAN",
    "ATTEN_ENERGY",
    "BPS",
)


def _catalogue_feature_series(
    frames: np.ndarray,
    features: list[str],
    gate_bounds: dict[str, tuple[int, int]] | None = None,
) -> dict[str, np.ndarray]:
    """Series per requested feature code (catalogue codes + physical codes).

    TD codes run compute_time_domain over the full waveform; FD codes run the
    default explicit spectral transform (no fs requirement). Only codes the
    catalogue defines are accepted; unknown codes raise NOT_FOUND upstream.
    """
    return selected_feature_series(frames, features, gate_bounds=gate_bounds)


def _read_json_local(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@router.post("/experiments/{battery_id}/{experiment_id}/feature-label-preview")
def feature_label_preview(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Event-grain preview: selected ultrasound features + exactly one target.

    Read-only aggregation of canonical artifacts — no recomputation, no
    artifact writes (hash-stable).

    BRW-025R-FE-R2 additions (additive):
    - grain declared explicitly (one row = one eligible MeasurementEvent)
    - row provenance: electrical locator/row/timestamp + match status
    - ambiguous rows returned separately (electrical identity null, target
      unavailable — never auto-nearest)
    - split_id → TRAIN/HELD_OUT role awareness with BACKEND y redaction for
      HELD_OUT rows (target=null + y_redacted=true; not CSS hiding)
    - tof_provenance: SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 + current fs +
      GateCalibrationRecord (BRW-017R2/018R2); TOF_XCORR column stays the
      legacy diagnostic and is never canonical
    - feature_meta: bilingual labels + units + definition status per column
    - preview_state=PREVIEW_DRAFT + spec_hash + materialized dataset lookup
      with stale-TOF / refresh-required markers
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    target_id = str(body.get("target_id", "reference_soc_percent"))
    requested_features = body.get("features", [])
    if not isinstance(requested_features, list) or any(
        not isinstance(feature, str) for feature in requested_features
    ):
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "features must be an array of feature codes",
        )
    if len(requested_features) > 12:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "feature ranking accepts at most 12 feature codes; reduce the selection and retry",
            {"requested_count": len(requested_features), "maximum_count": 12},
        )
    features = [str(f) for f in requested_features]
    limit = min(int(body.get("limit", 50)), 500)
    split_id = str(body.get("split_id", ""))  # ML-safe review: role awareness
    fold_index = body.get("fold_index")  # fold-specific roles (LEAVE_ONE_GROUP_OUT has ≥2)
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
    gate_context = _experiment_gate_context(request, battery_id, experiment_id)
    gate_bounds = gate_context["gate_bounds"]
    _validate_experiment_gate_context(gate_context, frames)

    # BRW-018R2 fix: catalogue-wide resolution (7 physical codes + 33 TD/FD
    # codes + raw aliases). Unknown codes still raise NOT_FOUND — but only for
    # codes the catalogue genuinely does not define.
    from battery_workbench.features.definitions_v2 import default_registry

    physical_series = selected_feature_series(
        frames, list(_PREDEFINED_PHYSICAL_CODES), gate_bounds=gate_bounds
    )
    catalogue = default_registry()
    resolved_alias: dict[str, str] = {}
    unknown_features = []
    for f in features:
        if f in physical_series:
            continue
        if f in catalogue._defs:
            continue
        if f in _ALIAS_TO_RAW:
            resolved_alias[f] = _ALIAS_TO_RAW[f]
            continue
        if f == "tof_us":  # BRW-017R2 canonical artifact (read-only join)
            continue
        unknown_features.append(f)
    if unknown_features:
        raise APIError(ErrorCode.NOT_FOUND, f"unknown features: {unknown_features}")

    series_by_code: dict[str, np.ndarray] = dict(physical_series)
    series_by_code.update(_catalogue_feature_series(frames, features, gate_bounds))

    events, labels = _load_events_labels(request, battery_id, experiment_id)
    import pandas as join_pd

    joined = _merge_event_labels(events, labels)
    frame_metadata_path = (
        get_service(request).processed_root
        / "ultrasound"
        / battery_id
        / experiment_id
        / "frames.parquet"
    )
    try:
        frame_metadata = join_pd.read_parquet(
            frame_metadata_path, columns=["ultrasound_asset_id", "frame_index_raw"]
        )
    except (OSError, ValueError, KeyError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "waveform frame identity metadata is unavailable or invalid",
            {
                "integrity_reasons": ["WAVEFORM_FRAME_IDENTITY_METADATA_INVALID"],
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            },
        ) from exc
    series_by_code = {
        code: _align_feature_series_to_event_frames(joined, frame_metadata, values)
        for code, values in series_by_code.items()
    }
    n = len(joined)
    joined = joined.iloc[:n]

    # canonical envelope-peak TOF: served from the materialized artifact only
    # (SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1) — never recomputed here.
    if "tof_us" in features:
        ct_path = (
            get_service(request).processed_root
            / "features_physical"
            / battery_id
            / experiment_id
            / "canonical_tof.parquet"
        )
        if not ct_path.is_file():
            raise APIError(
                ErrorCode.NOT_FOUND,
                "canonical TOF artifact not materialized — run CANONICAL_TOF_FEATURES first",
            )
        assert_canonical_tof_integrity(
            get_service(request).processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
        ct = join_pd.read_parquet(
            ct_path, columns=["measurement_event_id", "tof_us", "tof_status"]
        )
        series_by_code["tof_us"] = np.asarray(
            canonical_tof_values_by_event(joined["measurement_event_id"].astype(str).tolist(), ct),
            dtype="float64",
        )

    tcol = target_cols[target_id]
    target_vals = joined[tcol]
    eligible_mask = joined["analysis_eligible"] & target_vals.notna()
    for f in features:
        eligible_mask = eligible_mask & join_pd.Series(
            np.isfinite(series_by_code[f][:n]), index=joined.index
        )

    # BRW-025R-FE-R2 — split role awareness (backend y redaction, not CSS)
    role_by_event: dict[str, dict[str, Any]] = {}
    redaction_summary: dict[str, Any] | None = None
    if split_id:
        validate_id(split_id, "split_id")
        sa_path = get_service(request).processed_root / "splits" / battery_id / experiment_id
        sa_file = (
            next(sa_path.rglob(f"{split_id}/split_assignments.parquet"), None)
            if sa_path.is_dir()
            else None
        )
        if sa_file is None:
            raise APIError(
                ErrorCode.NOT_FOUND,
                "split assignments not available for the requested split_id "
                "(ML-safe review requires an existing Grouped Split first)",
            )
        _require_current_split(request, split_id, purpose="held-out role-aware preview")
        sa = join_pd.read_parquet(sa_file, columns=["measurement_event_id", "role", "fold"])
        # LEAVE_ONE_GROUP_OUT has ≥2 folds with opposite roles per event — the
        # review is fold-specific: fold_index selects the fold (deterministic
        # default = smallest fold id); roles from other folds never leak.
        folds = sorted(sa["fold"].astype(str).unique())
        if not folds:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "split assignments do not contain any folds",
            )
        selected_fold = str(fold_index) if fold_index is not None else folds[0]
        if selected_fold not in folds:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                f"requested fold_index {selected_fold!r} is not present in the split assignments",
                {"available_folds": folds},
            )
        sa_f = sa[sa["fold"].astype(str) == selected_fold]
        if (
            sa_f["measurement_event_id"].isna().any()
            or sa_f["measurement_event_id"].duplicated().any()
        ):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "split assignments contain missing or duplicate MeasurementEvent identities",
            )
        invalid_roles = sorted(set(sa_f["role"].astype(str)) - {"TRAIN", "HELD_OUT"})
        if invalid_roles:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "split assignments contain unsupported roles",
                {"invalid_roles": invalid_roles},
            )
        role_by_event = {
            str(row.measurement_event_id): {"role": str(row.role), "fold": selected_fold}
            for row in sa_f.itertuples()
        }
        eligible_event_ids = set(
            joined.loc[eligible_mask, "measurement_event_id"].astype(str)
        )
        unassigned_event_ids = eligible_event_ids - set(role_by_event)
        if unassigned_event_ids:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "split assignments do not cover all eligible preview rows",
                {"unassigned_event_count": len(unassigned_event_ids)},
            )
        train_n = sum(1 for v in role_by_event.values() if v["role"] == "TRAIN")
        held_n = sum(1 for v in role_by_event.values() if v["role"] == "HELD_OUT")

    def _redact(event_id: str, target_value: float | None) -> tuple[float | None, bool]:
        """Backend y redaction: HELD_OUT rows lose y before serialization."""
        if not split_id:
            return target_value, False
        info = role_by_event.get(event_id)
        if info is None or info["role"] != "TRAIN":
            return None, True
        return target_value, False

    eligible_idx = joined.index[eligible_mask][:limit]
    rows = []
    for i in eligible_idx:
        r = joined.loc[i]
        event_id = str(r["measurement_event_id"])
        raw_target = None if join_pd.isna(r[tcol]) else float(r[tcol])
        target_value, y_redacted = _redact(event_id, raw_target)
        row: dict[str, Any] = {
            "measurement_event_id": event_id,
            "ultrasound_asset_id": str(r["ultrasound_asset_id"])
            if join_pd.notna(r.get("ultrasound_asset_id"))
            else None,
            "frame_index_raw": int(r["frame_index_raw"])
            if join_pd.notna(r["frame_index_raw"])
            else None,
            "cycle": int(r["cycle_index_raw"]) if join_pd.notna(r["cycle_index_raw"]) else None,
            "state": _STATE_MAP.get(str(r.get("step_type", "")), "rest"),
            "target": target_value,
            "values": {f: float(series_by_code[f][i]) for f in features},
            "sync_error_s": float(r["sync_error_s"]) if join_pd.notna(r["sync_error_s"]) else None,
            "electrical_asset_id": str(r["electrical_asset_id"])
            if join_pd.notna(r["electrical_asset_id"])
            else None,
            # BRW-025R-FE-R2 row provenance (frame→event→electrical locator→sync)
            "electrical_record_locator": (
                str(r["electrical_record_locator"])
                if join_pd.notna(r.get("electrical_record_locator"))
                else None
            ),
            "electrical_row_index": (
                int(r["electrical_row_index"])
                if join_pd.notna(r.get("electrical_row_index"))
                else None
            ),
            "electrical_timestamp": (
                str(r["electrical_timestamp"])
                if join_pd.notna(r.get("electrical_timestamp"))
                else None
            ),
            "match_status": str(r["match_status"])
            if join_pd.notna(r.get("match_status"))
            else None,
            "y_redacted": y_redacted,
        }
        if split_id:
            info = role_by_event.get(event_id)
            row["split_role"] = info["role"] if info else "UNASSIGNED"
            row["fold"] = info["fold"] if info else None
        rows.append(row)

    # ambiguous rows are inspectable but electrical identity/target stay null
    ambiguous_mask = joined["match_status"] == "MATCHED_AMBIGUOUS"
    ambiguous_rows = []
    for i in joined.index[ambiguous_mask][:10]:
        r = joined.loc[i]
        ambiguous_rows.append(
            {
                "measurement_event_id": str(r["measurement_event_id"]),
                "ultrasound_asset_id": str(r["ultrasound_asset_id"])
                if join_pd.notna(r.get("ultrasound_asset_id"))
                else None,
                "frame_index_raw": int(r["frame_index_raw"])
                if join_pd.notna(r["frame_index_raw"])
                else None,
                "state": _STATE_MAP.get(str(r.get("step_type", "")), "rest"),
                "electrical_identity": None,
                "target": None,
                "candidate_count": int(r["candidate_record_count"])
                if join_pd.notna(r.get("candidate_record_count"))
                else None,
                "values": {f: float(series_by_code[f][i]) for f in features},
                "note": "ambiguous sync — electrical identity null; target unavailable; never auto-nearest",
            }
        )

    excluded_by_reason: dict[str, int] = {
        "AMBIGUOUS_SYNC": int((joined["match_status"] == "MATCHED_AMBIGUOUS").sum()),
        "UNMATCHED_SYNC": int(
            (~joined["match_status"].isin(["MATCHED_UNIQUE", "MATCHED_AMBIGUOUS"])).sum()
        ),
        "TARGET_MISSING": int((joined["analysis_eligible"] & target_vals.isna()).sum()),
        "FEATURE_MISSING": int(
            n
            - eligible_mask.sum()
            - int((joined["analysis_eligible"] & target_vals.isna()).sum())
            - int((joined["match_status"] != "MATCHED_UNIQUE").sum())
        ),
        "ANALYSIS_INELIGIBLE": int((~joined["analysis_eligible"]).sum()),
    }
    target_meta = next(
        (
            t
            for t in list_targets(request, battery_id, experiment_id)["data"]["targets"]
            if t["target_id"] == target_id
        ),
        {},
    )

    # ------------------------------------------------------------------
    # BRW-025R-FE-R2 — preview hardening response block (additive)
    # ------------------------------------------------------------------
    from battery_workbench.features.definitions_v2 import default_registry as _dr
    from battery_workbench.features.gate_calibration import (
        resolve_tof_gate_calibration,
    )

    _catalogue = _dr()
    PHYSICAL_META: dict[str, dict[str, str]] = {
        "BOTTOM_AMP": {
            "label_en": "Bottom-wave Amplitude",
            "label_zh": "底波幅值",
            "units": "a.u.",
        },
        "SWA": {"label_en": "Surface Wave Amplitude", "label_zh": "表面波幅值", "units": "a.u."},
        "TOF_XCORR": {
            "label_en": "XCorr TOF (legacy diagnostic)",
            "label_zh": "互相关 TOF（诊断）",
            "units": "sample",
        },
        "ATTEN_MAX": {"label_en": "Attenuation max", "label_zh": "衰减最大", "units": "a.u."},
        "ATTEN_MEAN": {"label_en": "Attenuation mean", "label_zh": "衰减平均", "units": "a.u."},
        "ATTEN_ENERGY": {"label_en": "Attenuation energy", "label_zh": "衰减能量", "units": "a.u."},
        "BPS": {"label_en": "Bottom-wave Phase Shift", "label_zh": "底波相移", "units": "rad"},
    }
    feature_meta: dict[str, Any] = {}
    for f in features:
        if f in _catalogue._defs:
            d = _catalogue._defs[f]
            alias = d.existing_alias
            feature_meta[f] = {
                "label_en": d.display_name_en,
                "label_zh": d.display_name_zh,
                "units": d.units,
                "definition_status": str(d.definition_status),
                "parity_status": str(d.parity_status),
                "source": "catalogue",
                "resolved_name": alias if (alias and alias in _ALIAS_TO_RAW) else f,
            }
        elif f in PHYSICAL_META:
            feature_meta[f] = {
                **PHYSICAL_META[f],
                "definition_status": "DEFINED_AND_VALIDATED",
                "parity_status": "MATLAB_ALIGNED",
                "source": "physical",
            }
        elif f == "tof_us":
            feature_meta[f] = {
                "label_en": "Canonical Envelope-Peak TOF",
                "label_zh": "规范包络峰TOF（表面→底波）",
                "units": "µs",
                "definition_status": "DEFINED_AND_VALIDATED",
                "parity_status": "SYNTHETIC_GOLDEN_PASS",
                "source": "canonical_tof_artifact",
                "method": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
            }
        else:  # raw alias
            feature_meta[f] = {
                "label_en": f,
                "label_zh": {
                    "waveform_mean_a_u": "波形均值",
                    "waveform_std_a_u": "波形标准差",
                    "waveform_max_a_u": "波形最大",
                    "waveform_min_a_u": "波形最小",
                    "waveform_p2p_a_u": "波形峰峰差",
                }.get(f, f),
                "units": "a.u.",
                "definition_status": "DEFINED_AND_VALIDATED",
                "parity_status": "MATLAB_ALIGNED",
                "source": "raw_alias",
            }
        gate_templates = FEATURE_GATE_TEMPLATES.get(f)
        if gate_templates:
            feature_meta[f]["gate_templates"] = list(gate_templates)
            feature_meta[f]["gate_calibration_id"] = gate_context["gate_calibration_id"]
            feature_meta[f]["gate_bounds_source"] = (
                "EXPERIMENT_FROZEN" if gate_context["gate_calibration_id"] else "SOURCE_TEMPLATE"
            )

    # TOF provenance: canonical method + current fs + GateCalibrationRecord
    service_ro = get_service(request)
    cal = resolve_tof_gate_calibration(battery_id, experiment_id, service_ro.processed_root)
    fs_hz, fs_verified, fs_ps = _resolved_sampling_rate(
        service_ro.processed_root, battery_id, experiment_id
    )
    if "TOF_XCORR" in features:
        feature_meta["TOF_XCORR"]["canonical_note"] = (
            "TOF_XCORR 为诊断量；canonical TOF 是 "
            "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1（见 tof_provenance）"
        )
    tof_provenance = {
        "canonical_method": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
        "tof_definition_version": "0.3.0",
        "fs_hz": fs_hz,
        "fs_verified": fs_verified,
        "fs_parameter_set_id": fs_ps,
        "gate_calibration_id": cal["gate_calibration_id"],
        "gate_calibration_source": cal["source"],
        "gate_calibration_version": cal["version"],
        "surface_gate_id": cal["surface_gate_id"],
        "bottom_gate_id": cal["bottom_gate_id"],
        "note": "TOF 是特征而非目标；XCorr 仅诊断，不进入规范 tof_us",
    }

    # preview spec hash + materialized dataset lookup + stale TOF marker
    spec_payload = json.dumps(
        {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "target": target_id,
            "features": sorted(features),
            "split_id": split_id,
            "gate_calibration_id": gate_context["gate_calibration_id"],
            "spec_version": "preview/1.0",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    spec_hash = "PREVIEW::" + hashlib.sha256(spec_payload.encode()).hexdigest()[:24]
    materialized: dict[str, Any] | None = None
    family_dir = service_ro.processed_root / "datasets" / battery_id / experiment_id / "SOC"
    if family_dir.is_dir():
        for ds_dir in sorted(family_dir.glob("DS::*")):
            dm = _read_json_local(ds_dir / "dataset_manifest.json") or {}
            if (
                sorted(dm.get("selected_features") or []) == sorted(features)
                and dm.get("target_name") == tcol
            ):
                stale_tof = "tof_method_id" not in dm
                uses_frozen_gates = any(code in FEATURE_GATE_TEMPLATES for code in features)
                stale_gate = (
                    uses_frozen_gates
                    and bool(gate_context["gate_calibration_id"])
                    and (dm.get("gate_calibration_id") != gate_context["gate_calibration_id"])
                )
                materialized = {
                    "dataset_id": ds_dir.name,
                    "materialization_status": "MATERIALIZED_DATASET",
                    "stale_tof": stale_tof,
                    "stale_gate": stale_gate,
                    "refresh_required": stale_tof or stale_gate,
                    "stale_note": (
                        "dataset 使用的 frozen gate calibration 与当前 calibration 不同，需重建"
                        if stale_gate
                        else (
                            "dataset manifest 无 tof_method_id —— legacy TOF 数据集，"
                            "未含 canonical 包络峰值 TOF；refresh required"
                        )
                        if stale_tof
                        else "TOF and gate provenance current"
                    ),
                    "feature_definition_version": dm.get("target_method_version"),
                }
                break

    if split_id and role_by_event:
        redaction_summary = {
            "split_id": split_id,
            "fold": selected_fold,
            "train_rows": train_n,
            "held_out_rows": held_n,
            "policy": "HELD_OUT y redacted server-side before serialization "
            "(target=null + y_redacted=true); evaluation materialization "
            "restores y via the modeling layer only",
        }
    else:
        redaction_summary = None

    return {
        "data": {
            "target_id": target_id,
            "target_source": target_meta.get("source"),
            "target_readiness": target_meta.get("readiness"),
            "features": features,
            "feature_meta": feature_meta,
            "rows": rows,
            "ambiguous_rows": ambiguous_rows,
            "tof_provenance": tof_provenance,
            "gate_provenance": {
                "gate_calibration_id": gate_context["gate_calibration_id"],
                "bounds_source": "EXPERIMENT_FROZEN"
                if gate_context["gate_calibration_id"]
                else "SOURCE_TEMPLATE",
                "bounds": gate_bounds,
            },
            "preview_state": "PREVIEW_DRAFT",
            "spec_hash": spec_hash,
            "materialized_dataset": materialized,
            "redaction_summary": redaction_summary,
            "grain": "one row = one eligible MeasurementEvent (measurement_event_id exact join)",
            "summary": {
                "total_frames": n_frames,
                "aligned_events": n,
                "eligible_rows": int(eligible_mask.sum()),
                "excluded_rows": int(n - eligible_mask.sum()),
                "excluded_by_reason": excluded_by_reason,
                "cycles": sorted(
                    int(c)
                    for c in join_pd.unique(joined.loc[eligible_mask, "cycle_index_raw"].dropna())
                ),
                "missing_values": 0,
                "alignment_status": "PROVISIONAL_TIMEBASE_MATCHED",
            },
        },
        "meta": {
            "note": "read-only preview; one row = one eligible MeasurementEvent; "
            "PREVIEW_DRAFT ≠ MATERIALIZED_DATASET"
        },
    }


_RANK_UNAVAILABLE = {
    "TEMPERATURE_UNAVAILABLE",
    "ARTIFACT_MISSING",
    "NOT_READY_INSUFFICIENT_SOH_STATES",
}
_RANK_INSUFFICIENT = {"INSUFFICIENT_VARIATION", "INSUFFICIENT_OVERLAP", "NUMERICAL_NAN"}


def _rank_direction_status(
    status: str, charge: float | None, discharge: float | None, overall: float | None
) -> str:
    """§5 direction-aware descriptive classification (no new math).

    A charge/discharge sign flip with meaningful magnitudes is
    DIRECTION_DEPENDENT even when the overall coefficient cancels to ~0 —
    an offset overall value must never demote it to WEAK.
    """
    if status in _RANK_UNAVAILABLE:
        return "UNAVAILABLE"
    if status in _RANK_INSUFFICIENT:
        return "INSUFFICIENT_VARIATION"
    if (
        charge is not None
        and discharge is not None
        and charge * discharge < 0
        and min(abs(charge), abs(discharge)) >= 0.2
    ):
        return "DIRECTION_DEPENDENT"
    best = (
        max(abs(v) for v in (overall, charge, discharge) if v is not None)
        if any(v is not None for v in (overall, charge, discharge))
        else 0.0
    )
    if best < 0.1:
        return "WEAK_ASSOCIATION"
    return "SAME_DIRECTION"


_RANK_PHYSICAL_META: dict[str, dict[str, str]] = {
    "BOTTOM_AMP": {
        "label_zh": "底波幅值",
        "label_en": "Bottom-wave Amplitude",
        "family": "PHYSICAL",
        "units": "a.u.",
    },
    "SWA": {
        "label_zh": "表面波幅值",
        "label_en": "Surface Wave Amplitude",
        "family": "PHYSICAL",
        "units": "a.u.",
    },
    "TOF_XCORR": {
        "label_zh": "表面波-底波互相关TOF（诊断）",
        "label_en": "Surface–Bottom XCorr TOF (diagnostic)",
        "family": "PHYSICAL_DIAGNOSTIC",
        "units": "samples",
    },
    "ATTEN_MAX": {
        "label_zh": "底波衰减（最大）",
        "label_en": "Bottom Attenuation (max)",
        "family": "PHYSICAL",
        "units": "a.u.",
    },
    "ATTEN_MEAN": {
        "label_zh": "底波衰减（均值）",
        "label_en": "Bottom Attenuation (mean)",
        "family": "PHYSICAL",
        "units": "a.u.",
    },
    "ATTEN_ENERGY": {
        "label_zh": "底波衰减（能量）",
        "label_en": "Bottom Attenuation (energy)",
        "family": "PHYSICAL",
        "units": "a.u.",
    },
    "BPS": {
        "label_zh": "底波相移",
        "label_en": "Bottom-wave Phase Shift",
        "family": "PHYSICAL",
        "units": "radian",
    },
}


@router.post("/experiments/{battery_id}/{experiment_id}/feature-target-ranking")
def feature_target_ranking(
    request: Request, battery_id: str, experiment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """BRW-021R2 — descriptive feature × target ranking.

    Exploratory mode uses all eligible MeasurementEvents and is explicitly
    Not ML-safe. TRAIN_ONLY_ML_SAFE requires a Grouped Split and restricts
    the correlation input STRUCTURALLY to that fold's TRAIN rows — held-out
    targets are never loaded into the analysis input. Ranking describes
    statistical association only: no best / causal / predictive guarantee.

    ``features`` must contain at most 12 string codes. Larger requests are
    rejected rather than silently truncated, so every accepted candidate is
    included in the returned ranking (except explicitly blocked/deduplicated
    aliases).
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    target_id = str(body.get("target_id", "reference_soc_percent"))
    requested_features = body.get("features", [])
    if not isinstance(requested_features, list) or any(
        not isinstance(feature, str) for feature in requested_features
    ):
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "features must be an array of feature codes",
        )
    if len(requested_features) > 12:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "feature ranking accepts at most 12 feature codes; reduce the selection and retry",
            {"requested_count": len(requested_features), "maximum_count": 12},
        )
    features = list(requested_features)
    mode = "TRAIN_ONLY_ML_SAFE" if body.get("mode") == "TRAIN_ONLY_ML_SAFE" else "EXPLORATORY"
    split_id = str(body.get("split_id") or "")
    fold_index = str(body.get("fold_index") or "")
    variant = str(body.get("variant") or "RAW")
    detail_feature = str(body.get("detail_feature") or "")
    if not features:
        raise APIError(ErrorCode.VALIDATION_ERROR, "features required")
    if variant in ("SOURCE_MOVMEAN5", "MOVMEAN_5_SOURCE_ORDER") and mode == "TRAIN_ONLY_ML_SAFE":
        raise APIError(
            ErrorCode.SCIENTIFIC_ACTION_REQUIRED,
            "SOURCE_MOVMEAN5 平滑窗口可跨 cycle 边界 — 不可作为 ML-safe 正式排名/提交"
            "（SOURCE_MOVMEAN5_EXPLORATORY_POLICY_V1）",
        )

    from battery_workbench.datasets.roles import ColumnRole, get_column_role
    from battery_workbench.features.definitions_v2 import default_registry

    catalogue = default_registry()
    known_codes = (
        set(_PREDEFINED_PHYSICAL_CODES) | set(catalogue._defs) | set(_ALIAS_TO_RAW) | {"tof_us"}
    )
    # §25 forbidden predictors: recognized and formally BLOCKED (no numbers),
    # not silently rejected as unknown — the block itself is the answer.
    blocked = [f for f in features if get_column_role(f) == ColumnRole.FORBIDDEN_PREDICTOR]
    missing = [f for f in features if f not in known_codes and f not in blocked]
    if missing:
        raise APIError(ErrorCode.NOT_FOUND, f"unknown features: {missing}")

    # §24 alias dedup: amplitude_a_u ≡ waveform_abs_peak_a_u — one row only
    alias_dedup: list[dict[str, str]] = []
    kept: list[str] = []
    seen_series: dict[str, str] = {}
    for f in features:
        raw = "waveform_abs_peak_a_u" if f == "amplitude_a_u" else _ALIAS_TO_RAW.get(f, f)
        if raw in seen_series:
            alias_dedup.append(
                {"dropped": f, "kept": seen_series[raw], "reason": "same underlying series (alias)"}
            )
            continue
        seen_series[raw] = f
        kept.append(f)
    features = kept

    features = [f for f in features if f not in blocked]

    frames = _load_frames(request, battery_id, experiment_id)
    gate_context = _experiment_gate_context(request, battery_id, experiment_id)
    gate_bounds = gate_context["gate_bounds"]
    _validate_experiment_gate_context(gate_context, frames)
    series_map: dict[str, np.ndarray] = {
        code: selected_feature_series(frames, [code], gate_bounds=gate_bounds)[code]
        for code in _PREDEFINED_PHYSICAL_CODES
    }
    series_map.update(_catalogue_feature_series(frames, features, gate_bounds))

    # canonical envelope-peak TOF: read-only from the materialized artifact
    tof_provenance: dict[str, Any] | None = None
    tof_refresh_required = False
    if "tof_us" in features:
        ct_path = (
            get_service(request).processed_root
            / "features_physical"
            / battery_id
            / experiment_id
            / "canonical_tof.parquet"
        )
        if not ct_path.is_file():
            raise APIError(
                ErrorCode.ARTIFACT_NOT_AVAILABLE,
                "RELATIONSHIP_ARTIFACT_MISSING: canonical TOF artifact not materialized",
            )
        assert_canonical_tof_integrity(
            get_service(request).processed_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
        import pandas as ct_pd

        events_t, _ = _load_events_labels(request, battery_id, experiment_id)
        ct = ct_pd.read_parquet(
            ct_path,
            columns=["measurement_event_id", "tof_us", "tof_status", "gate_calibration_id"],
        )
        frame_metadata_path = (
            get_service(request).processed_root
            / "ultrasound"
            / battery_id
            / experiment_id
            / "frames.parquet"
        )
        try:
            frame_metadata = ct_pd.read_parquet(
                frame_metadata_path,
                columns=["ultrasound_asset_id", "frame_index_raw"],
            )
        except (OSError, ValueError, KeyError) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "waveform frame identity metadata is unavailable or invalid",
                {
                    "integrity_reasons": ["WAVEFORM_FRAME_IDENTITY_METADATA_INVALID"],
                    "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                },
            ) from exc
        event_tof = np.asarray(
            canonical_tof_values_by_event(
                events_t["measurement_event_id"].astype(str).tolist(), ct
            ),
            dtype="float64",
        )
        series_map["tof_us"] = _align_event_series_to_frame_metadata(
            events_t, frame_metadata, event_tof
        )
        cm = _read_json_local(ct_path.parent / "canonical_tof_manifest.json") or {}
        from battery_workbench.features.gate_calibration import resolve_tof_gate_calibration

        cal = resolve_tof_gate_calibration(
            battery_id, experiment_id, get_service(request).processed_root
        )
        # Values are only as current as the GateCalibrationRecord embedded in
        # the artifact; the newest confirmed record is reported separately.
        embedded_ids = sorted({str(v) for v in ct["gate_calibration_id"].unique()})
        embedded_id = embedded_ids[0] if len(embedded_ids) == 1 else None
        gc_dir = (
            get_service(request).processed_root / "gate_calibrations" / battery_id / experiment_id
        )
        emb_record = _read_json_local(gc_dir / f"{embedded_id}.json") if embedded_id else None
        window_matches = emb_record is not None and all(
            emb_record.get(k) == cal.get(key)
            for k, key in (
                ("surface_gate_id", "surface_gate_id"),
                ("bottom_gate_id", "bottom_gate_id"),
                ("surface_start_sample", "surface_start"),
                ("surface_end_sample_exclusive", "surface_end_exclusive"),
                ("bottom_start_sample", "bottom_start"),
                ("bottom_end_sample_exclusive", "bottom_end_exclusive"),
            )
        )
        sampling_rate_matches = _canonical_tof_sampling_rate_matches(
            cm,
            _resolved_sampling_rate(
                get_service(request).processed_root, battery_id, experiment_id
            ),
        )
        tof_refresh_required = not window_matches or not sampling_rate_matches
        tof_provenance = {
            "tof_method_id": cm.get("tof_method_id"),
            "tof_definition_version": cm.get("tof_definition_version"),
            "sampling_rate_hz": cm.get("sampling_rate_hz"),
            "sampling_rate_verified": cm.get("sampling_rate_verified"),
            "parameter_set_id": cm.get("parameter_set_id"),
            "gate_calibration_id": embedded_id or "（artifact 内闸门记录不一致/缺失）",
            "gate_calibration_source": cal["source"],
            "current_gate_calibration_id": cal["gate_calibration_id"],
            "current_gate_calibration_version": cal["version"],
            "gate_calibration_window_matches_current": window_matches,
            "gate_calibration_refresh_required": not window_matches,
            "sampling_rate_parameter_set_matches_current": sampling_rate_matches,
            "sampling_rate_refresh_required": not sampling_rate_matches,
            "waveform_valid_rows": cm.get("canonical_tof_valid"),
            "note": "XCorr 为诊断量，不替代 canonical tof_us",
        }

    # §12/§16 ML-safe structural gate: TRAIN membership decided BEFORE any
    # correlation input is built; held-out y never reaches the suite.
    train_ids: set[str] | None = None
    if mode == "TRAIN_ONLY_ML_SAFE":
        if target_id != "reference_soc_percent":
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "TRAIN_ONLY_ML_SAFE ranking is defined for the grouped-Split SOC target",
            )
        if not split_id or not fold_index:
            # leave-one-group-out: the union of all folds' TRAIN rows is the
            # full dataset — a fold restriction is structural, not cosmetic.
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "INVALID_SPLIT: TRAIN_ONLY_ML_SAFE ranking requires split_id and fold_index (Grouped Split)",
            )
        sa_path = get_service(request).processed_root / "splits" / battery_id / experiment_id
        sa_file = (
            next(sa_path.rglob(f"{split_id}/split_assignments.parquet"), None)
            if sa_path.is_dir()
            else None
        )
        if sa_file is None:
            raise APIError(
                ErrorCode.ARTIFACT_NOT_AVAILABLE,
                f"INVALID_SPLIT: no split assignments for {split_id}",
            )
        _require_current_split(request, split_id, purpose="TRAIN_ONLY_ML_SAFE ranking")
        import pandas as sa_pd

        try:
            sa = sa_pd.read_parquet(
                sa_file, columns=["measurement_event_id", "role", "fold"]
            )
        except (OSError, KeyError, ValueError) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "INVALID_SPLIT: split assignments are unreadable or missing required columns",
            ) from exc
        if sa.empty or sa[["measurement_event_id", "role", "fold"]].isna().any().any():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "INVALID_SPLIT: split assignments contain no rows or null required values",
            )
        invalid_roles = sorted(
            set(sa["role"].astype(str)) - {"TRAIN", "HELD_OUT", "VALIDATION", "TEST"}
        )
        if invalid_roles:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "INVALID_SPLIT: split assignments contain unsupported roles",
                {"invalid_roles": invalid_roles},
            )
        available_folds = sorted(sa["fold"].astype(str).unique())
        if fold_index not in available_folds:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                f"INVALID_SPLIT: requested fold_index {fold_index!r} is not present",
                {"available_folds": available_folds},
            )
        sa = sa[sa["fold"].astype(str) == fold_index]
        if sa["measurement_event_id"].astype(str).duplicated().any():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "INVALID_SPLIT: selected fold contains duplicate MeasurementEvent identities",
            )
        if not (sa["role"] == "TRAIN").any():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "INVALID_SPLIT: selected fold contains no TRAIN rows",
            )
        train_ids = set(sa[sa["role"] == "TRAIN"]["measurement_event_id"].astype(str))

    def _rows_for(code: str):
        rows = _correlation_rows(
            request,
            battery_id,
            experiment_id,
            series_map[code],
            code,
            max_frames=len(frames),
        )
        if train_ids is not None:
            rows = [r for r in rows if r.measurement_event_id in train_ids]
        return rows

    def _meta_for(code: str) -> dict[str, Any]:
        if code in _RANK_PHYSICAL_META:
            meta = dict(_RANK_PHYSICAL_META[code])
        elif code == "tof_us":
            return {
                "label_zh": "规范包络峰TOF（表面→底波）",
                "label_en": "Canonical Envelope-Peak TOF",
                "family": "CANONICAL_TOF",
                "units": "µs",
            }
        else:
            d = catalogue._defs.get(code)
            if d is not None:
                meta = {
                    "label_zh": getattr(d, "display_name_zh", code),
                    "label_en": getattr(d, "display_name_en", code),
                    "family": getattr(d, "family", "TD"),
                    "units": getattr(d, "units", "a.u."),
                }
            else:
                meta = {"label_zh": code, "label_en": code, "family": "RAW_ALIAS", "units": "a.u."}
        required_gates = FEATURE_GATE_TEMPLATES.get(code)
        if required_gates:
            meta["gate_templates"] = list(required_gates)
            meta["gate_calibration_id"] = gate_context["gate_calibration_id"]
            meta["gate_bounds_source"] = (
                "EXPERIMENT_FROZEN" if gate_context["gate_calibration_id"] else "SOURCE_TEMPLATE"
            )
        return meta

    # direct-measurement targets: overall + honest scope note (no fake split stats)
    if target_id in ("voltage_v", "current_a"):
        joined = _events_labels_joined(request, battery_id, experiment_id)
        frame_metadata_path = (
            get_service(request).processed_root
            / "ultrasound"
            / battery_id
            / experiment_id
            / "frames.parquet"
        )
        try:
            frame_metadata = pd.read_parquet(
                frame_metadata_path,
                columns=["ultrasound_asset_id", "frame_index_raw"],
            )
        except (OSError, ValueError, KeyError) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "waveform frame identity metadata is unavailable or invalid",
                {
                    "integrity_reasons": ["WAVEFORM_FRAME_IDENTITY_METADATA_INVALID"],
                    "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                },
            ) from exc
        n = len(joined)
        results: list[dict[str, Any]] = []
        from battery_workbench.features.state_correlation import _pearson, _spearman

        for code in features:
            series = _align_feature_series_to_event_frames(
                joined, frame_metadata, series_map[code]
            )
            vals = joined[target_id]
            ok = joined["analysis_eligible"] & vals.notna() & np.isfinite(series)
            x, y = series[ok.to_numpy()], vals[ok].to_numpy(dtype=float)
            p = s = None
            if x.size >= 3 and np.std(x) > 0 and np.std(y) > 0:
                p, s = _pearson(x, y), _spearman(x, y)
            status = "VALID" if p is not None else "INSUFFICIENT_OVERLAP"
            results.append(
                {
                    "feature_code": code,
                    **_meta_for(code),
                    "pearson_overall": p,
                    "spearman_overall": s,
                    "pearson_charge": None,
                    "pearson_discharge": None,
                    "spearman_charge": None,
                    "spearman_discharge": None,
                    "n_valid": int(x.size),
                    "n_missing": int(n - x.size),
                    "status": status,
                    "direction_status": _rank_direction_status(status, None, None, s),
                    "direction_dependent": False,
                    "scope_note": "state-stratified metrics not reported for direct targets",
                    "freshness": (
                        "REFRESH_REQUIRED"
                        if (code == "tof_us" and tof_refresh_required)
                        else "CURRENT"
                    ),
                    "commit_eligible": not (code == "tof_us" and tof_refresh_required),
                }
            )
        return _rank_response(
            mode,
            target_id,
            split_id,
            fold_index,
            results,
            alias_dedup,
            blocked,
            tof_provenance,
            None,
            request,
            battery_id,
            experiment_id,
        )

    if target_id == "soh_capacity_reference_percent":
        summary = soh_cycle_summary(_rows_for(features[0])) if features else []
        return _rank_response(
            mode,
            target_id,
            split_id,
            fold_index,
            [],
            alias_dedup,
            blocked,
            tof_provenance,
            {
                "group_summary": summary,
                "note": "SOH is cycle-level; frame-level ranking is not reported",
            },
            request,
            battery_id,
            experiment_id,
        )

    if target_id == "temperature_c":
        ranking_t: list[dict[str, Any]] = []
        readiness_rows = _rows_for(features[0])
        linked_temperature = [
            float(row.temperature_c)
            for row in readiness_rows
            if row.analysis_eligible and row.temperature_c is not None
        ]
        if not linked_temperature:
            target_readiness = "UNAVAILABLE"
            target_limitation = "no temperature readings are linked to eligible measurement events"
        elif max(linked_temperature) - min(linked_temperature) < 2.0:
            target_readiness = "INSUFFICIENT_VARIATION"
            target_limitation = "observed temperature variation is below 2 °C"
        else:
            target_readiness = "BLOCKED_BY_VALIDATION"
            target_limitation = (
                "temperature values may be inspected exploratorily, but sensor location and "
                "calibration evidence are not verified; this target cannot be handed off for modeling"
            )
        for code in features:
            frows = _rows_for(code)
            r = correlate_feature_state(
                frows,
                state_variable="temperature_c",
                method="pearson",
                analysis_id=f"rank:{code}",
                feature_code=code,
            )
            rs = correlate_feature_state(
                frows,
                state_variable="temperature_c",
                method="spearman",
                analysis_id=f"rank:{code}:sp",
                feature_code=code,
            )
            ranking_t.append(
                {
                    "feature_code": code,
                    **_meta_for(code),
                    "pearson_overall": r.coefficient,
                    "spearman_overall": rs.coefficient,
                    "pearson_charge": None,
                    "pearson_discharge": None,
                    "spearman_charge": None,
                    "spearman_discharge": None,
                    "n_valid": r.n_valid,
                    "n_missing": r.missing_feature_count + r.missing_state_count,
                    "status": r.status,
                    "target_readiness": target_readiness,
                    "direction_status": _rank_direction_status(
                        r.status, None, None, rs.coefficient
                    ),
                    "direction_dependent": False,
                    "freshness": (
                        "REFRESH_REQUIRED"
                        if (code == "tof_us" and tof_refresh_required)
                        else "CURRENT"
                    ),
                    "commit_eligible": (
                        r.status == "VALID"
                        and target_readiness == "READY"
                        and not (code == "tof_us" and tof_refresh_required)
                    ),
                    "exploratory_only": target_readiness != "READY",
                    "note": target_limitation,
                }
            )
        return _rank_response(
            mode,
            target_id,
            split_id,
            fold_index,
            ranking_t,
            alias_dedup,
            blocked,
            tof_provenance,
            {
                "target_readiness": target_readiness,
                "target_limitation": target_limitation,
            },
            request,
            battery_id,
            experiment_id,
        )

    # Reference SOC via the existing stratified suite (§3/§4/§5/§6)
    ranking: list[dict[str, Any]] = []
    for code in features:
        frows = _rows_for(code)
        suite = soc_correlation_suite(frows, analysis_id=f"rank:{code}", feature_code=code)
        by = {(r.method, r.scope): r for r in suite}
        po = by[("pearson", "overall")]
        entry: dict[str, Any] = {
            "feature_code": code,
            **_meta_for(code),
            "pearson_overall": po.coefficient,
            "spearman_overall": by[("spearman", "overall")].coefficient,
            "pearson_charge": by[("pearson", "charge")].coefficient,
            "pearson_discharge": by[("pearson", "discharge")].coefficient,
            "spearman_charge": by[("spearman", "charge")].coefficient,
            "spearman_discharge": by[("spearman", "discharge")].coefficient,
            "n_valid": po.n_valid,
            "n_missing": po.missing_feature_count + po.missing_state_count,
            "status": po.status,
            "estimate_audit": [
                {
                    "analysis_id": result.analysis_id,
                    "scope": result.scope,
                    "method": result.method,
                    "coefficient": result.coefficient,
                    "n_input": result.n_input,
                    "n_input_unit": result.n_input_unit,
                    "n_valid": result.n_valid,
                    "n_valid_unit": result.n_valid_unit,
                    "independent_group_count": result.independent_group_count,
                    "independent_unit": result.independent_unit,
                    "group_identity_status": result.group_identity_status,
                    "distinct_state_count": result.distinct_state_count,
                    "missing_feature_count": result.missing_feature_count,
                    "missing_state_count": result.missing_state_count,
                    "excluded_ineligible_count": result.excluded_ineligible_count,
                    "limitations": result.limitations,
                    "status": result.status,
                }
                for result in suite
            ],
        }
        entry["direction_status"] = _rank_direction_status(
            po.status,
            entry["pearson_charge"],
            entry["pearson_discharge"],
            entry["spearman_overall"],
        )
        entry["direction_dependent"] = entry["direction_status"] == "DIRECTION_DEPENDENT"
        entry["freshness"] = (
            "REFRESH_REQUIRED" if (code == "tof_us" and tof_refresh_required) else "CURRENT"
        )
        entry["commit_eligible"] = po.status == "VALID" and variant == "RAW"
        if code == "tof_us" and tof_refresh_required:
            entry["commit_eligible"] = False
            entry["note"] = "canonical TOF artifact 基于旧闸门窗口，需重算 canonical TOF"
        if variant in ("SOURCE_MOVMEAN5", "MOVMEAN_5_SOURCE_ORDER"):
            entry["exploratory_only"] = True
            entry["commit_eligible"] = False
        if code == "TOF_XCORR":
            entry["legacy_diagnostic"] = True
            entry["note"] = "XCorr 仅诊断，不进入 canonical tof_us"
        ranking.append(entry)

    detail: dict[str, Any] | None = None
    if detail_feature and detail_feature in series_map:
        detail = _ranking_detail_scatter(
            request,
            battery_id,
            experiment_id,
            series_map[detail_feature],
            detail_feature,
            target_id,
            train_ids,
            len(frames),
        )

    # default display ordering: abs overall Spearman (explicitly NOT "best")
    ranking.sort(key=lambda e: -abs(e.get("spearman_overall") or 0.0))
    extra_response: dict[str, Any] = {"detail": detail} if detail else {}
    if target_id == "reference_soc_percent":
        extra_response["inference_assessment"] = exploratory_inference_assessment(
            correlation_results_included=True,
            study_protocol_assessment=_experiment_analysis_plan_assessment(
                request, battery_id, experiment_id
            ),
        )
        extra_response["alignment_assessment"] = _correlation_alignment_assessment(
            request, battery_id, experiment_id
        )
    return _rank_response(
        mode,
        target_id,
        split_id,
        fold_index,
        ranking,
        alias_dedup,
        blocked,
        tof_provenance,
        extra_response,
        request,
        battery_id,
        experiment_id,
        variant,
    )


def _rank_response(
    mode,
    target_id,
    split_id,
    fold_index,
    ranking,
    alias_dedup,
    blocked,
    tof_provenance,
    extra,
    request,
    battery_id,
    experiment_id,
    variant="RAW",
) -> dict[str, Any]:
    """Shared envelope: honest counts, limitations, association-only note."""
    events, labels = _load_events_labels(request, battery_id, experiment_id)
    joined = _merge_event_labels(events, labels)
    n = len(joined)
    eligible = (
        int((joined["analysis_eligible"] & joined["soc_reference_percent"].notna()).sum())
        if "soc_reference_percent" in joined.columns
        else int(joined["analysis_eligible"].sum())
    )
    data: dict[str, Any] = {
        "mode": mode,
        "analysis_mode": mode,
        "target_id": target_id,
        "variant": variant,
        "scope": ["overall", "charge", "discharge"],
        "split_id": split_id or None,
        "fold_index": fold_index or None,
        "ordering": "abs_overall_spearman — Default display ordering "
        "(display convention, not a scientific best)",
        "ranking": ranking,
        "alias_dedup": alias_dedup,
        "blocked_forbidden": [
            {
                "feature_code": b,
                "status": "BLOCKED_FORBIDDEN_PREDICTOR",
                "commit_eligible": False,
                "reason": "target-derivation column — never ranked or committed",
            }
            for b in blocked
        ],
        "summary": {
            "aligned_events": n,
            "target_eligible_rows": eligible,
            "waveform_valid_frames": n,
        },
        "limitations": (
            ["EXPLORATORY_NOT_ML_SAFE"]
            if mode == "EXPLORATORY"
            else ["TRAIN_ONLY_ML_SAFE", "WITHIN_BATTERY_CROSS_CYCLE_LIMITED"]
        )
        + ["RANKING_DESCRIBES_ASSOCIATION_ONLY"],
        "note": "Ranking describes statistical association under the selected "
        "scope; it does not identify the scientifically best feature, "
        "causality, or a predictive guarantee.",
    }
    if tof_provenance is not None:
        data["tof_provenance"] = tof_provenance
    if isinstance(extra, dict):
        data.update(extra)
    return {
        "data": data,
        "meta": {
            "read_only": True,
            "note": "ranking is a read-only aggregation of canonical artifacts; no artifact writes",
        },
    }


def _ranking_detail_scatter(
    request, battery_id, experiment_id, series, code, target_id, train_ids, max_frames
) -> dict[str, Any]:
    """§13 detail panel data: backend-computed scatter + stats per scope."""
    import random

    rows = _correlation_rows(
        request, battery_id, experiment_id, series, code, max_frames=max_frames
    )
    if train_ids is not None:
        rows = [r for r in rows if r.measurement_event_id in train_ids]
    tcol = {"reference_soc_percent": "reference_soc_percent"}.get(target_id, target_id)
    scopes = {
        "overall": [r for r in rows if r.analysis_eligible],
        "charge": [r for r in rows if r.analysis_eligible and r.state == "charge"],
        "discharge": [r for r in rows if r.analysis_eligible and r.state == "discharge"],
    }
    out: dict[str, Any] = {"feature_code": code, "target_id": target_id, "scopes": {}}
    rng = random.Random(21)
    for scope, srows in scopes.items():
        pts = [
            (r.value, getattr(r, tcol, None))
            for r in srows
            if r.value is not None and getattr(r, tcol, None) is not None
        ]
        if len(pts) > 300:
            pts = rng.sample(pts, 300)
        out["scopes"][scope] = {
            "n": len(
                [r for r in srows if r.value is not None and getattr(r, tcol, None) is not None]
            ),
            "points": [{"x": float(x), "y": float(y)} for x, y in pts],
        }
    out["excluded_ineligible"] = len([r for r in rows if not r.analysis_eligible])
    return out


# ---------------------------------------------------------------------------
# BRW-017R2 — canonical envelope-peak TOF (read endpoints)
# ---------------------------------------------------------------------------


@router.get("/experiments/{battery_id}/{experiment_id}/canonical-tof")
def canonical_tof(
    request: Request,
    battery_id: str,
    experiment_id: str,
    limit: int = Query(default=200, ge=1, le=4000),
) -> dict[str, Any]:
    """Canonical envelope-peak TOF series (SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1).

    fs comes from the effective ParameterSet only; both TOF gates must be the
    frozen source-template bindings; XCorr is never consumed.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    import pandas as pd

    frames = _load_frames(request, battery_id, experiment_id)
    events, _ = _load_events_labels(request, battery_id, experiment_id)
    frame_meta_path = (
        get_service(request).processed_root
        / "ultrasound"
        / battery_id
        / experiment_id
        / "frames.parquet"
    )
    frame_meta = pd.read_parquet(
        frame_meta_path, columns=["ultrasound_asset_id", "frame_index_raw"]
    )
    event_identity = events[
        ["measurement_event_id", "ultrasound_asset_id", "frame_index_raw"]
    ]
    identity = frame_meta.merge(
        event_identity,
        on=["ultrasound_asset_id", "frame_index_raw"],
        how="left",
        validate="one_to_one",
        sort=False,
    )
    if identity["measurement_event_id"].isna().any():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "canonical TOF could not resolve every waveform to one MeasurementEvent",
        )

    # fs from the effective parameter set — the only legal provenance
    fs_hz, fs_verified, parameter_set_id = _resolved_sampling_rate(
        get_service(request).processed_root, battery_id, experiment_id
    )
    if parameter_set_id is None:
        raise APIError(
            ErrorCode.ARTIFACT_NOT_AVAILABLE,
            "no resolved sampling-rate parameter set (fs alone does not activate TOF)",
        )

    from battery_workbench.features.gate_calibration import (
        CANONICAL_TOF_METHOD,
        TOFGateBinding,
        resolve_tof_gate_calibration,
    )
    from battery_workbench.features_physical.canonical_tof import (
        compute_canonical_tof_series,
    )

    # confirmed experiment calibration takes priority over the source template;
    # the fallback identity is always explicit provenance, never a silent one
    cal = resolve_tof_gate_calibration(
        battery_id, experiment_id, get_service(request).processed_root
    )
    surface_binding = TOFGateBinding(
        role="surface",
        gate_id=cal["surface_gate_id"],
        matlab_range="",
        python_start=cal["surface_start"],
        python_end_exclusive=cal["surface_end_exclusive"],
        length_samples=cal["surface_end_exclusive"] - cal["surface_start"],
    )
    bottom_binding = TOFGateBinding(
        role="bottom",
        gate_id=cal["bottom_gate_id"],
        matlab_range="",
        python_start=cal["bottom_start"],
        python_end_exclusive=cal["bottom_end_exclusive"],
        length_samples=cal["bottom_end_exclusive"] - cal["bottom_start"],
    )
    n = min(len(frames), len(identity), limit)
    frames = frames[:n]
    identity = identity.iloc[:n].reset_index(drop=True)
    table = compute_canonical_tof_series(
        frames[:n],
        identity["measurement_event_id"].astype(str).tolist(),
        surface_gate=surface_binding,
        bottom_gate=bottom_binding,
        gate_calibration_id=cal["gate_calibration_id"],
        sampling_rate_hz=fs_hz if fs_verified else None,
        parameter_set_id=parameter_set_id,
        frame_index_offset=0,
    )
    # Do not expose the calculator's positional placeholder as source identity.
    table = table.drop(columns=["frame_index_raw"], errors="ignore")
    table = table.merge(
        identity[["measurement_event_id", "ultrasound_asset_id", "frame_index_raw"]],
        on="measurement_event_id",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    status_counts = table["tof_status"].value_counts().to_dict()
    valid = table[table["tof_status"] == "VALID"]
    tof_series = valid["tof_samples"]
    tof_us_series = valid["tof_us"]

    def _stats(s: pd.Series | None) -> dict[str, float | None] | None:
        if s is None or s.empty:
            return None
        return {
            "min": float(s.min()),
            "median": float(s.median()),
            "max": float(s.max()),
        }

    return {
        "data": {
            "tof_method_id": CANONICAL_TOF_METHOD,
            "sampling_rate_hz": fs_hz,
            "sampling_rate_verified": fs_verified,
            "parameter_set_id": parameter_set_id,
            "surface_gate_id": surface_binding.gate_id,
            "bottom_gate_id": bottom_binding.gate_id,
            "gate_calibration_source": cal["source"],
            "gate_calibration_version": cal["version"],
            "rows": json.loads(table.to_json(orient="records")),
            "audit": {
                "total_frames": int(n),
                "status_counts": status_counts,
                "surface_valid": int(table["surface_peak_sample_index"].notna().sum()),
                "bottom_valid": int(table["bottom_peak_sample_index"].notna().sum()),
                "canonical_tof_valid": len(valid),
                "tof_samples_stats": _stats(tof_series),
                "tof_us_stats": _stats(tof_us_series),
            },
        },
        "meta": {
            "note": "fs from Parameter Registry; never from cadence/sample count/filename",
        },
    }

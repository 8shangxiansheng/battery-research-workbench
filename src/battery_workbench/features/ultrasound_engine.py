"""BRW-013 Ultrasound Feature Engine (Sample-Domain V1).

Consumes one AnalysisSlice + a waveform Zarr store and emits one feature row per
slice event. The per-asset relative cross-correlation reference is the first
valid event by ``event_order_index`` and is pre-loaded once per asset. No
resynchronization, no re-filtering, no waveform alignment, no physical
TOF/frequency (V1 stays sample-domain).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import zarr

from battery_workbench.features.definitions import FEATURE_DEFINITIONS
from battery_workbench.features.envelope import compute_envelope_features
from battery_workbench.features.feature_set_id import build_feature_set_id
from battery_workbench.features.raw_features import compute_raw_amplitude_features
from battery_workbench.features.ultrasound_schemas import (
    UltrasoundFeatureConfig,
    UltrasoundFeatureReport,
)
from battery_workbench.features.validation import (
    classify_waveform,
    physical_features_available,
    validate_locator,
)
from battery_workbench.features.xcorr import compute_relative_xcorr_features

logger = logging.getLogger(__name__)

_CONTEXT_COLS = [
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "ultrasound_asset_id",
    "frame_index_raw",
    "event_order_index",
    "provisional_absolute_timestamp",
    "elapsed_time_s",
    "waveform_group",
    "waveform_row_index",
    "cycle_index_raw",
    "step_index_raw",
    "step_type",
    "voltage_v",
    "current_a",
    "capacity_ah",
    "temperature_c",
    "soc_dod_percent",
    "sync_error_s",
    "event_quality_status",
    "analysis_eligible",
]


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zarr_provenance(zpath: Path) -> str:
    group = zarr.open_group(str(zpath), mode="r")
    return "|".join(sorted(str(k) for k in group)) or "empty"


def _sampling_rate(root: Any) -> float | None:
    for gname in root:
        group = root[gname]
        arr = group.get("waveform") if hasattr(group, "get") else None
        if arr is not None:
            value = arr.attrs.get("sampling_rate_hz")
            if value is not None:
                return value
        value = group.attrs.get("sampling_rate_hz")
        if value is not None:
            return value
    return None


def _reference_waveforms(
    slice_df: pd.DataFrame,
    root: Any,
    references: dict[str, str],
    warnings: list[str],
) -> dict[str, np.ndarray]:
    """Pre-load one reference waveform per asset (first valid event)."""
    refs: dict[str, np.ndarray] = {}
    for asset_id, ref_event_id in references.items():
        row = slice_df[slice_df["measurement_event_id"] == ref_event_id]
        if row.empty:
            warnings.append(f"asset {asset_id}: reference event {ref_event_id} not found")
            continue
        r = row.iloc[0]
        try:
            group = str(r["waveform_group"])
            idx = int(r["waveform_row_index"])
            # ``group`` is the full array path (e.g. "U001/waveform"); root[group] is the Array.
            refs[asset_id] = np.asarray(root[group][idx])
        except (KeyError, ValueError) as exc:
            warnings.append(f"asset {asset_id}: could not load reference waveform: {exc}")
    return refs


def extract_ultrasound_features(
    *,
    analysis_slice_path: Path,
    waveform_store_path: Path,
    output_root: Path,
    config: UltrasoundFeatureConfig | None = None,
) -> UltrasoundFeatureReport:
    """Extract sample-domain features for every event in an AnalysisSlice."""
    from battery_workbench.features.persistence import write_feature_payload

    analysis_slice_path = Path(analysis_slice_path)
    waveform_store_path = Path(waveform_store_path)
    output_root = Path(output_root)
    config = config or UltrasoundFeatureConfig()

    if not analysis_slice_path.exists():
        raise FileNotFoundError(f"analysis slice not found: {analysis_slice_path}")

    slice_df = pd.read_parquet(analysis_slice_path)
    slice_checksum = _sha256(analysis_slice_path)
    store_provenance = _zarr_provenance(waveform_store_path)
    store_checksum = _sha256(waveform_store_path)

    root = zarr.open_group(str(waveform_store_path), mode="r")
    sampling_rate = _sampling_rate(root)

    feature_set_id = build_feature_set_id(
        analysis_slice_checksum=slice_checksum,
        waveform_store_provenance=store_provenance,
        normalized_config=config.model_dump(mode="json"),
        feature_definition_version=config.feature_definition_version,
    )

    # Derive context from the slice manifest (correct for empty slices too).
    manifest_path = analysis_slice_path.parent / "analysis_slice_manifest.json"
    if manifest_path.exists():
        import json as _json

        _m = _json.loads(manifest_path.read_text(encoding="utf-8"))
        battery_id = _m.get("battery_id", "")
        experiment_id = _m.get("experiment_id", "")
        analysis_slice_id = _m.get("analysis_slice_id", "")
    else:
        # Fallback for synthetic tests: infer from parent dir / .iloc[0].
        analysis_slice_id = (
            analysis_slice_path.parent.name
            if analysis_slice_path.parent.name.startswith("AS::")
            else ""
        )
        battery_id = str(slice_df["battery_id"].iloc[0]) if not slice_df.empty else ""
        experiment_id = str(slice_df["experiment_id"].iloc[0]) if not slice_df.empty else ""

    references: dict[str, str] = {}
    for asset_id, sub in slice_df.groupby("ultrasound_asset_id"):
        first = sub.sort_values("event_order_index").iloc[0]
        references[asset_id] = str(first["measurement_event_id"])

    ref_waveforms = _reference_waveforms(slice_df, root, references, [])

    rows: list[dict] = []
    status_counts: dict[str, int] = {}
    for _, event in slice_df.iterrows():
        row = _extract_one(event, root, ref_waveforms, references)
        status_counts[row["feature_status"]] = status_counts.get(row["feature_status"], 0) + 1
        rows.append(row)

    # Explicit column schema so an empty slice still preserves the feature schema.
    columns = (
        list(dict.fromkeys(_CONTEXT_COLS))
        + [d["name"] for d in FEATURE_DEFINITIONS]
        + [
            "xcorr_warning",
            "feature_status",
            "sampling_rate_hz",
            "physical_time_features_available",
            "physical_frequency_features_available",
        ]
    )
    features_df = pd.DataFrame(rows, columns=columns)
    physical_time, physical_freq = physical_features_available(sampling_rate)
    warnings: list[str] = []
    if sampling_rate is None:
        warnings.append("sampling_rate_hz is null: physical time/frequency features unavailable")

    return write_feature_payload(
        features=features_df,
        slice_df=slice_df,
        battery_id=battery_id,
        experiment_id=experiment_id,
        analysis_slice_id=analysis_slice_id,
        feature_set_id=feature_set_id,
        analysis_slice_path=analysis_slice_path,
        slice_checksum=slice_checksum,
        waveform_store_path=waveform_store_path,
        store_provenance=store_provenance,
        store_checksum=store_checksum,
        sampling_rate=sampling_rate,
        physical_time=physical_time,
        physical_freq=physical_freq,
        xcorr_references=references,
        feature_status_counts=status_counts,
        warnings=warnings,
        config=config,
        output_root=output_root,
        context_cols=_CONTEXT_COLS,
    )


def _load_waveform(root: Any, group: str, row_index: int) -> np.ndarray:
    if group not in root:
        raise ValueError(f"waveform group not found: {group}")
    # ``group`` is the full array path; root[group] returns the Array directly.
    arr = root[group]
    if not validate_locator(group, row_index, arr.shape[0]):
        raise ValueError(f"invalid waveform locator: {group}:{row_index}")
    return np.asarray(arr[row_index])


def _extract_one(
    event: pd.Series,
    root: Any,
    ref_waveforms: dict[str, np.ndarray],
    references: dict[str, str],
) -> dict:
    group = str(event["waveform_group"]) if pd.notna(event["waveform_group"]) else ""
    row_index = int(event["waveform_row_index"]) if pd.notna(event["waveform_row_index"]) else -1
    out: dict[str, Any] = {col: event[col] for col in _CONTEXT_COLS if col in event.index}
    try:
        waveform = _load_waveform(root, group, row_index)
    except ValueError:
        out.update(feature_status="NONFINITE_WAVEFORM")
        out.update({d["name"]: None for d in FEATURE_DEFINITIONS})
        out.update(_xcorr_empty())
        return out

    status = classify_waveform(waveform)
    out.update(compute_raw_amplitude_features(waveform))
    out.update(compute_envelope_features(waveform))

    asset_id = str(event["ultrasound_asset_id"])
    ref_event_id = references.get(asset_id)
    out["xcorr_reference_measurement_event_id"] = ref_event_id
    ref = ref_waveforms.get(asset_id)
    if ref is not None:
        feat = compute_relative_xcorr_features(waveform, ref)
        out["xcorr_shift_samples"] = feat["xcorr_shift_samples"]
        out["xcorr_peak_coefficient"] = feat["xcorr_peak_coefficient"]
        out["xcorr_warning"] = feat["xcorr_warning"]
    else:
        out.update(_xcorr_empty())

    out["feature_status"] = status
    out["sampling_rate_hz"] = None
    out["physical_time_features_available"] = False
    out["physical_frequency_features_available"] = False
    return out


def _xcorr_empty() -> dict[str, Any]:
    return {
        "xcorr_shift_samples": None,
        "xcorr_peak_coefficient": None,
        "xcorr_warning": None,
    }

"""BRW-009 Timestamp Construction Engine.

Turns a BRW-008 selected anchor + BRW-005 frame elapsed clock into a provisional
absolute per-frame timestamp. V1 clock model is OFFSET_ONLY. It never reads
electrical records, never performs matching, drift fit, or cycle mapping, and
never claims verified synchronization.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.clock import construct_timestamp
from battery_workbench.synchronization.schemas import TimeAnchorState
from battery_workbench.synchronization.timestamp_schemas import (
    ClockModel,
    TimestampEngineAssetResult,
    TimestampEngineConfig,
    TimestampEngineReport,
)
from battery_workbench.synchronization.timestamp_validation import (
    compare_legacy_timestamp,
)

logger = logging.getLogger(__name__)

_COLUMN_MAP = {
    "battery_id": "battery_id",
    "experiment_id": "experiment_id",
    "ultrasound_asset_id": "ultrasound_asset_id",
    "source_file": "source_file",
    "source_line_index": "source_line_index",
    "frame_index_raw": "frame_index_raw",
    "waveform_group": "waveform_group",
    "waveform_row_index": "waveform_row_index",
    "elapsed_time_s": "elapsed_time_s",
}


def _load_anchor_state(path: Path) -> TimeAnchorState:
    return TimeAnchorState.model_validate_json(path.read_text(encoding="utf-8"))


def _candidate_for_asset(asset: dict, selected_anchor_id: str | None) -> dict | None:
    if selected_anchor_id is None:
        return None
    for candidate in asset.get("candidates", []):
        if candidate.get("anchor_id") == selected_anchor_id:
            return candidate
    return None


def _clock_model_for_asset(asset: dict, config: TimestampEngineConfig) -> ClockModel:
    candidate = _candidate_for_asset(asset, asset.get("selected_anchor_id"))
    return ClockModel(
        model_type=config.clock.model_type,
        anchor_id=candidate.get("anchor_id") if candidate else None,
        anchor_datetime=candidate.get("anchor_datetime") if candidate else None,
        elapsed_time_s_at_anchor=candidate.get("elapsed_time_s_at_anchor", 0.0)
        if candidate
        else 0.0,
        scale=config.clock.scale,
        offset_s=config.clock.offset_s,
        drift_enabled=config.clock.drift_enabled,
    )


def construct_asset_timestamps(
    frames: pd.DataFrame,
    asset: dict,
    config: TimestampEngineConfig,
    legacy_tolerance_s: float,
) -> tuple[pd.DataFrame, TimestampEngineAssetResult]:
    """Build the timestamp columns for one asset's frames.

    Returns ``(out_df, asset_diag)``. ``out_df`` keeps the input row count/order.
    """
    asset_id = asset["asset_id"]
    sub = frames[frames["ultrasound_asset_id"] == asset_id].reset_index(drop=True)
    candidate = _candidate_for_asset(asset, asset.get("selected_anchor_id"))
    anchor_status = asset.get("anchor_status")

    anchor_dt: pd.Timestamp | None = None
    elapsed_at_anchor = 0.0
    if candidate is not None:
        anchor_dt = pd.Timestamp(candidate["anchor_datetime"])
        elapsed_at_anchor = float(candidate.get("elapsed_time_s_at_anchor", 0.0))

    avail = [False] * len(sub)
    ts: list[pd.Timestamp | None] = [None] * len(sub)
    legacy: list[pd.Timestamp | None] = [None] * len(sub)
    legacy_delta: list[float | None] = [None] * len(sub)
    legacy_match: list[bool | None] = [None] * len(sub)
    max_delta: float | None = None
    compare_count = 0

    has_legacy = "absolute_timestamp" in sub.columns

    for i, (elapsed, legacy_ts) in enumerate(
        zip(
            sub["elapsed_time_s"].tolist(),
            sub.get("absolute_timestamp", pd.Series([None] * len(sub))).tolist(),
            strict=False,
        )
    ):
        if anchor_dt is not None:
            constructed = construct_timestamp(
                anchor_dt.to_pydatetime(), float(elapsed), elapsed_at_anchor
            )
            ts[i] = pd.Timestamp(constructed)
            avail[i] = True
        if has_legacy and legacy_ts is not None and not pd.isna(legacy_ts):
            legacy[i] = pd.Timestamp(legacy_ts)
            compare_count += 1
            if ts[i] is not None:
                delta_s, match = compare_legacy_timestamp(
                    ts[i].to_pydatetime(),
                    pd.Timestamp(legacy_ts).to_pydatetime(),
                    tolerance_s=legacy_tolerance_s,
                )
                legacy_delta[i] = delta_s
                legacy_match[i] = match
                max_delta = delta_s if max_delta is None else max(max_delta, abs(delta_s))

    out = sub.copy()
    out["anchor_id"] = candidate.get("anchor_id") if candidate else None
    out["anchor_source_type"] = candidate.get("source_type") if candidate else None
    out["anchor_status"] = anchor_status
    out["anchor_datetime"] = anchor_dt
    out["elapsed_time_s_at_anchor"] = elapsed_at_anchor
    out["clock_model_type"] = config.clock.model_type
    out["clock_scale"] = config.clock.scale
    out["clock_offset_s"] = config.clock.offset_s
    out["drift_enabled"] = config.clock.drift_enabled
    out["provisional_absolute_timestamp"] = ts
    out["timestamp_available"] = avail
    out["timezone_known"] = candidate.get("timezone_known", False) if candidate else False
    out["timezone_name"] = candidate.get("timezone_name") if candidate else None
    out["legacy_parser_timestamp"] = legacy
    out["legacy_timestamp_delta_s"] = legacy_delta
    out["legacy_timestamp_match"] = legacy_match

    # Diagnostics.
    elapsed_vals = sub["elapsed_time_s"].dropna()
    ts_vals = pd.Series([p for p in ts if p is not None])
    timestamp_min = ts_vals.min() if not ts_vals.empty else None
    timestamp_max = ts_vals.max() if not ts_vals.empty else None
    diag = TimestampEngineAssetResult(
        asset_id=asset_id,
        frame_count=len(sub),
        timestamp_available_count=sum(avail),
        timestamp_missing_count=len(sub) - sum(avail),
        elapsed_min_s=float(elapsed_vals.min()) if not elapsed_vals.empty else None,
        elapsed_max_s=float(elapsed_vals.max()) if not elapsed_vals.empty else None,
        timestamp_min=timestamp_min.to_pydatetime() if timestamp_min is not None else None,
        timestamp_max=timestamp_max.to_pydatetime() if timestamp_max is not None else None,
        is_elapsed_strictly_increasing=bool(
            elapsed_vals.is_monotonic_increasing and elapsed_vals.is_unique
        ),
        is_timestamp_strictly_increasing=bool(
            ts_vals.is_monotonic_increasing and ts_vals.is_unique
        ),
        duplicate_elapsed_count=int(elapsed_vals.duplicated().sum()),
        duplicate_timestamp_count=int(ts_vals.duplicated().sum()),
        anchor_id=candidate.get("anchor_id") if candidate else None,
        anchor_status=anchor_status,
        legacy_timestamp_compare_count=compare_count,
        legacy_timestamp_max_abs_delta_s=max_delta,
    )
    return out, diag


def build_ultrasound_timestamps(
    *,
    frames_path: Path,
    time_anchor_state_path: Path,
    output_dir: Path,
    config: TimestampEngineConfig,
) -> TimestampEngineReport:
    """Build provisional per-frame timestamps for one experiment.

    Reads ``frames.parquet`` and ``time_anchors.json`` (no electrical input),
    constructs per-asset timestamps, and persists the canonical outputs via
    :mod:`timestamp_persistence`. Returns the :class:`TimestampEngineReport`.
    """
    frames_path = Path(frames_path)
    time_anchor_state_path = Path(time_anchor_state_path)
    output_dir = Path(output_dir)

    if not frames_path.exists():
        raise FileNotFoundError(f"frames not found: {frames_path}")
    if not time_anchor_state_path.exists():
        raise FileNotFoundError(f"time anchor state not found: {time_anchor_state_path}")

    state = _load_anchor_state(time_anchor_state_path)
    frames = pd.read_parquet(frames_path)
    if frames.empty:
        raise ValueError(f"frames empty: {frames_path}")

    # Normalize anchor-state assets to plain dicts for uniform subscript access.
    asset_meta = {a.asset_id: a.model_dump(mode="json") for a in state.assets}
    frames_assets = frames["ultrasound_asset_id"].unique().tolist()

    legacy_tolerance = config.validation.legacy_timestamp_tolerance_s
    asset_results: list[TimestampEngineAssetResult] = []
    clock_models: list[ClockModel] = []
    outputs: list[pd.DataFrame] = []
    warnings: list[str] = []
    errors: list[str] = []

    for asset_id in frames_assets:
        meta = asset_meta.get(asset_id)
        if meta is None:
            # Frame asset present in frames but absent from anchor state.
            warnings.append(f"asset {asset_id}: no anchor assessment in time_anchors.json")
            empty = frames[frames["ultrasound_asset_id"] == asset_id].reset_index(drop=True)
            out = empty.copy()
            for col in (
                "anchor_id",
                "anchor_source_type",
                "anchor_status",
                "anchor_datetime",
                "elapsed_time_s_at_anchor",
                "clock_model_type",
                "clock_scale",
                "clock_offset_s",
                "drift_enabled",
                "provisional_absolute_timestamp",
                "timestamp_available",
                "timezone_known",
                "timezone_name",
                "legacy_parser_timestamp",
                "legacy_timestamp_delta_s",
                "legacy_timestamp_match",
            ):
                out[col] = None
            outputs.append(out)
            asset_results.append(
                TimestampEngineAssetResult(
                    asset_id=asset_id,
                    frame_count=len(out),
                    timestamp_available_count=0,
                    timestamp_missing_count=len(out),
                )
            )
            continue

        out, diag = construct_asset_timestamps(frames, meta, config, legacy_tolerance)
        outputs.append(out)
        asset_results.append(diag)
        clock_models.append(_clock_model_for_asset(meta, config))
        if diag.timestamp_available_count == 0:
            warnings.append(f"asset {asset_id}: no anchor; timestamps unavailable")
        elif meta.get("anchor_status") == "CONFLICTING":
            # A conflicting but selected anchor still timestamps, but the
            # conflict is propagated to the caller (BRW-009 §10).
            warnings.append(
                f"asset {asset_id}: anchor_status CONFLICTING; selected anchor used "
                "with provisional-with-warning status"
            )

    # Concatenate outputs and restore the original frames row order.
    combined = pd.concat(outputs, ignore_index=True)
    if "event_order_index" in combined.columns:
        combined = combined.sort_values("event_order_index", kind="stable").reset_index(drop=True)
    if len(combined) != len(frames):
        errors.append("output row count does not match input")

    # Orphan anchors (in anchor state but not in frames).
    for asset_id in asset_meta:
        if asset_id not in frames_assets:
            warnings.append(
                f"orphan anchor asset {asset_id}: present in anchor state, absent in frames"
            )

    total_avail = sum(r.timestamp_available_count for r in asset_results)
    total_missing = sum(r.timestamp_missing_count for r in asset_results)
    status = _status(asset_results, warnings, errors)

    report = TimestampEngineReport(
        battery_id=state.battery_id,
        experiment_id=state.experiment_id,
        engine_version=config.version,
        input_frame_count=len(frames),
        output_frame_count=len(combined),
        assets=asset_results,
        timestamp_available_count=total_avail,
        timestamp_missing_count=total_missing,
        clock_models=clock_models,
        warnings=warnings,
        errors=errors,
        status=status,
        validated_sync=False,
        electrical_matching_performed=False,
        drift_correction_applied=False,
        cycle_mapping_performed=False,
        configuration=_config_dump(config),
    )

    from battery_workbench.synchronization.timestamp_persistence import write_timestamp_payload

    outputs_written = write_timestamp_payload(
        report,
        combined,
        state=state,
        frames_path=frames_path,
        time_anchor_state_path=time_anchor_state_path,
        output_dir=output_dir,
        config=config,
    )
    report.artifacts = outputs_written
    return report


def _config_dump(config: TimestampEngineConfig) -> dict:
    return config.model_dump()


def _status(
    assets: list[TimestampEngineAssetResult], warnings: list[str], errors: list[str]
) -> str:
    if errors:
        return "FAIL"
    if any(a.timestamp_available_count == 0 for a in assets) or warnings:
        return "PASS_WITH_WARNINGS"
    return "PASS"

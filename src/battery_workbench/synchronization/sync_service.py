"""BRW-010 high-level synchronization service.

``synchronize_ultrasound_to_electrical`` matches each timestamp-available
ultrasound frame to the nearest electrical record group and persists aligned
summary + candidate outputs. ``align_frames`` is the pure (DataFrame-level)
worker used by tests and the service.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from battery_workbench.synchronization.matcher import (
    ElectricalIndex,
    build_electrical_index,
    candidates_for_frame,
    find_nearest_candidates,
)
from battery_workbench.synchronization.sync_schemas import (
    SynchronizationConfig,
    SynchronizationReport,
    SyncQualityMetrics,
)

logger = logging.getLogger(__name__)

_TIMESTAMP_COL = "timestamp"
_LOCATOR_COL = "source_row_index"
_ASSET_COL = "electrical_asset_id"


def _timezone_kind(series: pd.Series) -> str:
    """Return 'naive' or 'aware' based on the series timezone."""
    try:
        return "aware" if series.dt.tz is not None else "naive"
    except Exception:  # noqa: BLE001 - non-datetime series should read as naive
        return "naive"


def align_frames(
    ultrasound: pd.DataFrame,
    index: ElectricalIndex,
    *,
    max_sync_error_s: float,
    tie_tolerance_s: float,
) -> pd.DataFrame:
    """Align one set of ultrasound frames to an electrical index.

    Returns a DataFrame with one row per input frame, in the input order.
    Unavailable/tz-mismatch frames are marked without matching.
    """
    uts_col = "provisional_absolute_timestamp"
    avail_col = "timestamp_available"

    # Timezone compatibility is decided once for the whole frame set.
    ultra_aware = _timezone_kind(ultrasound[uts_col])
    elec_aware = "naive"
    if index.record_count > 0 and index.sorted_timestamps:
        elec_aware = "aware" if index.sorted_timestamps[0].tzinfo is not None else "naive"
    tz_mismatch = ultra_aware != elec_aware

    rows: list[dict] = []
    for _, urow in ultrasound.iterrows():
        ts = urow[uts_col]
        available = bool(urow.get(avail_col, True))
        base = {
            "battery_id": urow.get("battery_id"),
            "experiment_id": urow.get("experiment_id"),
            "ultrasound_asset_id": urow.get("ultrasound_asset_id"),
            "frame_index_raw": urow.get("frame_index_raw"),
            "waveform_group": urow.get("waveform_group"),
            "waveform_row_index": urow.get("waveform_row_index"),
            "provisional_absolute_timestamp": ts,
            "anchor_id": urow.get("anchor_id"),
            "anchor_status": urow.get("anchor_status"),
            "validated_sync": False,
            # composite selected identity: (electrical_asset_id, locator);
            # filled only for MATCHED_UNIQUE, null otherwise (BRW-010R §2/§4).
            "electrical_asset_id": None,
        }

        if not available:
            base.update(
                match_status="TIMESTAMP_UNAVAILABLE",
                electrical_asset_id=None,
                electrical_record_locator=None,
                electrical_timestamp=None,
                sync_error_s=None,
                within_tolerance=False,
                candidate_timestamp_count=0,
                candidate_record_count=0,
                sync_ambiguous=False,
                ambiguity_type=None,
                boundary_flag=False,
                boundary_reason=None,
            )
            rows.append(base)
            continue

        if tz_mismatch:
            base.update(
                match_status="TIMEZONE_MISMATCH",
                electrical_asset_id=None,
                electrical_record_locator=None,
                electrical_timestamp=None,
                sync_error_s=None,
                within_tolerance=False,
                candidate_timestamp_count=0,
                candidate_record_count=0,
                sync_ambiguous=False,
                ambiguity_type=None,
                boundary_flag=False,
                boundary_reason=None,
            )
            rows.append(base)
            continue

        result = find_nearest_candidates(
            ts.to_pydatetime()
            if hasattr(ts, "to_pydatetime")
            else pd.Timestamp(ts).to_pydatetime(),
            index,
            tie_tolerance_s=tie_tolerance_s,
        )
        within = result.within_tolerance(max_sync_error_s)
        ambiguous = result.candidate_record_count != 1
        selected_asset = None
        if result.candidate_timestamp_count == 0:
            status = "NO_ELECTRICAL_CANDIDATE"
            selected_locator = None
            selected_ts = None
        elif not within:
            status = "OUT_OF_TOLERANCE"
            selected_locator = None
            selected_ts = None
        elif ambiguous:
            status = "MATCHED_AMBIGUOUS"
            selected_locator = None
            selected_ts = None
        else:
            status = "MATCHED_UNIQUE"
            # exactly one record under the nearest timestamp group; the
            # selected identity is composite: (asset_id, locator).
            best_ts = result.candidate_timestamps[0]
            rec = index.record_lists[best_ts][0]
            selected_asset = rec["asset_id"]
            selected_locator = rec["locator"]
            selected_ts = rec["timestamp"]

        base.update(
            match_status=status,
            electrical_asset_id=selected_asset,
            electrical_record_locator=selected_locator,
            electrical_timestamp=selected_ts,
            sync_error_s=result.sync_error_s,
            within_tolerance=bool(within),
            candidate_timestamp_count=result.candidate_timestamp_count,
            candidate_record_count=result.candidate_record_count,
            sync_ambiguous=ambiguous and result.candidate_timestamp_count > 0,
            ambiguity_type=result.ambiguity_type if result.candidate_timestamp_count > 0 else None,
            boundary_flag=False,  # filled in service layer using boundary detection
            boundary_reason=None,
        )
        rows.append(base)

    return pd.DataFrame(rows)


def synchronize_ultrasound_to_electrical(
    *,
    timestamped_frames_path: Path,
    electrical_records_path: Path,
    output_dir: Path,
    config: SynchronizationConfig,
) -> SynchronizationReport:
    """Read inputs, align, and persist sync outputs (read-only inputs)."""
    timestamped_frames_path = Path(timestamped_frames_path)
    electrical_records_path = Path(electrical_records_path)
    output_dir = Path(output_dir)

    if not timestamped_frames_path.exists():
        raise FileNotFoundError(f"timestamped frames not found: {timestamped_frames_path}")
    if not electrical_records_path.exists():
        raise FileNotFoundError(f"electrical records not found: {electrical_records_path}")

    ultrasound = pd.read_parquet(timestamped_frames_path)
    electrical = pd.read_parquet(electrical_records_path)
    if electrical.empty:
        raise ValueError("electrical records empty")

    index = build_electrical_index(
        electrical,
        timestamp_col=_TIMESTAMP_COL,
        locator_col=_LOCATOR_COL,
        asset_col=_ASSET_COL,
    )
    aligned = align_frames(
        ultrasound,
        index,
        max_sync_error_s=config.matching.max_sync_error_s,
        tie_tolerance_s=config.matching.tie_tolerance_s,
    )

    # Boundary diagnostics computed on electrical original order.
    from battery_workbench.synchronization.boundary import detect_boundary

    boundary = detect_boundary(electrical)
    boundary_map: dict[tuple, bool] = {}
    for _, brow in boundary.iterrows():
        key = (brow[_ASSET_COL], brow[_LOCATOR_COL])
        boundary_map[key] = bool(brow["boundary_flag"])

    # Attach boundary to aligned rows by selected locator/asset when present.
    aligned_boundary: list[bool] = []
    for _, arow in aligned.iterrows():
        locator = arow.get("electrical_record_locator")
        asset = arow.get("electrical_asset_id")
        is_boundary = False
        if locator is not None and asset is not None:
            is_boundary = boundary_map.get((asset, locator), False)
        aligned_boundary.append(is_boundary)
    aligned["boundary_flag"] = aligned_boundary

    # Candidate audit table.
    cand_rows: list[dict] = []
    for _, arow in aligned.iterrows():
        if arow["match_status"] in ("MATCHED_UNIQUE", "MATCHED_AMBIGUOUS", "OUT_OF_TOLERANCE"):
            ts = arow["provisional_absolute_timestamp"]
            for cand in candidates_for_frame(
                ts.to_pydatetime()
                if hasattr(ts, "to_pydatetime")
                else pd.Timestamp(ts).to_pydatetime(),
                index,
                tie_tolerance_s=config.matching.tie_tolerance_s,
            ):
                cand_rows.append(
                    {
                        "battery_id": arow["battery_id"],
                        "experiment_id": arow["experiment_id"],
                        "ultrasound_asset_id": arow["ultrasound_asset_id"],
                        "frame_index_raw": arow["frame_index_raw"],
                        "ultrasound_timestamp": ts,
                        **{k: v for k, v in cand.items()},
                        "boundary_flag": arow["boundary_flag"],
                    }
                )
    candidates_df = pd.DataFrame(cand_rows)

    metrics = _compute_metrics(aligned)
    status = _report_status(metrics)
    report = SynchronizationReport(
        battery_id=str(aligned["battery_id"].iloc[0]) if not aligned.empty else "",
        experiment_id=str(aligned["experiment_id"].iloc[0]) if not aligned.empty else "",
        sync_version=config.version,
        matching_method=config.matching.method,
        max_sync_error_s=config.matching.max_sync_error_s,
        tie_tolerance_s=config.matching.tie_tolerance_s,
        ultrasound_frame_count=len(aligned),
        electrical_record_count=len(electrical),
        metrics=metrics,
        status=status,
        matching_performed=True,
        validated_sync=False,
        sync_semantics="MATCHED_USING_PROVISIONAL_TIMEBASE",
        configuration=config.model_dump(),
    )

    from battery_workbench.synchronization.sync_persistence import write_sync_payload

    report.artifacts = write_sync_payload(
        aligned=aligned,
        candidates=candidates_df,
        battery_id=report.battery_id,
        experiment_id=report.experiment_id,
        sync_version=config.version,
        ultrasound_frames_path=timestamped_frames_path,
        electrical_records_path=electrical_records_path,
        output_dir=output_dir,
        report=report,
    )
    return report


def _compute_metrics(aligned: pd.DataFrame) -> SyncQualityMetrics:
    statuses = aligned["match_status"] if not aligned.empty else pd.Series(dtype=object)
    total = len(aligned)
    unique = int((statuses == "MATCHED_UNIQUE").sum())
    ambiguous = int((statuses == "MATCHED_AMBIGUOUS").sum())
    oot = int((statuses == "OUT_OF_TOLERANCE").sum())
    unavailable = int((statuses == "TIMESTAMP_UNAVAILABLE").sum())
    no_cand = int((statuses == "NO_ELECTRICAL_CANDIDATE").sum())
    tz = int((statuses == "TIMEZONE_MISMATCH").sum())
    errs = (
        aligned.loc[aligned["sync_error_s"].notna(), "sync_error_s"]
        if "sync_error_s" in aligned.columns
        else pd.Series(dtype=float)
    )
    errs = errs.astype(float)
    return SyncQualityMetrics(
        total_ultrasound_frames=total,
        matched_unique_count=unique,
        matched_ambiguous_count=ambiguous,
        out_of_tolerance_count=oot,
        timestamp_unavailable_count=unavailable,
        no_candidate_count=no_cand,
        timezone_mismatch_count=tz,
        ambiguous_fraction=(ambiguous / total) if total else 0.0,
        within_tolerance_fraction=(unique + ambiguous) / total if total else 0.0,
        sync_error_min_s=float(errs.min()) if not errs.empty else None,
        sync_error_median_s=float(errs.median()) if not errs.empty else None,
        sync_error_p95_s=float(errs.quantile(0.95)) if not errs.empty else None,
        sync_error_max_s=float(errs.max()) if not errs.empty else None,
        boundary_match_count=int(aligned["boundary_flag"].sum())
        if "boundary_flag" in aligned
        else 0,
        ambiguous_boundary_count=int(
            ((aligned["match_status"] == "MATCHED_AMBIGUOUS") & (aligned["boundary_flag"])).sum()
        )
        if "boundary_flag" in aligned
        else 0,
    )


def _report_status(metrics: SyncQualityMetrics) -> str:
    if metrics.timezone_mismatch_count > 0:
        return "FAIL"
    if metrics.no_candidate_count > 0 and metrics.matched_unique_count == 0:
        return "FAIL"
    if (
        metrics.out_of_tolerance_count > 0
        or metrics.matched_ambiguous_count > 0
        or metrics.timestamp_unavailable_count > 0
    ):
        return "PASS_WITH_WARNINGS"
    return "PASS"

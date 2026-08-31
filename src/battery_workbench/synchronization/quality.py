from __future__ import annotations
import statistics

from battery_workbench.synchronization.schemas import SyncQualityReport


def build_sync_quality_report(
    total_frames: int,
    sync_errors_s: list[float],
) -> SyncQualityReport:
    matched = len(sync_errors_s)
    unmatched = total_frames - matched
    return SyncQualityReport(
        total_ultrasound_frames=total_frames,
        matched_frames=matched,
        unmatched_frames=unmatched,
        match_rate=(matched / total_frames) if total_frames else 0.0,
        median_sync_error_s=statistics.median(sync_errors_s) if sync_errors_s else None,
        max_sync_error_s=max(sync_errors_s) if sync_errors_s else None,
    )

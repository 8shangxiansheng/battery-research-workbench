from __future__ import annotations

from typing import Any, cast

from battery_workbench.ultrasound.qa.schemas import QAAnomaly, QAAnomalyRegion

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def anomaly(
    code: str,
    severity: str,
    scope: str,
    message: str,
    *,
    asset_id: str | None = None,
    frame_index_raw: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> QAAnomaly:
    return QAAnomaly(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        scope=scope,
        asset_id=asset_id,
        frame_index_raw=frame_index_raw,
        message=message,
        metrics=metrics or {},
    )


def status_from(anomalies: list[QAAnomaly]) -> str:
    if any(item.severity == "critical" for item in anomalies):
        return "FAIL"
    if any(item.severity == "warning" for item in anomalies):
        return "PASS_WITH_WARNINGS"
    return "PASS"


def aggregate_anomaly_regions(anomalies: list[QAAnomaly]) -> list[QAAnomalyRegion]:
    """Aggregate consecutive frame anomalies without changing source records."""
    grouped: dict[tuple[str, str], list[QAAnomaly]] = {}
    for item in anomalies:
        if item.asset_id is None or item.frame_index_raw is None:
            continue
        grouped.setdefault((item.code, item.asset_id), []).append(item)

    regions: list[QAAnomalyRegion] = []
    for (code, asset_id), items in sorted(grouped.items()):
        frame_ids = sorted({cast(int, item.frame_index_raw) for item in items})
        severity = max(items, key=lambda item: SEVERITY_ORDER[item.severity]).severity
        start = frame_ids[0]
        previous = start
        for frame_id in frame_ids[1:]:
            if frame_id != previous + 1:
                regions.append(_region(code, severity, asset_id, start, previous))
                start = frame_id
            previous = frame_id
        regions.append(_region(code, severity, asset_id, start, previous))
    return regions


def _region(
    code: str,
    severity: str,
    asset_id: str,
    start: int,
    end: int,
) -> QAAnomalyRegion:
    return QAAnomalyRegion(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        asset_id=asset_id,
        start_frame_index_raw=start,
        end_frame_index_raw=end,
        frame_count=end - start + 1,
    )

from __future__ import annotations

from collections.abc import Mapping

from battery_workbench.electrical.qa.schemas import QAAnomaly


def anomaly(
    code: str,
    severity: str,
    scope: str,
    message: str,
    *,
    count: int = 1,
    metadata: Mapping[str, object] | None = None,
) -> QAAnomaly:
    return QAAnomaly(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        scope=scope,
        message=message,
        count=count,
        metadata=dict(metadata or {}),
    )


def status_from(anomalies: list[QAAnomaly]) -> str:
    if any(item.severity == "critical" for item in anomalies):
        return "FAIL"
    if any(item.severity == "warning" for item in anomalies):
        return "PASS_WITH_WARNINGS"
    return "PASS"

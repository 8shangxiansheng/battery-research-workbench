from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly
from battery_workbench.electrical.qa.schemas import QAAnomaly


def analyze_steps(
    records: pd.DataFrame, steps: pd.DataFrame
) -> tuple[list[dict[str, Any]], list[QAAnomaly]]:
    needed = {"cycle_index_raw", "step_index_raw"}
    if not needed <= set(records.columns):
        return [], []
    record_pairs = set(records[list(needed)].dropna().itertuples(index=False, name=None))
    table_pairs = (
        set(steps[list(needed)].dropna().itertuples(index=False, name=None))
        if needed <= set(steps.columns)
        else set()
    )
    issues: list[QAAnomaly] = []
    if record_pairs != table_pairs:
        issues.append(
            anomaly(
                "STEP_ID_MISMATCH",
                "warning",
                "steps",
                "Record and step-table Cycle/Step pairs differ",
                metadata={
                    "record_only": sorted(record_pairs - table_pairs),
                    "table_only": sorted(table_pairs - record_pairs),
                },
            )
        )
    summaries: list[dict[str, Any]] = []
    for (cycle_id, step_id), group in records.groupby(
        ["cycle_index_raw", "step_index_raw"], sort=True
    ):
        timestamps = group["timestamp"]
        summary = {
            "cycle_index_raw": int(str(cycle_id)),
            "step_index_raw": int(str(step_id)),
            "step_type_raw": _first(group, "step_type_raw"),
            "start_timestamp": timestamps.min().isoformat(),
            "end_timestamp": timestamps.max().isoformat(),
            "records_count": len(group),
            "duration_s": float((timestamps.max() - timestamps.min()).total_seconds()),
            "current_min_a": _stat(group, "current_a", "min"),
            "current_max_a": _stat(group, "current_a", "max"),
            "current_median_a": _stat(group, "current_a", "median"),
            "voltage_min_v": _stat(group, "voltage_v", "min"),
            "voltage_max_v": _stat(group, "voltage_v", "max"),
            "capacity_start_ah": _edge(group, "capacity_ah", first=True),
            "capacity_end_ah": _edge(group, "capacity_ah", first=False),
        }
        summaries.append(summary)
        matching = (
            steps[(steps["cycle_index_raw"] == cycle_id) & (steps["step_index_raw"] == step_id)]
            if needed <= set(steps.columns)
            else pd.DataFrame()
        )
        if not matching.empty:
            row = matching.iloc[0]
            if "step_type_raw" in row and summary["step_type_raw"] != str(row["step_type_raw"]):
                issues.append(
                    anomaly(
                        "STEP_TYPE_MISMATCH",
                        "warning",
                        f"cycle:{int(str(cycle_id))}/step:{int(str(step_id))}",
                        "Record and step-table types differ",
                    )
                )
            if (
                "start_timestamp" in row
                and pd.Timestamp(row["start_timestamp"]) != timestamps.min()
            ):
                issues.append(
                    anomaly(
                        "STEP_TIME_MISMATCH",
                        "warning",
                        f"cycle:{int(str(cycle_id))}/step:{int(str(step_id))}",
                        "Step start timestamp differs",
                    )
                )
            if "end_timestamp" in row and pd.Timestamp(row["end_timestamp"]) != timestamps.max():
                issues.append(
                    anomaly(
                        "STEP_TIME_MISMATCH",
                        "warning",
                        f"cycle:{int(str(cycle_id))}/step:{int(str(step_id))}",
                        "Step end timestamp differs",
                    )
                )
    return summaries, issues


def _first(frame: pd.DataFrame, field: str) -> str | None:
    return str(frame[field].iloc[0]) if field in frame else None


def _stat(frame: pd.DataFrame, field: str, operation: str) -> float | None:
    if field not in frame:
        return None
    value = getattr(frame[field], operation)()
    return None if pd.isna(value) else float(value)


def _edge(frame: pd.DataFrame, field: str, *, first: bool) -> float | None:
    if field not in frame:
        return None
    value = frame[field].iloc[0 if first else -1]
    return None if pd.isna(value) else float(value)

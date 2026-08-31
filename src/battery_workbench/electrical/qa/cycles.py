from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly
from battery_workbench.electrical.qa.schemas import ElectricalQAConfig, QAAnomaly


def analyze_cycles(
    records: pd.DataFrame, cycles: pd.DataFrame, config: ElectricalQAConfig
) -> tuple[list[dict[str, Any]], list[QAAnomaly]]:
    if "cycle_index_raw" not in records:
        return [], []
    record_ids = set(records["cycle_index_raw"].dropna().astype(int))
    table_ids = (
        set(cycles["cycle_index_raw"].dropna().astype(int))
        if "cycle_index_raw" in cycles
        else set()
    )
    issues: list[QAAnomaly] = []
    if record_ids != table_ids:
        issues.append(
            anomaly(
                "CYCLE_ID_MISMATCH",
                "warning",
                "cycles",
                "Record and cycle-table IDs differ",
                metadata={"record_ids": sorted(record_ids), "table_ids": sorted(table_ids)},
            )
        )
    summaries: list[dict[str, Any]] = []
    indexed = (
        cycles.set_index("cycle_index_raw", drop=False)
        if "cycle_index_raw" in cycles
        else pd.DataFrame()
    )
    for cycle_id, group in records.groupby("cycle_index_raw", sort=True):
        table = indexed.loc[cycle_id] if not indexed.empty and cycle_id in indexed.index else None
        if isinstance(table, pd.DataFrame):
            table = table.iloc[0]
        charge = _sum_step_max(group, "charge_capacity_ah")
        discharge = _sum_step_max(group, "discharge_capacity_ah")
        summary = {
            "cycle_index_raw": int(str(cycle_id)),
            "start_timestamp": group["timestamp"].min().isoformat(),
            "end_timestamp": group["timestamp"].max().isoformat(),
            "records_count": len(group),
            "charge_capacity_ah": charge,
            "discharge_capacity_ah": discharge,
            "capacity_retention_percent": _table_number(table, "capacity_retention_percent"),
            "coulombic_efficiency_percent": _table_number(table, "coulombic_efficiency_percent"),
            "charge_energy_wh": _table_number(table, "charge_energy_wh"),
            "discharge_energy_wh": _table_number(table, "discharge_energy_wh"),
            "temperature_min_c": _table_number(table, "t1_min_temperature_c"),
            "temperature_max_c": _table_number(table, "t1_max_temperature_c"),
        }
        summaries.append(summary)
        if table is not None:
            for field, derived_time in (
                ("start_timestamp", group["timestamp"].min()),
                ("end_timestamp", group["timestamp"].max()),
            ):
                if field in table and pd.Timestamp(table[field]) != derived_time:
                    issues.append(
                        anomaly(
                            "CYCLE_TIME_MISMATCH",
                            "warning",
                            f"cycle:{int(str(cycle_id))}",
                            f"Derived {field} differs from cycle table",
                            metadata={
                                "derived": derived_time.isoformat(),
                                "table": pd.Timestamp(table[field]).isoformat(),
                            },
                        )
                    )
            for field, derived in (
                ("charge_capacity_ah", charge),
                ("discharge_capacity_ah", discharge),
            ):
                expected = _table_number(table, field)
                if (
                    expected is not None
                    and derived is not None
                    and not _close(derived, expected, config.cross_table.numeric_relative_tolerance)
                ):
                    issues.append(
                        anomaly(
                            "CYCLE_SUMMARY_MISMATCH",
                            "warning",
                            f"cycle:{int(str(cycle_id))}",
                            f"Derived {field} differs from cycle table",
                            metadata={"derived": derived, "table": expected},
                        )
                    )
    if {"start_timestamp", "end_timestamp"} <= set(cycles.columns):
        ordered = cycles.sort_values("start_timestamp")
        overlap_count = int(
            (
                ordered["start_timestamp"].iloc[1:].reset_index(drop=True)
                < ordered["end_timestamp"].iloc[:-1].reset_index(drop=True)
            ).sum()
        )
        if overlap_count:
            issues.append(
                anomaly(
                    "CYCLE_TIME_OVERLAP",
                    "warning",
                    "cycles",
                    "Cycle time ranges overlap",
                    count=overlap_count,
                )
            )
    return summaries, issues


def _sum_step_max(group: pd.DataFrame, field: str) -> float | None:
    if field not in group:
        return None
    return float(group.groupby("step_index_raw")[field].max().sum())


def _table_number(row: pd.Series[Any] | None, field: str) -> float | None:
    if row is None or field not in row or pd.isna(row[field]):
        return None
    return float(row[field])


def _close(left: float, right: float, tolerance: float) -> bool:
    scale = max(abs(left), abs(right), 1e-12)
    return abs(left - right) / scale <= tolerance

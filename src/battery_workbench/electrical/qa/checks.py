from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly
from battery_workbench.electrical.qa.schemas import ElectricalQAConfig, QAAnomaly

CORE_COMPLETENESS_COLUMNS = [
    "timestamp",
    "cycle_index_raw",
    "step_index_raw",
    "current_a",
    "voltage_v",
    "capacity_ah",
    "soc_dod_percent",
    "dqdv_mah_per_v",
    "contact_resistance_mohm",
]
OPTIONAL_RECORD_COLUMNS = ["soc_dod_percent", "dqdv_mah_per_v", "contact_resistance_mohm"]


def check_schema(
    records: pd.DataFrame, config: ElectricalQAConfig
) -> tuple[dict[str, Any], list[QAAnomaly]]:
    missing = sorted(set(config.required_columns) - set(records.columns))
    optional_missing = sorted(set(OPTIONAL_RECORD_COLUMNS) - set(records.columns))
    dtype_mismatches: dict[str, str] = {}
    if (
        "timestamp" in records
        and not isinstance(records["timestamp"].dtype, pd.DatetimeTZDtype)
        and not pd.api.types.is_datetime64_any_dtype(records["timestamp"])
    ):
        dtype_mismatches["timestamp"] = str(records["timestamp"].dtype)
    issues = (
        [
            anomaly(
                "MISSING_REQUIRED_COLUMN",
                "critical",
                "records",
                f"Missing required records columns: {missing}",
                count=len(missing),
                metadata={"columns": missing},
            )
        ]
        if missing
        else []
    )
    if dtype_mismatches:
        issues.append(
            anomaly(
                "DTYPE_MISMATCH",
                "critical",
                "records",
                "Critical dtype mismatch",
                metadata=dtype_mismatches,
            )
        )
    return {
        "schema_status": "FAIL" if missing or dtype_mismatches else "PASS",
        "missing_required_columns": missing,
        "missing_optional_columns": optional_missing,
        "dtype_mismatches": dtype_mismatches,
    }, issues


def completeness(frames: dict[str, pd.DataFrame | None]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, frame in frames.items():
        if frame is None:
            result[name] = {"available": False, "row_count": 0, "columns": {}}
            continue
        columns: dict[str, dict[str, float | int]] = {}
        for column in frame.columns:
            count = int(frame[column].isna().sum())
            columns[column] = {
                "null_count": count,
                "null_ratio": count / len(frame) if len(frame) else 0.0,
            }
        result[name] = {"available": True, "row_count": len(frame), "columns": columns}
    return result


def physical_ranges(
    records: pd.DataFrame,
    aux_temperature: pd.DataFrame | None,
    config: ElectricalQAConfig,
) -> tuple[dict[str, Any], list[QAAnomaly]]:
    output: dict[str, Any] = {}
    issues: list[QAAnomaly] = []
    for field, bounds in config.physical_bounds.items():
        series: pd.Series[Any] | None = None
        scope = "records"
        if field == "temperature_c":
            if aux_temperature is not None and field in aux_temperature:
                series = aux_temperature[field]
                scope = "aux_temperature"
        elif field in records:
            series = records[field]
        if series is None:
            output[field] = {"available": False, "min": None, "max": None, "outlier_count": 0}
            continue
        numeric = pd.to_numeric(series, errors="coerce")
        outliers = (numeric < bounds.min) | (numeric > bounds.max)
        count = int(outliers.sum())
        output[field] = {
            "available": True,
            "min": _number(numeric.min()),
            "max": _number(numeric.max()),
            "configured_min": bounds.min,
            "configured_max": bounds.max,
            "outlier_count": count,
        }
        if count:
            issues.append(
                anomaly(
                    "PHYSICAL_RANGE_OUTLIER",
                    "warning",
                    scope,
                    f"{field} has {count} values outside configured engineering bounds",
                    count=count,
                    metadata={"field": field, "min": bounds.min, "max": bounds.max},
                )
            )
    return output, issues


def _number(value: Any) -> float | None:
    return None if pd.isna(value) else float(value)

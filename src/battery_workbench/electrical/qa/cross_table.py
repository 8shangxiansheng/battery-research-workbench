from __future__ import annotations

from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly
from battery_workbench.electrical.qa.schemas import ElectricalQAConfig, QAAnomaly


def analyze_cross_table(
    records: pd.DataFrame,
    cycles: pd.DataFrame,
    steps: pd.DataFrame,
    aux_tables: dict[str, pd.DataFrame | None],
    config: ElectricalQAConfig,
) -> tuple[dict[str, Any], list[QAAnomaly]]:
    result: dict[str, Any] = {
        "records_cycles": _id_coverage(records, cycles, ["cycle_index_raw"]),
        "records_steps": _id_coverage(records, steps, ["cycle_index_raw", "step_index_raw"]),
    }
    issues: list[QAAnomaly] = []
    for name, aux in aux_tables.items():
        if aux is None:
            result[name] = {
                "available": False,
                "row_count": 0,
                "record_key_coverage": 0.0,
                "exact_timestamp_match_rate": 0.0,
                "nearest_timestamp_match_rate": 0.0,
            }
            issues.append(
                anomaly(
                    "OPTIONAL_TABLE_MISSING",
                    "warning",
                    name,
                    f"Optional {name} table is unavailable",
                )
            )
            continue
        keys = ["electrical_asset_id", "record_index_raw"]
        record_keys = records[keys].drop_duplicates()
        aux_keys = aux[keys].drop_duplicates()
        merged = record_keys.merge(aux_keys, on=keys, how="left", indicator=True)
        coverage = float((merged["_merge"] == "both").mean()) if len(merged) else 0.0
        joined = records[keys + ["timestamp"]].merge(
            aux[keys + ["timestamp"]], on=keys, how="left", suffixes=("_record", "_aux")
        )
        valid = joined["timestamp_aux"].notna()
        if valid.any():
            record_time = pd.to_datetime(joined.loc[valid, "timestamp_record"])
            aux_time = pd.to_datetime(joined.loc[valid, "timestamp_aux"])
            delta = (record_time - aux_time).abs().dt.total_seconds()
        else:
            delta = pd.Series(dtype=float)
        exact = float((delta == 0).mean()) if len(delta) else 0.0
        nearest = (
            float((delta <= config.cross_table.timestamp_tolerance_s).mean()) if len(delta) else 0.0
        )
        result[name] = {
            "available": True,
            "row_count": len(aux),
            "record_key_coverage": coverage,
            "exact_timestamp_match_rate": exact,
            "nearest_timestamp_match_rate": nearest,
            "missing_record_keys": int((merged["_merge"] != "both").sum()),
        }
        if coverage < 1.0 or nearest < 1.0:
            issues.append(
                anomaly(
                    "AUX_COVERAGE_MISMATCH",
                    "warning",
                    name,
                    f"{name} does not fully cover record keys/timestamps",
                    metadata={
                        "record_key_coverage": coverage,
                        "nearest_timestamp_match_rate": nearest,
                    },
                )
            )
    return result, issues


def _id_coverage(records: pd.DataFrame, summary: pd.DataFrame, keys: list[str]) -> dict[str, Any]:
    if not set(keys) <= set(records.columns) or not set(keys) <= set(summary.columns):
        return {
            "available": False,
            "record_id_coverage": 0.0,
            "missing_ids": [],
            "extra_ids": [],
        }
    record_ids = set(records[keys].drop_duplicates().itertuples(index=False, name=None))
    summary_ids = set(summary[keys].drop_duplicates().itertuples(index=False, name=None))
    coverage = len(record_ids & summary_ids) / len(record_ids) if record_ids else 0.0
    return {
        "available": True,
        "record_id_coverage": coverage,
        "missing_ids": [_plain(values) for values in sorted(record_ids - summary_ids)],
        "extra_ids": [_plain(values) for values in sorted(summary_ids - record_ids)],
    }


def _plain(values: tuple[Any, ...]) -> list[Any]:
    return [value.item() if hasattr(value, "item") else value for value in values]

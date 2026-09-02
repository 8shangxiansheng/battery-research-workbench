"""BRW-021 candidate feature resolution.

Locators: feature_name or feature_name@gate_id. Core / AUXILIARY / GATED
roles follow BRW-017/018 semantics; no new feature names are created.
TOF unavailability is reported honestly, never forged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

CORE_FEATURES = ["tof_us", "amplitude_a_u"]
DERIVED_FEATURES = ["wave_speed_m_s"]
TOF_BLOCK_REASON = "tof_status=BLOCKED (arrival detector semantics; never forged)"


def parse_locator(locator: str) -> tuple[str, str | None]:
    if "@" in locator:
        name, gate_id = locator.split("@", 1)
        return name, gate_id
    return locator, None


def resolve_candidates(
    locators: list[str], frame: pd.DataFrame, *, mode: str
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for locator in locators:
        name, gate_id = parse_locator(locator)
        if gate_id is not None:
            column = f"{name}@{gate_id}"
            available = column in frame.columns and frame[column].notna().any()
            resolved.append(
                {
                    "feature_name": name,
                    "locator": locator,
                    "gate_id": gate_id,
                    "role": "GATED",
                    "status": "AVAILABLE" if available else "MISSING_COLUMN",
                    "reason": "" if available else f"column {column!r} not in analysis frame",
                }
            )
            continue
        if name in CORE_FEATURES:
            role = "CORE"
        elif name in DERIVED_FEATURES:
            role = "DERIVED"
        else:
            role = "AUXILIARY"
        available = name in frame.columns and frame[name].notna().any()
        entry: dict[str, Any] = {
            "feature_name": name,
            "locator": locator,
            "gate_id": None,
            "role": role,
            "status": "AVAILABLE" if available else "UNAVAILABLE",
            "reason": "",
        }
        if not available:
            entry["reason"] = (
                TOF_BLOCK_REASON
                if name in ("tof_us", "wave_speed_m_s")
                else f"column {name!r} missing or all-null in analysis frame"
            )
        resolved.append(entry)
    return resolved


def columns_for(resolved: list[dict[str, Any]]) -> list[str]:
    """Locator columns actually usable for analysis."""
    return [r["locator"] for r in resolved if r["status"] == "AVAILABLE"]

"""BRW-018 gated feature-label analysis.

Joins gated candidate features (grain: measurement_event_id × gate_id) with
SOC/SOH reference labels on measurement_event_id (exact join). Gated feature
columns are exposed with ``feature_name@gate_id`` locators — no new feature
names are invented.
"""

from __future__ import annotations

import pandas as pd

from battery_workbench.datasets.joins import exact_event_join

# Label columns carried into the gated analysis table.
_LABEL_COLUMNS = ["soc_reference_percent", "soh_capacity_reference_percent"]
_IDENTITY_COLUMNS = [
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "cycle_index_raw",
]


def gated_locator(feature_name: str, gate_id: str) -> str:
    """Canonical gated feature locator: feature_name@gate_id."""
    return f"{feature_name}@{gate_id}"


def delay_locator(reference_gate_id: str, received_gate_id: str) -> str:
    """Between-gate delay locator: delay_us@<ref_gate_id>><<rcv_gate_id>."""
    return f"delay_us@{reference_gate_id}>{received_gate_id}"


def build_gated_feature_label_analysis(
    *,
    gated_features: pd.DataFrame,
    event_labels: pd.DataFrame,
    cycle_labels: pd.DataFrame | None = None,
    event_grain: bool = False,
) -> pd.DataFrame:
    """Exact-join gated features with reference labels.

    ``gated_features`` grain is measurement_event_id × gate_id unless
    ``event_grain=True`` (one row per event, locator columns).
    """
    gated = gated_features.copy()
    if not event_grain:
        # Pivot gate-grain rows into one row per event with locator columns.
        feature_cols = [
            c
            for c in gated.columns
            if c not in ("measurement_event_id", "gate_id", "gate_name")
            and not c.startswith("gate_")
        ]
        pivots = []
        for col in feature_cols:
            sub = gated[["measurement_event_id", "gate_id", col]].copy()
            sub["loc"] = sub["gate_id"].map(lambda g, _c=col: gated_locator(_c, str(g)))
            sub = sub.pivot(index="measurement_event_id", columns="loc", values=col)
            pivots.append(sub)
        gated = pd.concat(pivots, axis=1).reset_index()
    else:
        # One row per event with a single gate_id column → locator columns.
        if "gate_id" in gated.columns:
            gate_id = str(gated["gate_id"].iloc[0])
            feature_cols = [
                c
                for c in gated.columns
                if c not in ("measurement_event_id", "gate_id", "gate_name")
                and not c.startswith("gate_")
            ]
            gated = gated.copy()
            for col in feature_cols:
                gated.rename(columns={col: gated_locator(col, gate_id)}, inplace=True)

    joined = exact_event_join(gated, event_labels)
    if isinstance(joined, tuple):  # pragma: no cover - report_surplus=False
        raise TypeError("exact_event_join returned unexpected tuple")
    if cycle_labels is not None:
        from battery_workbench.datasets.joins import exact_cycle_join

        joined = exact_cycle_join(joined, cycle_labels)

    keep: list[str] = []
    for col in _IDENTITY_COLUMNS + _LABEL_COLUMNS:
        if col in joined.columns and col not in keep:
            keep.append(col)
    locator_cols = [c for c in joined.columns if "@" in c]
    keep.extend(locator_cols)
    return joined[keep].copy()

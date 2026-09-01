"""Exact-join primitives for BRW-016.

Join keys: ``measurement_event_id`` (event grain) and
``battery_id + experiment_id + cycle_index_raw`` (cycle grain). No timestamp,
row-position, or nearest matching anywhere.
"""

from __future__ import annotations

import pandas as pd


class DatasetIntegrityError(ValueError):
    """Raised for duplicate keys, missing required labels, or non-unique cycle keys."""


def _assert_unique(df: pd.DataFrame, key: str, side: str) -> None:
    dups = df[key].duplicated().sum()
    if dups:
        raise DatasetIntegrityError(f"duplicate {key} in {side}: {dups} rows")


def exact_event_join(
    features: pd.DataFrame,
    event_labels: pd.DataFrame,
    *,
    report_surplus: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, int]:
    """Inner-join features to event labels on ``measurement_event_id``.

    Duplicate keys on either side are integrity failures. Features without a
    label row are integrity failures (every feature must carry a label).
    Surplus labels (labels without features) are reported as a count, not a
    failure, because BRW-014 intentionally covers all 3999 events while
    features exist only for eligible slice events.
    """
    _assert_unique(features, "measurement_event_id", "features")
    _assert_unique(event_labels, "measurement_event_id", "event_labels")

    missing = set(features["measurement_event_id"]) - set(event_labels["measurement_event_id"])
    if missing:
        raise DatasetIntegrityError(
            f"missing required event labels for {len(missing)} feature rows (e.g. {sorted(missing)[:3]})"
        )
    surplus = len(set(event_labels["measurement_event_id"]) - set(features["measurement_event_id"]))

    merged = features.merge(
        event_labels, on="measurement_event_id", how="inner", suffixes=("", "_label")
    )
    if report_surplus:
        return merged, surplus
    return merged


def exact_cycle_join(
    events: pd.DataFrame,
    cycle_labels: pd.DataFrame,
) -> pd.DataFrame:
    """Attach cycle-level labels by the exact three-part cycle key."""
    key_cols = ["battery_id", "experiment_id", "cycle_index_raw"]
    if cycle_labels[key_cols].duplicated().any():
        raise DatasetIntegrityError("non-unique cycle key in cycle_labels")
    # Drop cycle-label columns that would collide with event columns, but keep
    # the join key columns and cycle-specific label columns.
    keep = set(key_cols) | {
        "soh_capacity_reference_percent",
        "soh_reference_cycle_index",
        "soh_reference_quality",
        "soh_label_eligible",
    }
    cycles = cycle_labels[[c for c in cycle_labels.columns if c in keep]]
    return events.merge(cycles, on=key_cols, how="left", suffixes=("", "_cycle"))

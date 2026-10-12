"""Identity-safe joins between canonical MeasurementEvents and event labels."""

from __future__ import annotations

import pandas as pd

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.multimodal.event_id import (
    MeasurementEventIdentityError,
    validate_measurement_event_ids,
)


def merge_event_labels(events: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Left-join labels while preserving one row per valid MeasurementEvent.

    Event labels may cover only a subset of events, so this is a left join.
    Duplicate, blank, non-string, or untrimmed identities are integrity errors;
    they must never inflate or silently alter scientific denominators.
    """
    for artifact_name, frame in (("MeasurementEvent", events), ("event labels", labels)):
        if "measurement_event_id" not in frame.columns:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                f"{artifact_name} artifact is missing measurement_event_id",
                {
                    "artifact": artifact_name,
                    "integrity_reasons": ["MEASUREMENT_EVENT_ID_COLUMN_MISSING"],
                },
            )
        try:
            validate_measurement_event_ids(
                frame["measurement_event_id"].tolist(), artifact_name=artifact_name
            )
        except MeasurementEventIdentityError as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                str(exc),
                {
                    "artifact": artifact_name,
                    "integrity_reasons": [exc.reason_code],
                },
            ) from exc

    try:
        joined = events.merge(
            labels,
            on="measurement_event_id",
            how="left",
            suffixes=("", "_label"),
            validate="one_to_one",
        )
    except pd.errors.MergeError as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "MeasurementEvent and label artifacts do not form a one-to-one join",
            {"integrity_reasons": ["MEASUREMENT_EVENT_LABEL_JOIN_NOT_ONE_TO_ONE"]},
        ) from exc
    if len(joined) != len(events):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "label join changed MeasurementEvent cardinality",
            {
                "integrity_reasons": ["MEASUREMENT_EVENT_LABEL_JOIN_CARDINALITY_CHANGED"],
                "expected_rows": len(events),
                "observed_rows": len(joined),
            },
        )
    return joined

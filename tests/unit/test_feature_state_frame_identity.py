from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.routes.features_v2 import (
    _align_event_series_to_frame_metadata,
    _align_feature_series_to_event_frames,
)


def _events(identities: list[tuple[str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ultrasound_asset_id": asset_id,
                "frame_index_raw": frame_index,
            }
            for asset_id, frame_index in identities
        ]
    )


def test_aligns_waveform_series_by_asset_and_frame_not_row_order() -> None:
    events = _events([("U002", 0), ("U001", 0), ("U001", 1)])
    frame_metadata = _events([("U001", 0), ("U001", 1), ("U002", 0)])

    aligned = _align_feature_series_to_event_frames(
        events, frame_metadata, np.asarray([10.0, 11.0, 20.0])
    )

    np.testing.assert_array_equal(aligned, [20.0, 10.0, 11.0])


def test_aligns_event_series_back_to_waveform_metadata_order() -> None:
    events = _events([("U002", 0), ("U001", 0), ("U001", 1)])
    frame_metadata = _events([("U001", 0), ("U001", 1), ("U002", 0)])

    aligned = _align_event_series_to_frame_metadata(
        events, frame_metadata, np.asarray([20.0, 10.0, 11.0])
    )

    np.testing.assert_array_equal(aligned, [10.0, 11.0, 20.0])


@pytest.mark.parametrize(
    ("events", "frames", "values", "reason"),
    [
        (
            _events([("U001", 0), ("U001", 0)]),
            _events([("U001", 0), ("U001", 1)]),
            np.asarray([1.0, 2.0]),
            "MEASUREMENT_EVENT_FRAME_IDENTITY_DUPLICATE",
        ),
        (
            _events([("U001", 0), ("U001", 2)]),
            _events([("U001", 0), ("U001", 1)]),
            np.asarray([1.0, 2.0]),
            "FRAME_EVENT_IDENTITY_SET_MISMATCH",
        ),
        (
            _events([("U001", 0)]),
            _events([("U001", 0), ("U001", 1)]),
            np.asarray([1.0, 2.0]),
            "FRAME_EVENT_ROW_COUNT_MISMATCH",
        ),
    ],
)
def test_rejects_untrustworthy_frame_event_correspondence(
    events: pd.DataFrame,
    frames: pd.DataFrame,
    values: np.ndarray,
    reason: str,
) -> None:
    with pytest.raises(APIError) as exc_info:
        _align_feature_series_to_event_frames(events, frames, values)

    assert exc_info.value.details["integrity_reasons"] == [reason]


def test_rejects_missing_identity_columns() -> None:
    with pytest.raises(APIError) as exc_info:
        _align_feature_series_to_event_frames(
            pd.DataFrame({"measurement_event_id": ["ME1"]}),
            _events([("U001", 0)]),
            np.asarray([1.0]),
        )

    assert exc_info.value.details["integrity_reasons"] == [
        "FRAME_EVENT_IDENTITY_COLUMNS_MISSING"
    ]

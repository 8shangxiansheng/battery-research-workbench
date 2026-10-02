from __future__ import annotations

import pandas as pd
import pytest

from battery_workbench.features_physical.canonical_tof import canonical_tof_values_by_event


def test_canonical_tof_values_join_by_measurement_event_not_local_frame_index() -> None:
    rows = pd.DataFrame(
        {
            "measurement_event_id": ["ME::U1::0", "ME::U2::0", "ME::U2::1"],
            "frame_index_raw": [0, 0, 1],
            "tof_us": [10.0, 20.0, None],
            "tof_status": ["VALID", "VALID", "BLOCKED"],
        }
    )

    assert canonical_tof_values_by_event(
        ["ME::U2::0", "ME::U1::0", "ME::missing", "ME::U2::1"], rows
    ) == [20.0, 10.0, None, None]


def test_canonical_tof_values_reject_duplicate_event_identity() -> None:
    rows = pd.DataFrame(
        {
            "measurement_event_id": ["ME::U1::0", "ME::U1::0"],
            "tof_us": [10.0, 11.0],
            "tof_status": ["VALID", "VALID"],
        }
    )

    with pytest.raises(ValueError, match="duplicate MeasurementEvent"):
        canonical_tof_values_by_event(["ME::U1::0"], rows)

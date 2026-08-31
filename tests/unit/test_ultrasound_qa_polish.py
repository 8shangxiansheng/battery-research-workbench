from __future__ import annotations

from matplotlib import pyplot as plt

from battery_workbench.ultrasound.qa.anomalies import (
    aggregate_anomaly_regions,
    anomaly,
)
from battery_workbench.ultrasound.qa.figures import (
    configure_correlation_axis,
    select_frame_ids,
)


def test_correlation_axis_displays_full_values_without_offset() -> None:
    figure, axis = plt.subplots()
    axis.plot([0, 1], [0.99996, 0.99999])
    configure_correlation_axis(axis)
    figure.canvas.draw()
    labels = [item.get_text() for item in axis.get_yticklabels()]
    assert axis.yaxis.get_offset_text().get_text() == ""
    assert any(label.startswith("0.9999") for label in labels)
    plt.close(figure)


def test_current_baseline_uses_exact_golden_frame_ids() -> None:
    assert select_frame_ids(range(3999)) == [0, 1000, 2000, 3000, 3998]


def test_selected_frame_ids_fall_back_to_actual_quartile_frames() -> None:
    assert select_frame_ids([10, 20, 30, 40, 50, 60, 70, 80, 90]) == [
        10,
        30,
        50,
        70,
        90,
    ]


def _frame_anomaly(code: str, asset_id: str, frame_index: int):
    return anomaly(
        code,
        "warning",
        "frame",
        "synthetic",
        asset_id=asset_id,
        frame_index_raw=frame_index,
    )


def test_contiguous_anomalies_form_one_region_without_mutating_source() -> None:
    anomalies = [_frame_anomaly("RMS_OUTLIER", "U1", index) for index in [0, 1, 2, 3]]
    original_count = len(anomalies)
    regions = aggregate_anomaly_regions(anomalies)
    assert len(anomalies) == original_count
    assert [region.model_dump() for region in regions] == [
        {
            "code": "RMS_OUTLIER",
            "severity": "warning",
            "asset_id": "U1",
            "start_frame_index_raw": 0,
            "end_frame_index_raw": 3,
            "frame_count": 4,
        }
    ]


def test_anomaly_gap_splits_regions() -> None:
    anomalies = [_frame_anomaly("RMS_OUTLIER", "U1", index) for index in [0, 1, 5, 6, 7]]
    regions = aggregate_anomaly_regions(anomalies)
    assert [
        (region.start_frame_index_raw, region.end_frame_index_raw, region.frame_count)
        for region in regions
    ] == [(0, 1, 2), (5, 7, 3)]


def test_anomaly_regions_group_by_code_and_asset() -> None:
    anomalies = [
        _frame_anomaly("RMS_OUTLIER", "U1", 1),
        _frame_anomaly("P2P_OUTLIER", "U1", 1),
        _frame_anomaly("RMS_OUTLIER", "U2", 1),
    ]
    regions = aggregate_anomaly_regions(anomalies)
    assert {(region.code, region.asset_id) for region in regions} == {
        ("RMS_OUTLIER", "U1"),
        ("P2P_OUTLIER", "U1"),
        ("RMS_OUTLIER", "U2"),
    }


def test_non_frame_anomalies_do_not_create_regions() -> None:
    anomalies = [anomaly("LARGE_FRAME_GAP", "warning", "asset", "synthetic")]
    assert aggregate_anomaly_regions(anomalies) == []

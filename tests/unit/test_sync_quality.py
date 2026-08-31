import pytest

from battery_workbench.synchronization.quality import build_sync_quality_report


def test_sync_quality_report() -> None:
    report = build_sync_quality_report(4, [0.03, 0.04, 0.02])

    assert report.matched_frames == 3
    assert report.unmatched_frames == 1
    assert report.match_rate == pytest.approx(0.75)
    assert report.median_sync_error_s == pytest.approx(0.03)
    assert report.max_sync_error_s == pytest.approx(0.04)

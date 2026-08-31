from datetime import datetime, timedelta

from battery_workbench.synchronization.boundary import is_near_boundary


def test_boundary_flag() -> None:
    boundary = datetime(2024, 1, 1, 10, 0, 0)

    assert is_near_boundary(boundary + timedelta(seconds=0.7), [boundary], tolerance_s=1.0)
    assert not is_near_boundary(boundary + timedelta(seconds=2.0), [boundary], tolerance_s=1.0)

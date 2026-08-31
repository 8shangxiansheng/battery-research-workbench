from datetime import datetime, timedelta

from battery_workbench.synchronization.align import nearest_timestamp_index


def test_nearest_timestamp_index() -> None:
    start = datetime(2024, 1, 1, 10, 0, 0)
    electrical = [start + timedelta(seconds=i) for i in range(20)]
    target = start + timedelta(seconds=10.031)

    idx, error = nearest_timestamp_index(target, electrical)

    assert idx == 10
    assert error == 0.031

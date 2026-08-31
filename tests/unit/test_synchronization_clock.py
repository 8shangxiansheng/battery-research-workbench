from datetime import datetime

from battery_workbench.synchronization.clock import elapsed_to_absolute


def test_elapsed_to_absolute() -> None:
    start = datetime(2024, 1, 6, 9, 52, 31)
    result = elapsed_to_absolute(start, 10.031217)

    assert result == datetime(2024, 1, 6, 9, 52, 41, 31217)

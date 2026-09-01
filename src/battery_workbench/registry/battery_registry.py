from __future__ import annotations

from battery_workbench.domain.battery import BatteryCell


class BatteryRegistry:
    def __init__(self, batteries: list[BatteryCell]) -> None:
        self._items = {x.battery_id: x for x in batteries}

    def list_batteries(self) -> list[BatteryCell]:
        return list(self._items.values())

    def get(self, battery_id: str) -> BatteryCell:
        return self._items[battery_id]

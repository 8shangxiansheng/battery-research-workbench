from __future__ import annotations

from battery_workbench.domain.experiment import Experiment


class ExperimentRegistry:
    def __init__(self, experiments: list[Experiment]) -> None:
        self._items = {x.experiment_id: x for x in experiments}

    def list_for_battery(self, battery_id: str) -> list[Experiment]:
        return [x for x in self._items.values() if x.battery_id == battery_id]

    def get(self, experiment_id: str) -> Experiment:
        return self._items[experiment_id]

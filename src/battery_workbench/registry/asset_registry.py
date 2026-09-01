from __future__ import annotations

from battery_workbench.domain.asset import DataAsset


class AssetRegistry:
    def __init__(self, assets: list[DataAsset]) -> None:
        self._items = {x.asset_id: x for x in assets}

    def list_for_experiment(self, experiment_id: str) -> list[DataAsset]:
        return [x for x in self._items.values() if x.experiment_id == experiment_id]

    def list_by_modality(self, experiment_id: str, modality: str) -> list[DataAsset]:
        return [
            x for x in self._items.values()
            if x.experiment_id == experiment_id and x.modality == modality
        ]

    def get(self, asset_id: str) -> DataAsset:
        return self._items[asset_id]

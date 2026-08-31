"""Modality -> DataAdapter registry for BRW-007.

A ``DataAdapterRegistry`` maps a modality string to the adapter that owns it.
It never uses ``if/elif`` dispatch; lookup is a plain dict read. Adding a new
modality requires only registering a new adapter, not editing the importer.
"""

from __future__ import annotations

from battery_workbench.io.adapters.base import DataAdapter


class DuplicateAdapterRegistrationError(ValueError):
    """Raised when two adapters claim the same modality."""

    def __init__(self, modality: str) -> None:
        self.modality = modality
        super().__init__(f"duplicate adapter registration for modality: {modality}")


class UnknownModalityError(KeyError):
    """Raised when no adapter is registered for a requested modality."""

    def __init__(self, modality: str) -> None:
        self.modality = modality
        super().__init__(f"no adapter registered for modality: {modality}")


class DataAdapterRegistry:
    """Owns the modality -> adapter mapping."""

    def __init__(self) -> None:
        self._adapters: dict[str, DataAdapter] = {}

    def register(self, adapter: DataAdapter) -> None:
        modality = adapter.modality
        if modality in self._adapters:
            raise DuplicateAdapterRegistrationError(modality)
        self._adapters[modality] = adapter

    def get(self, modality: str) -> DataAdapter:
        if modality not in self._adapters:
            raise UnknownModalityError(modality)
        return self._adapters[modality]

    def has(self, modality: str) -> bool:
        return modality in self._adapters

    def modalities(self) -> list[str]:
        return list(self._adapters.keys())


def build_default_adapter_registry() -> DataAdapterRegistry:
    """A registry pre-populated with the built-in electrical and ultrasound adapters."""
    from battery_workbench.io.adapters.electrical import ElectricalAdapter
    from battery_workbench.io.adapters.ultrasound import UltrasoundAdapter

    registry = DataAdapterRegistry()
    registry.register(ElectricalAdapter())
    registry.register(UltrasoundAdapter())
    return registry

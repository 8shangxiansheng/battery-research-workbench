"""DataAdapter contract, registry, and built-in modality adapters."""

from battery_workbench.io.adapters.base import DataAdapter
from battery_workbench.io.adapters.electrical import ElectricalAdapter
from battery_workbench.io.adapters.registry import (
    DataAdapterRegistry,
    DuplicateAdapterRegistrationError,
    UnknownModalityError,
    build_default_adapter_registry,
)
from battery_workbench.io.adapters.ultrasound import UltrasoundAdapter

__all__ = [
    "DataAdapter",
    "DataAdapterRegistry",
    "DuplicateAdapterRegistrationError",
    "ElectricalAdapter",
    "UltrasoundAdapter",
    "UnknownModalityError",
    "build_default_adapter_registry",
]

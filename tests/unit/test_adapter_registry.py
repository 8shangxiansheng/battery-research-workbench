from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.adapters import (
    DataAdapter,
    DataAdapterRegistry,
    DuplicateAdapterRegistrationError,
    UnknownModalityError,
    build_default_adapter_registry,
)
from battery_workbench.io.experiment.schemas import ModalityImportResult


class FakeAdapter:
    """Structural stand-in for the DataAdapter Protocol."""

    def __init__(self, modality: str, *, name: str | None = None) -> None:
        self.modality = modality
        self.adapter_name = name or f"Fake{modality.capitalize()}Adapter"
        self.adapter_version = "0.0.1"

    def supports(self, asset: DataAsset) -> bool:
        return asset.modality == self.modality

    def expected_output_paths(
        self, processed_root: Path, battery_id: str, experiment_id: str
    ) -> list[Path]:
        return [Path(processed_root) / self.modality / battery_id / experiment_id]

    def import_assets(
        self,
        *,
        battery,
        experiment,
        assets: list[DataAsset],
        raw_root: Path,
        processed_root: Path,
        overwrite: bool = False,
    ) -> ModalityImportResult:
        return ModalityImportResult(
            modality=self.modality,
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            asset_ids=[asset.asset_id for asset in assets],
            status="SUCCESS",
        )


def test_fake_adapter_satisfies_protocol() -> None:
    """T01: a structurally-compatible adapter satisfies the DataAdapter contract."""
    fake = FakeAdapter("test_modality")
    assert isinstance(fake, DataAdapter)


def test_registry_register_and_get() -> None:
    """T02: register and retrieve by modality."""
    registry = DataAdapterRegistry()
    adapter = FakeAdapter("electrical")
    registry.register(adapter)

    assert registry.get("electrical") is adapter
    assert registry.has("electrical")
    assert "electrical" in registry.modalities()


def test_duplicate_registration_raises() -> None:
    """T03: registering a second adapter for the same modality fails clearly."""
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))

    with pytest.raises(DuplicateAdapterRegistrationError) as excinfo:
        registry.register(FakeAdapter("electrical"))
    assert "electrical" in str(excinfo.value)


def test_unknown_modality_lookup_raises() -> None:
    """T04: requesting an unregistered modality raises an explicit error."""
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))

    with pytest.raises(UnknownModalityError) as excinfo:
        registry.get("ultrasound")
    assert "ultrasound" in str(excinfo.value)


def test_default_registry_has_electrical_and_ultrasound() -> None:
    """T05: the default registry ships electrical and ultrasound."""
    registry = build_default_adapter_registry()
    assert registry.has("electrical")
    assert registry.has("ultrasound")
    assert set(registry.modalities()) == {"electrical", "ultrasound"}

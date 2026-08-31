"""The ``DataAdapter`` contract for BRW-007.

A ``DataAdapter`` owns one modality. It does **not** implement parsing: it
delegates to the existing BRW-003 (electrical) / BRW-005 (ultrasound) parser
services, normalizes the outcome into a ``ModalityImportResult``, and decides
whether an output already exists.

Using a ``typing.Protocol`` (not an ABC) lets a test ``FakeAdapter`` satisfy
the contract structurally, with no inheritance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.battery import BatteryCell
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.experiment.schemas import ModalityImportResult


@runtime_checkable
class DataAdapter(Protocol):
    """Owns parsing/delegation for exactly one data modality."""

    modality: str
    """Canonical modality string this adapter serves."""

    adapter_name: str
    """Human-readable adapter identifier (e.g. ``ElectricalAdapter``)."""

    adapter_version: str
    """Semantic version of this adapter wrapping layer."""

    def supports(self, asset: DataAsset) -> bool:
        """Whether this adapter owns the given asset's modality."""
        ...

    def expected_output_paths(
        self,
        processed_root: Path,
        battery_id: str,
        experiment_id: str,
    ) -> list[Path]:
        """Predict output locations without writing anything."""
        ...

    def import_assets(
        self,
        *,
        battery: BatteryCell,
        experiment: Experiment,
        assets: list[DataAsset],
        raw_root: Path,
        processed_root: Path,
        overwrite: bool = False,
    ) -> ModalityImportResult:
        """Import all assets of one modality for one experiment.

        Granularity is *Experiment + modality + multiple assets*: one call
        handles every asset of a single modality in an experiment.
        """
        ...

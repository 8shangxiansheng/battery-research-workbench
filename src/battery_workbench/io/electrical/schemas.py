from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.electrical.custom_excel import SheetInfo


@dataclass
class ElectricalAssetParseResult:
    battery_id: str
    asset: DataAsset
    source_path: Path
    source_sha256: str
    sheets_found: dict[str, SheetInfo]
    column_mappings: dict[str, dict[str, str]]
    records: pd.DataFrame
    cycles: pd.DataFrame
    steps: pd.DataFrame
    aux_temperature: pd.DataFrame | None = None
    aux_voltage: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ElectricalExperimentParseResult:
    experiment: Experiment
    assets: list[DataAsset]
    asset_results: list[ElectricalAssetParseResult]
    records: pd.DataFrame
    cycles: pd.DataFrame
    steps: pd.DataFrame
    aux_temperature: pd.DataFrame | None = None
    aux_voltage: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def battery_id(self) -> str:
        return self.experiment.battery_id

    @property
    def experiment_id(self) -> str:
        return self.experiment.experiment_id


@dataclass(frozen=True)
class ElectricalOutputManifest:
    output_dir: Path
    manifest_path: Path
    output_files: dict[str, Path]

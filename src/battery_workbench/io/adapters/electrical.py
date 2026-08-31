"""Electrical adapter for BRW-007.

Purely a wrapper around the existing BRW-003 electrical parser service. It does
not re-implement openpyxl reading, column mapping, cycle/step parsing, or the
Parquet writer.
"""

from __future__ import annotations

from pathlib import Path

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.battery import BatteryCell
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.electrical.service import (
    parse_electrical_experiment,
    write_electrical_experiment,
)
from battery_workbench.io.experiment.schemas import (
    AssetImportResult,
    AssetImportStatus,
    ImportError,
    ImportStatus,
    ModalityImportResult,
)

_OUTPUT_MARKER = "parser_manifest.json"


class ElectricalAdapter:
    """Owns the ``electrical`` modality; delegates to the BRW-003 service."""

    modality = "electrical"
    adapter_name = "ElectricalAdapter"
    adapter_version = "0.1.0"

    def supports(self, asset: DataAsset) -> bool:
        return asset.modality == self.modality

    def expected_output_paths(
        self,
        processed_root: Path,
        battery_id: str,
        experiment_id: str,
    ) -> list[Path]:
        return [Path(processed_root) / "electrical" / battery_id / experiment_id]

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
        asset_ids = [asset.asset_id for asset in assets]
        output_paths = self.expected_output_paths(
            processed_root, experiment.battery_id, experiment.experiment_id
        )
        output_dir = output_paths[0]
        marker = output_dir / _OUTPUT_MARKER

        if not overwrite and marker.exists():
            # Existing outputs: skip without invoking the parser.
            asset_results = [
                AssetImportResult(asset_id=asset_id, status=AssetImportStatus.SKIPPED)
                for asset_id in asset_ids
            ]
            return ModalityImportResult(
                modality=self.modality,
                adapter_name=self.adapter_name,
                adapter_version=self.adapter_version,
                asset_ids=asset_ids,
                status=ImportStatus.PARTIAL,
                asset_results=asset_results,
                output_paths=output_paths,
                warnings=[
                    (
                        "output already exists, skipped: "
                        f"{output_dir} (use overwrite=True to regenerate)"
                    )
                ],
            )

        try:
            parsed = parse_electrical_experiment(experiment, assets, raw_root)
            manifest = write_electrical_experiment(parsed, processed_root)
        except Exception as error:  # noqa: BLE001 - normalize any parser failure
            issue = ImportError(
                code="ADAPTER_FAILURE",
                message=str(error),
                battery_id=experiment.battery_id,
                experiment_id=experiment.experiment_id,
                modality=self.modality,
                asset_ids=asset_ids,
                adapter_name=self.adapter_name,
            )
            return ModalityImportResult(
                modality=self.modality,
                adapter_name=self.adapter_name,
                adapter_version=self.adapter_version,
                asset_ids=asset_ids,
                status=ImportStatus.FAILED,
                asset_results=[
                    AssetImportResult(
                        asset_id=asset_id,
                        status=AssetImportStatus.FAILED,
                        error=issue,
                    )
                    for asset_id in asset_ids
                ],
                errors=[issue],
            )

        asset_results = [
            AssetImportResult(asset_id=asset_id, status=AssetImportStatus.SUCCESS)
            for asset_id in asset_ids
        ]
        return ModalityImportResult(
            modality=self.modality,
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            asset_ids=asset_ids,
            status=ImportStatus.SUCCESS,
            asset_results=asset_results,
            output_paths=[manifest.output_dir],
            warnings=list(parsed.warnings),
            errors=[],
        )

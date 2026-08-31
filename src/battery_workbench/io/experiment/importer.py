"""Experiment-level import orchestration for BRW-007.

This is the single high-level entry point that decides:

    Experiment -> DataAssets -> group by modality -> AdapterRegistry
    -> DataAdapter -> existing parser service -> ExperimentImportResult

It does **not** implement XLSX/TXT parsing itself. Unknown-modality detection
lives in the adapter registry (``registry.has`` / ``registry.get``); the core
``DataAsset.modality`` Literal contract is never weakened.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.battery import BatteryCell
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.adapters.registry import (
    DataAdapterRegistry,
    build_default_adapter_registry,
)
from battery_workbench.io.experiment.manifest_loader import (
    load_batteries,
    load_data_assets,
    load_experiments,
)
from battery_workbench.io.experiment.schemas import (
    ExperimentImportPlan,
    ExperimentImportResult,
    ImportError,
    ImportStatus,
    ModalityImportResult,
)

logger = logging.getLogger(__name__)

_MANIFEST_SUBDIR = "manifests"


class ExperimentImportError(Exception):
    """Structured exception raised by strict-mode import failures.

    Carries the underlying ``ImportError``; never a bare string.
    """

    def __init__(self, error: ImportError) -> None:
        self.error = error
        super().__init__(error.message)


def _manifest_dir(raw_root: Path) -> Path:
    return Path(raw_root) / _MANIFEST_SUBDIR


def _resolve_experiment(raw_root: Path, experiment_id: str) -> Experiment:
    experiments = load_experiments(_manifest_dir(raw_root) / "experiments.csv")
    for experiment in experiments:
        if experiment.experiment_id == experiment_id:
            return experiment
    raise ExperimentImportError(
        ImportError(
            code="EXPERIMENT_NOT_FOUND",
            message=f"experiment not found: {experiment_id}",
            experiment_id=experiment_id,
        )
    )


def _resolve_battery(raw_root: Path, battery_id: str) -> BatteryCell:
    batteries = load_batteries(_manifest_dir(raw_root) / "batteries.csv")
    for battery in batteries:
        if battery.battery_id == battery_id:
            return battery
    raise ExperimentImportError(
        ImportError(
            code="BATTERY_NOT_FOUND",
            message=f"battery not found: {battery_id}",
            battery_id=battery_id,
        )
    )


def _resolve_assets(raw_root: Path, experiment_id: str) -> list[DataAsset]:
    return [
        asset
        for asset in load_data_assets(_manifest_dir(raw_root) / "data_assets.csv")
        if asset.experiment_id == experiment_id
    ]


def _filter_modalities(assets: list[DataAsset], modalities: set[str] | None) -> list[DataAsset]:
    if modalities is None:
        return list(assets)
    return [asset for asset in assets if asset.modality in modalities]


def _group_by_modality(assets: list[DataAsset]) -> dict[str, list[DataAsset]]:
    groups: dict[str, list[DataAsset]] = defaultdict(list)
    for asset in assets:
        groups[asset.modality].append(asset)
    return dict(groups)


def _split_supported(
    groups: dict[str, list[DataAsset]], registry: DataAdapterRegistry
) -> tuple[dict[str, list[DataAsset]], dict[str, list[str]]]:
    supported: dict[str, list[DataAsset]] = {}
    unsupported: dict[str, list[str]] = {}
    for modality, assets in groups.items():
        if registry.has(modality):
            supported[modality] = assets
        else:
            unsupported[modality] = [asset.asset_id for asset in assets]
    return supported, unsupported


def plan_experiment_import(
    experiment_id: str,
    *,
    raw_root: Path,
    processed_root: Path,
    registry: DataAdapterRegistry | None = None,
    modalities: set[str] | None = None,
) -> ExperimentImportPlan:
    """Build a dry-run plan. Never invokes a parser and never writes files."""
    registry = registry or build_default_adapter_registry()
    raw_root = Path(raw_root)
    processed_root = Path(processed_root)

    experiment = _resolve_experiment(raw_root, experiment_id)
    # Resolve (and validate) the owning battery even though planning itself
    # never invokes a parser: a missing battery must surface at plan time.
    battery = _resolve_battery(raw_root, experiment.battery_id)
    assets = _filter_modalities(_resolve_assets(raw_root, experiment_id), modalities)

    groups = _group_by_modality(assets)
    supported, unsupported = _split_supported(groups, registry)

    adapter_assignments: dict[str, str] = {}
    expected_paths: list[Path] = []
    warnings: list[str] = []
    for modality, modality_assets in supported.items():
        adapter = registry.get(modality)
        adapter_assignments[modality] = adapter.adapter_name
        expected_paths.extend(
            adapter.expected_output_paths(
                processed_root, experiment.battery_id, experiment.experiment_id
            )
        )
        logger.info(
            "plan battery_id=%s experiment_id=%s modality=%s assets=%s adapter=%s",
            battery.battery_id,
            experiment.experiment_id,
            modality,
            [asset.asset_id for asset in modality_assets],
            adapter.adapter_name,
        )
    for modality, asset_ids in unsupported.items():
        warnings.append(
            f"modality={modality} has no registered adapter; assets {asset_ids} will be skipped"
        )

    return ExperimentImportPlan(
        battery_id=experiment.battery_id,
        experiment_id=experiment.experiment_id,
        modalities=list(groups.keys()),
        asset_groups={
            modality: [a.asset_id for a in assets] for modality, assets in groups.items()
        },
        adapter_assignments=adapter_assignments,
        expected_output_paths=expected_paths,
        unsupported_modalities=unsupported,
        warnings=warnings,
    )


def _aggregate_status(
    modality_results: list[ModalityImportResult], unsupported: dict[str, list[str]]
) -> ImportStatus:
    has_unsupported = bool(unsupported)
    has_success = any(r.status == ImportStatus.SUCCESS for r in modality_results)
    has_failure = any(r.status == ImportStatus.FAILED for r in modality_results)
    has_skip = any(r.status == ImportStatus.PARTIAL for r in modality_results)
    if has_success and not has_failure and not has_skip and not has_unsupported:
        return ImportStatus.SUCCESS
    if not has_success and has_failure:
        return ImportStatus.FAILED
    return ImportStatus.PARTIAL


def import_experiment(
    experiment_id: str,
    *,
    raw_root: Path,
    processed_root: Path,
    registry: DataAdapterRegistry | None = None,
    modalities: set[str] | None = None,
    overwrite: bool = False,
    strict: bool = False,
) -> ExperimentImportResult:
    """Import one Experiment, one call per modality, via the adapter registry.

    ``strict=False`` isolates failures (keeps successful modality results and
    returns ``PARTIAL``). ``strict=True`` fails fast on any unsupported
    modality or adapter failure.
    """
    registry = registry or build_default_adapter_registry()
    raw_root = Path(raw_root)
    processed_root = Path(processed_root)

    experiment = _resolve_experiment(raw_root, experiment_id)
    battery = _resolve_battery(raw_root, experiment.battery_id)
    assets = _filter_modalities(_resolve_assets(raw_root, experiment_id), modalities)

    groups = _group_by_modality(assets)
    supported, unsupported = _split_supported(groups, registry)

    if strict and unsupported:
        first_modality, first_asset_ids = next(iter(unsupported.items()))
        raise ExperimentImportError(
            ImportError(
                code="UNSUPPORTED_MODALITY",
                message=f"strict import aborted: no adapter for modality={first_modality}",
                battery_id=experiment.battery_id,
                experiment_id=experiment.experiment_id,
                modality=first_modality,
                asset_ids=first_asset_ids,
            )
        )

    modality_results: list[ModalityImportResult] = []
    for modality, modality_assets in supported.items():
        adapter = registry.get(modality)
        logger.info(
            "import experiment_id=%s modality=%s assets=%s adapter=%s overwrite=%s",
            experiment.experiment_id,
            modality,
            [asset.asset_id for asset in modality_assets],
            adapter.adapter_name,
            overwrite,
        )
        result = adapter.import_assets(
            battery=battery,
            experiment=experiment,
            assets=modality_assets,
            raw_root=raw_root,
            processed_root=processed_root,
            overwrite=overwrite,
        )
        modality_results.append(result)
        if strict and result.status == ImportStatus.FAILED:
            error = (
                result.errors[0]
                if result.errors
                else ImportError(
                    code="ADAPTER_FAILURE",
                    message=f"adapter failed for modality={modality}",
                    modality=modality,
                    adapter_name=adapter.adapter_name,
                )
            )
            raise ExperimentImportError(error)

    status = _aggregate_status(modality_results, unsupported)
    source_asset_ids = [asset.asset_id for asset in assets]
    imported = {r.modality for r in modality_results if r.status == ImportStatus.SUCCESS}
    skipped = {r.modality for r in modality_results if r.status == ImportStatus.PARTIAL}
    output_paths = [path for r in modality_results for path in r.output_paths]
    warnings: list[str] = []
    errors: list[ImportError] = []
    for r in modality_results:
        warnings.extend(r.warnings)
        errors.extend(r.errors)
    for modality, asset_ids in unsupported.items():
        warnings.append(
            f"modality={modality} has no registered adapter; assets {asset_ids} skipped"
        )

    result = ExperimentImportResult(
        battery_id=experiment.battery_id,
        experiment_id=experiment.experiment_id,
        status=status,
        requested_modalities=list(groups.keys()),
        imported_modalities=sorted(imported),
        skipped_modalities=sorted(skipped),
        unsupported_modalities=unsupported,
        source_asset_ids=source_asset_ids,
        modality_results=modality_results,
        output_paths=output_paths,
        warnings=warnings,
        errors=errors,
    )
    logger.info(
        "import complete experiment_id=%s status=%s",
        experiment.experiment_id,
        result.status.value,
    )
    return result

from __future__ import annotations

from pathlib import Path

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.adapters import DataAdapterRegistry
from battery_workbench.io.experiment.importer import import_experiment
from battery_workbench.io.experiment.schemas import ImportStatus, ModalityImportResult


class FakeAdapter:
    def __init__(
        self,
        modality: str,
        *,
        name: str | None = None,
        fail: bool = False,
    ) -> None:
        self.modality = modality
        self.adapter_name = name or f"Fake{modality.capitalize()}Adapter"
        self.adapter_version = "0.0.1"
        self._fail = fail
        self.calls: list[list[str]] = []

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
        self.calls.append([asset.asset_id for asset in assets])
        status = "FAILED" if self._fail else "SUCCESS"
        return ModalityImportResult(
            modality=self.modality,
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            asset_ids=[asset.asset_id for asset in assets],
            status=status,
            output_paths=self.expected_output_paths(
                processed_root, experiment.battery_id, experiment.experiment_id
            ),
        )


_BATTERIES = "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_A,NMC,5.0,test\n"
_EXPERIMENTS = (
    "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
    "EXP_A,CELL_A,2024-01-01 10:00:00,2024-01-01 12:00:00,cycling,test\n"
)
_ASSETS = (
    "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,"
    "parser_name,parser_version\n"
    "E1,EXP_A,electrical,batteries/CELL_A/EXP_A/electrical/a.xlsx,,,custom_excel,0.1\n"
    "E2,EXP_A,electrical,batteries/CELL_A/EXP_A/electrical/b.xlsx,,,custom_excel,0.1\n"
    "U1,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u1.txt,"
    "2024-01-01 10:00:00,,custom_txt,0.1\n"
)


def _write_manifests(root: Path) -> None:
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "batteries.csv").write_text(_BATTERIES, encoding="utf-8")
    (manifest_dir / "experiments.csv").write_text(_EXPERIMENTS, encoding="utf-8")
    (manifest_dir / "data_assets.csv").write_text(_ASSETS, encoding="utf-8")


def _registry() -> DataAdapterRegistry:
    electrical = FakeAdapter("electrical")
    ultrasound = FakeAdapter("ultrasound")
    registry = DataAdapterRegistry()
    registry.register(electrical)
    registry.register(ultrasound)
    return registry


def test_import_all_success(tmp_path: Path) -> None:
    """T12: every modality succeeds -> overall SUCCESS."""
    _write_manifests(tmp_path)
    result = import_experiment(
        "EXP_A",
        raw_root=tmp_path,
        processed_root=tmp_path / "processed",
        registry=_registry(),
    )
    assert result.status == ImportStatus.SUCCESS
    assert set(result.imported_modalities) == {"electrical", "ultrasound"}
    assert result.unsupported_modalities == {}
    assert result.source_asset_ids == ["E1", "E2", "U1"]


def test_import_dispatch_once_per_modality(tmp_path: Path) -> None:
    """T07/T08 combined: two electrical assets -> one electrical adapter call."""
    _write_manifests(tmp_path)
    electrical = FakeAdapter("electrical")
    ultrasound = FakeAdapter("ultrasound")
    registry = DataAdapterRegistry()
    registry.register(electrical)
    registry.register(ultrasound)

    import_experiment(
        "EXP_A",
        raw_root=tmp_path,
        processed_root=tmp_path / "processed",
        registry=registry,
    )
    assert electrical.calls == [["E1", "E2"]]
    assert ultrasound.calls == [["U1"]]


def test_dry_run_plan_does_not_invoke_parser(tmp_path: Path) -> None:
    """T16: plan mode never writes output nor calls a parser."""
    _write_manifests(tmp_path)
    electrical = FakeAdapter("electrical")
    ultrasound = FakeAdapter("ultrasound")
    registry = DataAdapterRegistry()
    registry.register(electrical)
    registry.register(ultrasound)

    from battery_workbench.io.experiment.importer import plan_experiment_import

    plan = plan_experiment_import(
        "EXP_A",
        raw_root=tmp_path,
        processed_root=tmp_path / "processed",
        registry=registry,
    )
    assert plan.expected_output_paths
    # No parser is invoked during planning.
    assert electrical.calls == []
    assert ultrasound.calls == []
    assert not (tmp_path / "processed").exists()

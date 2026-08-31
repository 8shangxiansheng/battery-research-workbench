from __future__ import annotations

from pathlib import Path

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.adapters import DataAdapterRegistry
from battery_workbench.io.experiment.importer import plan_experiment_import
from battery_workbench.io.experiment.schemas import ModalityImportResult


class FakeAdapter:
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


_BATTERIES = "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_A,NMC,5.0,test\n"
_EXPERIMENTS = (
    "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
    "EXP_A,CELL_A,2024-01-01 10:00:00,2024-01-01 12:00:00,cycling,test\n"
)


def _electronical_assets_csv() -> str:
    return (
        "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,"
        "parser_name,parser_version\n"
        "E1,EXP_A,electrical,batteries/CELL_A/EXP_A/electrical/a.xlsx,,,custom_excel,0.1\n"
        "E2,EXP_A,electrical,batteries/CELL_A/EXP_A/electrical/b.xlsx,,,custom_excel,0.1\n"
        "U1,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u1.txt,"
        "2024-01-01 10:00:00,,custom_txt,0.1\n"
        "U2,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u2.txt,"
        "2024-01-01 11:00:00,,custom_txt,0.1\n"
    )


def _write_manifests(root: Path) -> None:
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "batteries.csv").write_text(_BATTERIES, encoding="utf-8")
    (manifest_dir / "experiments.csv").write_text(_EXPERIMENTS, encoding="utf-8")
    (manifest_dir / "data_assets.csv").write_text(_electronical_assets_csv(), encoding="utf-8")


def _registry() -> DataAdapterRegistry:
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))
    registry.register(FakeAdapter("ultrasound"))
    return registry


def test_plan_groups_assets_by_modality(tmp_path: Path) -> None:
    """T06: assets are grouped by modality, never mixed."""
    _write_manifests(tmp_path)
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=_registry()
    )
    assert plan.asset_groups["electrical"] == ["E1", "E2"]
    assert plan.asset_groups["ultrasound"] == ["U1", "U2"]
    assert plan.unsupported_modalities == {}


def test_plan_multi_asset_same_modality_single_adapter(tmp_path: Path) -> None:
    """T07: one modality with two assets maps to one adapter assignment."""
    _write_manifests(tmp_path)
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=_registry()
    )
    assert plan.adapter_assignments["electrical"] == "FakeElectricalAdapter"
    assert plan.asset_groups["electrical"] == ["E1", "E2"]


def test_plan_multi_modality_both_adapters(tmp_path: Path) -> None:
    """T08: electrical and ultrasound each resolve to their own adapter."""
    _write_manifests(tmp_path)
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=_registry()
    )
    assert set(plan.adapter_assignments) == {"electrical", "ultrasound"}


def test_plan_predicts_expected_output_paths(tmp_path: Path) -> None:
    """T15: plan exposes expected outputs without touching disk or parsers."""
    _write_manifests(tmp_path)
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=_registry()
    )
    processed = tmp_path / "processed"
    assert processed / "electrical" / "CELL_A" / "EXP_A" in plan.expected_output_paths
    assert processed / "ultrasound" / "CELL_A" / "EXP_A" in plan.expected_output_paths
    # Namespace the plan never invoked the parser: nothing was written.
    assert not (processed / "electrical").exists()


def test_plan_reports_no_unsupported_when_all_registered(tmp_path: Path) -> None:
    """T17: with every asset modality registered, the plan surfaces nothing unsupported."""
    _write_manifests(tmp_path)
    registry = _registry()
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=registry
    )
    assert plan.unsupported_modalities == {}
    assert plan.adapter_assignments  # both known modalities resolved


def test_plan_unknown_modality_when_registry_lacks_modality(tmp_path: Path) -> None:
    """T17: assets for a modality with no registered adapter are reported as unsupported."""
    _write_manifests(tmp_path)
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))
    plan = plan_experiment_import(
        "EXP_A", raw_root=tmp_path, processed_root=tmp_path / "processed", registry=registry
    )
    assert plan.unsupported_modalities == {"ultrasound": ["U1", "U2"]}
    # The known (electrical) modality still resolves normally.
    assert plan.adapter_assignments == {"electrical": "FakeElectricalAdapter"}

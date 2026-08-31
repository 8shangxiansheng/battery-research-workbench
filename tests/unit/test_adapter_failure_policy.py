from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.adapters import DataAdapterRegistry
from battery_workbench.io.experiment.importer import (
    ExperimentImportError,
    import_experiment,
)
from battery_workbench.io.experiment.schemas import (
    ImportError,
    ImportStatus,
    ModalityImportResult,
)


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
        status = "FAILED" if self._fail else "SUCCESS"
        errors = (
            [
                ImportError(
                    code="ADAPTER_FAILURE",
                    message=f"adapter {self.modality} failed",
                    modality=self.modality,
                )
            ]
            if self._fail
            else []
        )
        return ModalityImportResult(
            modality=self.modality,
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            asset_ids=[asset.asset_id for asset in assets],
            status=status,
            errors=errors,
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
    "U1,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u1.txt,"
    "2024-01-01 10:00:00,,custom_txt,0.1\n"
)


def _write_manifests(root: Path) -> None:
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "batteries.csv").write_text(_BATTERIES, encoding="utf-8")
    (manifest_dir / "experiments.csv").write_text(_EXPERIMENTS, encoding="utf-8")
    (manifest_dir / "data_assets.csv").write_text(_ASSETS, encoding="utf-8")


def test_one_adapter_fails_other_succeeds_partial(tmp_path: Path) -> None:
    """T11: one modality fails, the other succeeds -> PARTIAL, success retained."""
    _write_manifests(tmp_path)
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical", fail=True))
    registry.register(FakeAdapter("ultrasound"))

    result = import_experiment(
        "EXP_A",
        raw_root=tmp_path,
        processed_root=tmp_path / "processed",
        registry=registry,
    )
    assert result.status == ImportStatus.PARTIAL
    # The successful ultrasound modality is still present.
    assert "ultrasound" in result.imported_modalities
    # The failed electrical modality is absent from imported and yields errors.
    assert "electrical" not in result.imported_modalities
    assert any(error.code == "ADAPTER_FAILURE" for error in result.errors)


def test_one_adapter_fails_strict_raises(tmp_path: Path) -> None:
    """T17/T11 strict: a failing adapter raises an ExperimentImportError."""
    _write_manifests(tmp_path)
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical", fail=True))
    registry.register(FakeAdapter("ultrasound"))

    with pytest.raises(ExperimentImportError) as excinfo:
        import_experiment(
            "EXP_A",
            raw_root=tmp_path,
            processed_root=tmp_path / "processed",
            registry=registry,
            strict=True,
        )
    assert excinfo.value.error.code == "ADAPTER_FAILURE"


def test_unknown_modality_non_strict_partial(tmp_path: Path) -> None:
    """T09: a modality with no registered adapter -> PARTIAL, reported, not silent."""
    _write_manifests(tmp_path)
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))

    result = import_experiment(
        "EXP_A",
        raw_root=tmp_path,
        processed_root=tmp_path / "processed",
        registry=registry,
    )
    assert result.status == ImportStatus.PARTIAL
    assert result.unsupported_modalities == {"ultrasound": ["U1"]}
    assert "ultrasound" not in result.imported_modalities
    assert "electrical" in result.imported_modalities


def test_unknown_modality_strict_raises(tmp_path: Path) -> None:
    """T10: a modality with no registered adapter in strict mode fails fast."""
    _write_manifests(tmp_path)
    registry = DataAdapterRegistry()
    registry.register(FakeAdapter("electrical"))

    with pytest.raises(ExperimentImportError) as excinfo:
        import_experiment(
            "EXP_A",
            raw_root=tmp_path,
            processed_root=tmp_path / "processed",
            registry=registry,
            strict=True,
        )
    assert excinfo.value.error.code == "UNSUPPORTED_MODALITY"
    assert excinfo.value.error.modality == "ultrasound"

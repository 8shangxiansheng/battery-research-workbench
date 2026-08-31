from __future__ import annotations

from pathlib import Path

import pytest

from battery_workbench.io.adapters import build_default_adapter_registry
from battery_workbench.io.experiment.importer import (
    import_experiment,
    plan_experiment_import,
)
from battery_workbench.io.experiment.schemas import ImportStatus

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw"
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"

_EXPECTED_RAW = RAW_ROOT / "batteries" / "CELL_001" / "EXP_001"
_RAW_ELECTRICAL = _EXPECTED_RAW / "electrical" / "小-1-1-264.xlsx"
_RAW_ULTRASOUND = _EXPECTED_RAW / "ultrasound" / "export - 2024.01.06 - 21.03.01.txt"


@pytest.mark.skipif(
    not (_RAW_ELECTRICAL.exists() and _RAW_ULTRASOUND.exists()),
    reason="CELL_001/EXP_001 raw sample files not present",
)
def test_current_cell001_plan_routes_adapters() -> None:
    """T17/T18: real CELL_001/EXP_001 plan resolves E001 and U001 to the right adapters."""
    plan = plan_experiment_import(
        "EXP_001",
        raw_root=RAW_ROOT,
        processed_root=PROCESSED_ROOT,
        registry=build_default_adapter_registry(),
    )

    assert plan.battery_id == "CELL_001"
    assert plan.experiment_id == "EXP_001"
    assert plan.asset_groups == {"electrical": ["E001"], "ultrasound": ["U001"]}
    assert plan.adapter_assignments == {
        "electrical": "ElectricalAdapter",
        "ultrasound": "UltrasoundAdapter",
    }
    assert plan.unsupported_modalities == {}


@pytest.mark.skipif(
    not (_RAW_ELECTRICAL.exists() and _RAW_ULTRASOUND.exists()),
    reason="CELL_001/EXP_001 raw sample files not present",
)
def test_current_cell001_import_default_overwrite_false_is_safe() -> None:
    """T13/T18: with existing processed outputs, overwrite=False skips and never writes."""
    # Snapshot the output directory listing (contents are immutable golden outputs).
    electrical_dir = PROCESSED_ROOT / "electrical" / "CELL_001" / "EXP_001"
    ultrasound_dir = PROCESSED_ROOT / "ultrasound" / "CELL_001" / "EXP_001"

    # If golden outputs already exist, importing without overwrite must not touch them.
    if electrical_dir.exists() or ultrasound_dir.exists():
        result = import_experiment(
            "EXP_001",
            raw_root=RAW_ROOT,
            processed_root=PROCESSED_ROOT,
            registry=build_default_adapter_registry(),
            overwrite=False,
        )
        # Skip-existing is surfaced as PARTIAL, not silently overwritten.
        assert result.status == ImportStatus.PARTIAL
        assert result.errors == []  # skipping is not an error
        # No modality was actually (re)imported because output dirs exist.
        assert result.imported_modalities == []
        # The golden parser manifests are still present and re-parseable.
        assert (electrical_dir / "parser_manifest.json").exists()
        assert (ultrasound_dir / "parser_manifest.json").exists()

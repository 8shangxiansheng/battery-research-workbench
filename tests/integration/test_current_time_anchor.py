from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from battery_workbench.synchronization.persistence import write_time_anchor_state
from battery_workbench.synchronization.schemas import (
    TimeAnchorConfig,
    TimeAnchorState,
)
from battery_workbench.synchronization.service import assess_experiment_time_anchors

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw"
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"

_EXPECTED_RAW = RAW_ROOT / "batteries" / "CELL_001" / "EXP_001"
_RAW_ELECTRICAL = _EXPECTED_RAW / "electrical" / "小-1-1-264.xlsx"
_RAW_ULTRASOUND = _EXPECTED_RAW / "ultrasound" / "export - 2024.01.06 - 21.03.01.txt"
_CONFIG = TimeAnchorConfig.from_yaml(REPO_ROOT / "configs" / "time_anchor.yaml")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.skipif(
    not (_RAW_ELECTRICAL.exists() and _RAW_ULTRASOUND.exists()),
    reason="CELL_001/EXP_001 raw sample files not present",
)
def test_current_cell001_time_anchor_assessment(tmp_path: Path) -> None:
    """T19: real CELL_001/EXP_001 anchor assessment."""
    # Input integrity snapshot.
    manifest_assets = (RAW_ROOT / "manifests" / "data_assets.csv").read_bytes()
    manifest_experiments = (RAW_ROOT / "manifests" / "experiments.csv").read_bytes()
    records_parquet = PROCESSED_ROOT / "electrical" / "CELL_001" / "EXP_001" / "records.parquet"
    frames_parquet = PROCESSED_ROOT / "ultrasound" / "CELL_001" / "EXP_001" / "frames.parquet"
    records_hash = _sha256(records_parquet)
    frames_hash = _sha256(frames_parquet)

    report = assess_experiment_time_anchors(
        "EXP_001",
        processed_root=PROCESSED_ROOT,
        manifest_root=RAW_ROOT / "manifests",
        config=_CONFIG,
    )

    assert report.experiment_id == "EXP_001"
    assert report.validated_sync is False
    assert report.status in ("PASS", "PASS_WITH_WARNINGS")

    u001 = next(a for a in report.assets if a["asset_id"] == "U001")
    assert u001["anchor_status"] == "PROVISIONAL"
    assert u001["validated_sync"] is False
    # The selected candidate is the manifest file_start_time source.
    assert u001["selected_anchor_id"] is not None
    selected_source = {c["source_type"] for c in u001["candidates"]}
    assert "MANIFEST_FILE_START" in selected_source

    # Mechanical coverage matches the real baseline.
    coverage = u001["coverage"]
    assert coverage["candidate_start"] == "2024-01-06T09:52:31.031217"
    assert coverage["candidate_end"] == "2024-01-06T20:58:51.030000"
    assert coverage["end_residual_s"] == pytest.approx(-2.97, abs=1e-6)
    assert coverage["coverage_overlap_fraction"] == pytest.approx(1.0, abs=1e-6)

    # Timezone remains unknown.
    assert any("timezone unknown" in limitation for limitation in report.limitations)

    # Inputs are unchanged after assessment.
    assert (RAW_ROOT / "manifests" / "data_assets.csv").read_bytes() == manifest_assets
    assert (RAW_ROOT / "manifests" / "experiments.csv").read_bytes() == manifest_experiments
    assert _sha256(records_parquet) == records_hash
    assert _sha256(frames_parquet) == frames_hash


@pytest.mark.skipif(
    not (_RAW_ELECTRICAL.exists() and _RAW_ULTRASOUND.exists()),
    reason="CELL_001/EXP_001 raw sample files not present",
)
def test_current_cell001_time_anchor_persistence(tmp_path: Path) -> None:
    """Canonical time_anchors.json written to the standard location."""
    report = assess_experiment_time_anchors(
        "EXP_001",
        processed_root=PROCESSED_ROOT,
        manifest_root=RAW_ROOT / "manifests",
        config=_CONFIG,
    )
    from battery_workbench.synchronization.schemas import AssetAnchorAssessment

    state = TimeAnchorState(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        anchor_version=_CONFIG.version,
        experiment_reference={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "experiment_start_time": "2024-01-06T09:52:31",
            "experiment_end_time": "2024-01-06T20:58:54",
        },
        assets=[AssetAnchorAssessment.model_validate(a) for a in report.assets],
        warnings=report.warnings,
        limitations=report.limitations,
        validated_sync=False,
    )
    paths = write_time_anchor_state(
        state,
        processed_root=tmp_path / "processed",
        artifacts_root=tmp_path / "artifacts",
        html_report=report,
    )
    canonical = paths["time_anchors"]
    assert canonical.exists()
    assert canonical.parent.name == "EXP_001"
    assert (
        tmp_path / "artifacts" / "CELL_001" / "EXP_001" / "time_anchor" / "time_anchor_report.json"
    ).exists()

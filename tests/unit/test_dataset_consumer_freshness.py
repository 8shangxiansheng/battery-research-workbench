from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from battery_workbench.orchestrator.nodes import (
    FeatureAnalysisNode,
    SocModelingNode,
    SplitNode,
)
from battery_workbench.orchestrator.schemas import AnalysisPlan, ArtifactRef, PlanProject


def _stale_dataset(tmp_path: Path) -> tuple[ArtifactRef, SimpleNamespace, AnalysisPlan]:
    processed_root = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    dataset_id = "DS::stale-consumer"
    dataset_dir = processed_root / "datasets" / "CELL_TEST" / "EXP_TEST" / "SOC" / dataset_id
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_TEST"],
            "experiment_id": ["EXP_TEST"],
            "measurement_event_id": ["ME::1"],
            "soc_reference_percent": [50.0],
            "peak_to_peak_v": [0.5],
        }
    ).to_parquet(dataset_path, index=False)
    manifest_path = dataset_dir / "dataset_manifest.json"
    manifest = {
        "dataset_id": dataset_id,
        "dataset_family": "SOC",
        "dataset_status": "READY_FOR_SPLIT",
        "battery_id": "CELL_TEST",
        "experiment_id": "EXP_TEST",
        "target_name": "soc_reference_percent",
        "target_column": "soc_reference_percent",
        "predictor_columns": ["peak_to_peak_v"],
        "output_checksum": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "feature_set_id": "FS::missing",
        "feature_set_path": "features/CELL_TEST/EXP_TEST/FS::missing/features.parquet",
        "feature_set_checksum": "0" * 64,
        "label_set_id": "LB::missing",
        "label_set_path": "labels/CELL_TEST/EXP_TEST/event_labels.parquet",
        "label_set_checksum": "0" * 64,
        "label_set_manifest_path": "labels/CELL_TEST/EXP_TEST/label_manifest.json",
        "label_set_manifest_checksum": "0" * 64,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_ref = ArtifactRef(
        artifact_type="DATASET",
        artifact_id=dataset_id,
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        path=str(dataset_dir),
        manifest_path=str(manifest_path),
    )
    ctx = SimpleNamespace(raw_root=raw_root, processed_root=processed_root)
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_TEST", experiment_id="EXP_TEST"),
        stages=["DATASET"],
        target="soc_reference_percent",
        feature_analysis={"analysis_mode": "TRAIN_ONLY_ML_SAFE"},
    )
    return dataset_ref, ctx, plan


@pytest.mark.parametrize(
    ("node", "consumer"),
    [
        (FeatureAnalysisNode(), "ML-safe feature analysis"),
        (SplitNode(), "Split generation"),
        (SocModelingNode(), "SOC modeling"),
    ],
)
def test_dataset_consumers_revalidate_freshness_before_reading(
    tmp_path: Path, node, consumer: str
) -> None:
    dataset_ref, ctx, plan = _stale_dataset(tmp_path)

    with pytest.raises(ValueError, match=rf"{consumer} blocked: Dataset is stale"):
        node.run(plan, {"DATASET": dataset_ref}, ctx)

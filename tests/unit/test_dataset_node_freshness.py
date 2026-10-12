from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

from battery_workbench.datasets.freshness import dataset_freshness
from battery_workbench.orchestrator.nodes import DatasetNode
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_reusable_dataset(root: Path, dataset_id: str) -> Path:
    plan = AnalysisPlan(
        profile="BUILD_DATASET",
        project=PlanProject(battery_id="CELL_NODE", experiment_id="EXP_NODE"),
        stages=["DATASET"],
        features={"selected_features": ["amplitude_a_u"]},
        target="soc_reference_percent",
    )
    node = DatasetNode()
    requirements = node.requirements(plan, {})
    dataset_dir = root / requirements.output_rel_dir / dataset_id
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "dataset.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["CELL_NODE::ME::1"],
            "battery_id": ["CELL_NODE"],
            "experiment_id": ["EXP_NODE"],
            "soc_reference_percent": [25.0],
            "amplitude_a_u": [0.25],
        }
    ).to_parquet(dataset_path, index=False)

    feature_dir = root / "features" / "CELL_NODE" / "EXP_NODE" / "FS::node"
    feature_dir.mkdir(parents=True)
    feature_path = feature_dir / "ultrasound_features.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["CELL_NODE::ME::1"], "amplitude_a_u": [0.25]}
    ).to_parquet(feature_path, index=False)
    definitions_path = feature_dir / "feature_definitions.json"
    definitions_path.write_text('{"features":["amplitude_a_u"]}', encoding="utf-8")
    analysis_slice_path = root / "analysis_slices/CELL_NODE/EXP_NODE/AS::node.parquet"
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"analysis slice")
    waveform_store_path = root / "waveform_inputs/CELL_NODE/EXP_NODE/waveforms.zarr"
    waveform_store_path.mkdir(parents=True)
    (waveform_store_path / "chunk.bin").write_bytes(b"waveform")
    feature_manifest_path = feature_dir / "feature_set_manifest.json"
    feature_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS::node",
                "battery_id": "CELL_NODE",
                "experiment_id": "EXP_NODE",
                "analysis_slice_id": "AS::node",
                "analysis_slice_path": str(analysis_slice_path.relative_to(root)),
                "analysis_slice_checksum": _sha256(analysis_slice_path),
                "waveform_store_path": str(waveform_store_path.relative_to(root)),
                "waveform_store_checksum": _tree_sha256(waveform_store_path),
                "output_paths": {
                    "features": str(feature_path.relative_to(root)),
                    "definitions": str(definitions_path.relative_to(root)),
                },
                "output_checksums": {
                    "features": _sha256(feature_path),
                    "definitions": _sha256(definitions_path),
                },
            }
        ),
        encoding="utf-8",
    )
    label_dir = root / "labels" / "CELL_NODE" / "EXP_NODE"
    label_dir.mkdir(parents=True)
    label_path = label_dir / "event_labels.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["CELL_NODE::ME::1"], "soc_reference_percent": [25.0]}
    ).to_parquet(label_path, index=False)
    cycle_label_path = label_dir / "cycle_labels.parquet"
    pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [99.0]}).to_parquet(
        cycle_label_path, index=False
    )
    label_manifest_path = label_dir / "label_manifest.json"
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LB::node",
                "battery_id": "CELL_NODE",
                "experiment_id": "EXP_NODE",
                "output_paths": {
                    "event_labels": str(label_path.relative_to(root)),
                    "cycle_labels": str(cycle_label_path.relative_to(root)),
                },
                "output_checksums": {
                    "event_labels": _sha256(label_path),
                    "cycle_labels": _sha256(cycle_label_path),
                },
            }
        ),
        encoding="utf-8",
    )

    manifest: dict[str, object] = {
        "dataset_id": dataset_id,
        "battery_id": "CELL_NODE",
        "experiment_id": "EXP_NODE",
        "dataset_family": "SOC",
        "dataset_status": "READY_WITH_LIMITATIONS",
        "output_checksum": _sha256(dataset_path),
        "feature_set_id": "FS::node",
        "feature_set_path": str(feature_path.relative_to(root)),
        "feature_set_checksum": _sha256(feature_path),
        "feature_set_manifest_path": str(feature_manifest_path.relative_to(root)),
        "feature_set_manifest_checksum": _sha256(feature_manifest_path),
        "label_set_id": "LB::node",
        "label_set_path": str(label_path.relative_to(root)),
        "label_set_checksum": _sha256(label_path),
        "label_set_manifest_path": str(label_manifest_path.relative_to(root)),
        "label_set_manifest_checksum": _sha256(label_manifest_path),
        "selected_features": ["amplitude_a_u"],
        "predictor_columns": ["amplitude_a_u"],
        "target_name": "soc_reference_percent",
        "target_column": "soc_reference_percent",
        "dataset_builder_version": requirements.expected_version,
        "analysis_slice_id": "AS::node",
    }
    (dataset_dir / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return label_path


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


def test_dataset_node_does_not_reuse_dataset_after_label_source_changes(tmp_path: Path) -> None:
    dataset_id = "DS::node-freshness"
    label_path = _write_reusable_dataset(tmp_path, dataset_id)
    pd.DataFrame(
        {"measurement_event_id": ["CELL_NODE::ME::1"], "soc_reference_percent": [75.0]}
    ).to_parquet(label_path, index=False)
    plan = AnalysisPlan(
        profile="BUILD_DATASET",
        project=PlanProject(battery_id="CELL_NODE", experiment_id="EXP_NODE"),
        stages=["DATASET"],
        features={"selected_features": ["amplitude_a_u"]},
        target="soc_reference_percent",
    )

    ref, reason = DatasetNode().resolve_existing_output(plan, {}, tmp_path)

    assert ref is None
    assert "STALE_SOURCE" in reason


def test_dataset_freshness_rejects_analysis_slice_identity_mismatch(tmp_path: Path) -> None:
    _write_reusable_dataset(tmp_path, "DS::slice-identity")
    manifest_path = (
        tmp_path / "datasets/CELL_NODE/EXP_NODE/SOC/DS::slice-identity/dataset_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["analysis_slice_id"] = "AS::different"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    freshness = dataset_freshness(tmp_path, manifest_path, manifest)

    assert freshness["freshness_status"] == "STALE_SOURCE"
    assert "FEATURE_SET_ANALYSIS_SLICE_ID_MISMATCH" in freshness["freshness_reasons"]


def test_dataset_node_skips_stale_sibling_and_reuses_matching_fresh_dataset(
    tmp_path: Path,
) -> None:
    stale_id = "DS::000-stale"
    fresh_id = "DS::999-fresh"
    label_path = _write_reusable_dataset(tmp_path, stale_id)
    pd.DataFrame(
        {"measurement_event_id": ["CELL_NODE::ME::1"], "soc_reference_percent": [75.0]}
    ).to_parquet(label_path, index=False)

    stale_dir = tmp_path / "datasets/CELL_NODE/EXP_NODE/SOC" / stale_id
    fresh_dir = tmp_path / "datasets/CELL_NODE/EXP_NODE/SOC" / fresh_id
    shutil.copytree(stale_dir, fresh_dir)
    fresh_manifest_path = fresh_dir / "dataset_manifest.json"
    fresh_manifest = json.loads(fresh_manifest_path.read_text())
    fresh_manifest["dataset_id"] = fresh_id
    fresh_manifest["label_set_checksum"] = _sha256(label_path)
    label_manifest_path = tmp_path / "labels/CELL_NODE/EXP_NODE/label_manifest.json"
    label_manifest = json.loads(label_manifest_path.read_text())
    label_manifest["output_checksums"]["event_labels"] = _sha256(label_path)
    cycle_label_path = label_path.parent / "cycle_labels.parquet"
    label_manifest["output_checksums"]["cycle_labels"] = _sha256(cycle_label_path)
    label_manifest_path.write_text(json.dumps(label_manifest), encoding="utf-8")
    fresh_manifest["label_set_manifest_checksum"] = _sha256(label_manifest_path)
    fresh_manifest_path.write_text(json.dumps(fresh_manifest), encoding="utf-8")

    plan = AnalysisPlan(
        profile="BUILD_DATASET",
        project=PlanProject(battery_id="CELL_NODE", experiment_id="EXP_NODE"),
        stages=["DATASET"],
        features={"selected_features": ["amplitude_a_u"]},
        target="soc_reference_percent",
    )

    ref, reason = DatasetNode().resolve_existing_output(plan, {}, tmp_path)

    assert ref is not None
    assert ref.artifact_id == fresh_id
    assert reason == "manifest+identity+status+provenance verified"

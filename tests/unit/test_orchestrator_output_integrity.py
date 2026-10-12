from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from battery_workbench.analysis.schemas import ConditionSliceSpec
from battery_workbench.analysis.slice_engine import create_analysis_slice
from battery_workbench.api.errors import APIError
from battery_workbench.feature_analysis.output import write_analysis_payload
from battery_workbench.feature_analysis.schemas import FeatureAnalysisSpec
from battery_workbench.features.ultrasound_engine import extract_ultrasound_features
from battery_workbench.gates.persistence import (
    write_gated_analysis_payload,
    write_gated_feature_payload,
)
from battery_workbench.gates.schemas import GateSpec
from battery_workbench.orchestrator.nodes import (
    AnalysisSliceNode,
    FeatureAnalysisNode,
    FeatureLabelAnalysisNode,
    GatedFeaturesNode,
    MeasurementEventsNode,
    ReferenceLabelsNode,
    SocModelingNode,
    SplitNode,
    SynchronizationNode,
    UltrasoundFeaturesNode,
    UltrasoundTimestampsNode,
    _assert_current_measurement_event_labels,
)
from battery_workbench.orchestrator.schemas import AnalysisPlan, ArtifactRef, PlanProject
from battery_workbench.splits.schemas import SplitSpec
from battery_workbench.synchronization.sync_schemas import SYNCHRONIZATION_SCHEMA_VERSION


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_feature_analysis_cache(root: Path, *, include_input_provenance: bool = True):
    battery_id, experiment_id = "CELL_A", "EXP_A"
    spec = FeatureAnalysisSpec(
        analysis_mode="EXPLORATORY_FULL_DATA",
        target="soc_reference_percent",
    )
    source = root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"events-v1")
    input_files = {"measurement_events": source} if include_input_provenance else None
    written = write_analysis_payload(
        spec=spec,
        analysis={"availability": []},
        selection={
            "selection_id": "SEL::cache-test",
            "analysis_mode": spec.analysis_mode.value,
            "selection_requested": False,
            "selected_features": [],
            "rejected_features": [],
            "selection_basis": "NOT_REQUESTED",
            "selection_mode": "NOT_REQUESTED",
            "ml_safe_selection": False,
            "split_id": None,
            "fold_index": None,
            "policy": {},
            "policy_version": "0.1.0",
            "auto_removed_features": [],
            "commit_status": "NOT_REQUESTED",
        },
        battery_id=battery_id,
        experiment_id=experiment_id,
        dataset_id="",
        output_root=root,
        input_files=input_files,
    )
    manifest_path = Path(written["analysis_manifest"])
    return source, manifest_path


def _feature_analysis_plan() -> AnalysisPlan:
    return AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_A", experiment_id="EXP_A"),
        feature_analysis={
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "target": "soc_reference_percent",
        },
    )


def test_feature_analysis_node_reuses_only_current_input_provenance(tmp_path: Path) -> None:
    source, manifest_path = _write_feature_analysis_cache(tmp_path)
    node = FeatureAnalysisNode()

    current_ref, _ = node.resolve_existing_output(_feature_analysis_plan(), {}, tmp_path)
    assert current_ref is not None

    source.write_bytes(b"events-v2")
    stale_ref, reason = node.resolve_existing_output(_feature_analysis_plan(), {}, tmp_path)
    assert stale_ref is None
    assert "input 'measurement_events' changed" in reason
    assert manifest_path.is_file()


def test_feature_analysis_node_does_not_reuse_legacy_missing_input_provenance(
    tmp_path: Path,
) -> None:
    _, manifest_path = _write_feature_analysis_cache(tmp_path, include_input_provenance=False)

    reference, reason = FeatureAnalysisNode().resolve_existing_output(
        _feature_analysis_plan(), {}, tmp_path
    )

    assert reference is None
    assert "ANALYSIS_INPUT_PROVENANCE_MISSING" in reason
    assert manifest_path.is_file()


def _write_gated_feature_cache(root: Path) -> tuple[Path, Path, AnalysisPlan]:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    waveform_store = root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    waveform_store.mkdir(parents=True)
    (waveform_store / "0.0").write_bytes(b"synthetic-waveform")
    gate = GateSpec(
        gate_name="primary",
        start_sample=10,
        end_sample=40,
        waveform_length=1250,
    )
    payload = write_gated_feature_payload(
        gated_features=pd.DataFrame(
            {"measurement_event_id": ["ME::1"], "gate_id": [gate.gate_id], "rms": [1.0]}
        ),
        gate_specs=[gate],
        tof_definitions=[],
        gate_selection_basis="SIGNAL_ONLY",
        battery_id=battery_id,
        experiment_id=experiment_id,
        output_root=root,
        waveform_store_path=str(waveform_store),
    )
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        gates={"gate_specs": [{"gate_name": "primary", "start_sample": 10, "end_sample": 40}]},
    )
    return waveform_store, Path(payload["gated_feature_manifest"]), plan


def test_gated_feature_node_reuses_only_intact_outputs_and_waveform_source(
    tmp_path: Path,
) -> None:
    waveform_store, manifest_path, plan = _write_gated_feature_cache(tmp_path)
    node = GatedFeaturesNode()

    reference, _ = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is not None

    (waveform_store / "0.0").write_bytes(b"changed-waveform")
    stale_reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert stale_reference is None
    assert "GATED_FEATURE_WAVEFORM_CHECKSUM_MISMATCH" in reason

    (waveform_store / "0.0").write_bytes(b"synthetic-waveform")
    gated_path = manifest_path.parent / "gated_features.parquet"
    gated_path.write_bytes(b"tampered-gated-features")
    damaged_reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert damaged_reference is None
    assert "GATED_FEATURE_OUTPUT_CHECKSUM_MISMATCH:gated_features" in reason


def test_gated_feature_node_rejects_legacy_manifest_missing_schema_checksum(
    tmp_path: Path,
) -> None:
    _, manifest_path, plan = _write_gated_feature_cache(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["output_checksums"]["gated_feature_schema"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reference, reason = GatedFeaturesNode().resolve_existing_output(plan, {}, tmp_path)

    assert reference is None
    assert "GATED_FEATURE_OUTPUT_CHECKSUM_MISSING:gated_feature_schema" in reason


def _write_gated_analysis_cache(root: Path) -> tuple[Path, Path, Path, AnalysisPlan]:
    waveform_store, gate_manifest_path, plan = _write_gated_feature_cache(root)
    del waveform_store
    gate_manifest = json.loads(gate_manifest_path.read_text(encoding="utf-8"))
    gate_set_id = gate_manifest["gate_set_id"]
    gate_dir = gate_manifest_path.parent
    labels_dir = root / "labels" / "CELL_A" / "EXP_A"
    labels_dir.mkdir(parents=True)
    event_labels = labels_dir / "event_labels.parquet"
    cycle_labels = labels_dir / "cycle_labels.parquet"
    label_manifest = labels_dir / "label_manifest.json"
    event_labels.write_bytes(b"event-labels")
    cycle_labels.write_bytes(b"cycle-labels")
    label_manifest.write_text("{}", encoding="utf-8")
    plan.gates["gate_set_id"] = gate_set_id
    written = write_gated_analysis_payload(
        analysis_df=pd.DataFrame({"measurement_event_id": ["ME::1"], "soc": [50.0]}),
        manifest={"gate_set_id": gate_set_id},
        report={"note": "test"},
        battery_id="CELL_A",
        experiment_id="EXP_A",
        gate_set_id=gate_set_id,
        output_root=root,
        input_files={
            "gated_features": gate_dir / "gated_features.parquet",
            "gated_feature_manifest": gate_manifest_path,
            "gate_specs": gate_dir / "gate_specs.json",
            "event_labels": event_labels,
            "cycle_labels": cycle_labels,
            "label_manifest": label_manifest,
        },
    )
    return (
        root / written["analysis_manifest"],
        gate_dir / "gated_features.parquet",
        root / written["analysis_parquet"],
        plan,
    )


def test_feature_label_analysis_node_reuses_only_intact_inputs_and_outputs(
    tmp_path: Path,
) -> None:
    manifest_path, source_path, output_path, plan = _write_gated_analysis_cache(tmp_path)
    node = FeatureLabelAnalysisNode()

    reference, _ = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is not None

    source_bytes = source_path.read_bytes()
    source_path.write_bytes(b"changed-gated-features")
    stale_reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert stale_reference is None
    assert "input 'gated_features' changed" in reason

    source_path.write_bytes(source_bytes)
    output_path.write_bytes(b"tampered-analysis")
    damaged_reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert damaged_reference is None
    assert "OUTPUT_CHECKSUM_MISMATCH:analysis" in reason
    assert manifest_path.is_file()


def test_feature_label_analysis_node_rejects_legacy_cache_without_provenance(
    tmp_path: Path,
) -> None:
    manifest_path, _source_path, _output_path, plan = _write_gated_analysis_cache(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("input_paths")
    manifest.pop("input_checksums")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reference, reason = FeatureLabelAnalysisNode().resolve_existing_output(plan, {}, tmp_path)

    assert reference is None
    assert "INPUT_MANIFEST_INVALID" in reason


def test_ultrasound_feature_cache_tracks_waveform_tree_and_outputs(tmp_path: Path) -> None:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    slice_id = "AS::feature-cache"
    slice_dir = tmp_path / "analysis_slices" / battery_id / experiment_id / slice_id
    slice_dir.mkdir(parents=True)
    slice_path = slice_dir / "analysis_slice.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::1"],
            "battery_id": [battery_id],
            "experiment_id": [experiment_id],
            "ultrasound_asset_id": ["U001"],
            "event_order_index": [0],
            "waveform_group": ["U001/waveform"],
            "waveform_row_index": [0],
            "elapsed_time_s": [0.0],
        }
    ).to_parquet(slice_path, index=False)
    (slice_dir / "analysis_slice_manifest.json").write_text(
        json.dumps(
            {
                "analysis_slice_id": slice_id,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
            }
        ),
        encoding="utf-8",
    )
    waveform_path = tmp_path / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    waveform_path.parent.mkdir(parents=True)
    waveform_group = zarr.open_group(str(waveform_path), mode="w")
    waveform_group.create_array(
        "U001/waveform", data=np.asarray([[0, 1, 0, -1] * 4], dtype=np.float32)
    )
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        analysis_slice={"analysis_slice_id": slice_id},
    )
    report = extract_ultrasound_features(
        analysis_slice_path=slice_path,
        waveform_store_path=waveform_path,
        output_root=tmp_path,
    )
    node = UltrasoundFeaturesNode()
    inputs = {
        "ANALYSIS_SLICE": ArtifactRef(
            artifact_type="ANALYSIS_SLICE",
            artifact_id=slice_id,
            battery_id=battery_id,
            experiment_id=experiment_id,
            path=str(slice_dir),
            manifest_path=str(slice_dir / "analysis_slice_manifest.json"),
        )
    }
    reference, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert reference is not None, reason

    manifest = json.loads(Path(reference.manifest_path).read_text(encoding="utf-8"))
    assert len(manifest["waveform_store_checksum"]) == 64
    feature_output = Path(reference.manifest_path).parent / "ultrasound_features.parquet"
    feature_bytes = feature_output.read_bytes()
    feature_output.write_bytes(b"tampered-feature-output")
    stale_output, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert stale_output is None
    assert "OUTPUT_CHECKSUM_MISMATCH:features" in reason

    feature_output.write_bytes(feature_bytes)
    waveform_group["U001/waveform"][0, 0] = 3.0
    stale_source, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert stale_source is None
    assert "no reusable feature set matches current slice/waveform content" in reason
    rebuilt = extract_ultrasound_features(
        analysis_slice_path=slice_path,
        waveform_store_path=waveform_path,
        output_root=tmp_path,
    )
    assert rebuilt.feature_set_id != report.feature_set_id
    assert report.feature_set_id == manifest["feature_set_id"]


def test_analysis_slice_cache_verifies_canonical_input_and_output(tmp_path: Path) -> None:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    events_path = (
        tmp_path / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    )
    events_path.parent.mkdir(parents=True)
    events = pd.DataFrame(
        {
            "measurement_event_id": ["ME::1", "ME::2"],
            "battery_id": [battery_id, battery_id],
            "experiment_id": [experiment_id, experiment_id],
            "event_quality_status": ["READY", "READY"],
            "analysis_eligible": [True, True],
            "cycle_index_raw": [1, 1],
        }
    )
    events.to_parquet(events_path, index=False)
    report = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(),
        output_root=tmp_path,
    )
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        analysis_slice={"analysis_slice_id": report.analysis_slice_id},
    )
    node = AnalysisSliceNode()

    reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is not None, reason

    slice_manifest_path = Path(reference.manifest_path)
    slice_output_path = slice_manifest_path.parent / "analysis_slice.parquet"
    output_bytes = slice_output_path.read_bytes()
    slice_output_path.write_bytes(b"tampered-slice-output")
    damaged_output, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert damaged_output is None
    assert "OUTPUT_CHECKSUM_MISMATCH:analysis_slice" in reason

    slice_output_path.write_bytes(output_bytes)
    events.loc[len(events)] = {
        "measurement_event_id": "ME::3",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "event_quality_status": "READY",
        "analysis_eligible": True,
        "cycle_index_raw": 2,
    }
    events.to_parquet(events_path, index=False)
    stale_input, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert stale_input is None
    assert "INPUT_CHECKSUM_MISMATCH:measurement_events" in reason


def test_analysis_slice_resolver_skips_stale_sibling_and_reuses_current_one(
    tmp_path: Path,
) -> None:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    events_path = (
        tmp_path / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    )
    events_path.parent.mkdir(parents=True)
    old_events = pd.DataFrame(
        {
            "measurement_event_id": ["ME::1", "ME::2"],
            "battery_id": [battery_id, battery_id],
            "experiment_id": [experiment_id, experiment_id],
            "event_quality_status": ["READY", "READY"],
            "analysis_eligible": [True, True],
            "cycle_index_raw": [1, 1],
        }
    )
    current_events = pd.concat(
        [
            old_events,
            pd.DataFrame(
                {
                    "measurement_event_id": ["ME::3"],
                    "battery_id": [battery_id],
                    "experiment_id": [experiment_id],
                    "event_quality_status": ["READY"],
                    "analysis_eligible": [True],
                    "cycle_index_raw": [2],
                }
            ),
        ],
        ignore_index=True,
    )
    old_events.to_parquet(events_path, index=False)
    stale_ids: list[str] = []
    for cycle in range(1, 101):
        stale = create_analysis_slice(
            measurement_events_path=events_path,
            spec=ConditionSliceSpec(cycle_indices=[cycle]),
            output_root=tmp_path,
        )
        stale_ids.append(stale.analysis_slice_id)

    current_events.to_parquet(events_path, index=False)
    current = create_analysis_slice(
        measurement_events_path=events_path,
        spec=ConditionSliceSpec(),
        output_root=tmp_path,
    )
    assert any(stale_id < current.analysis_slice_id for stale_id in stale_ids)

    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
    )
    reference, reason = AnalysisSliceNode().resolve_existing_output(plan, {}, tmp_path)

    assert reference is not None, reason
    assert reference.artifact_id == current.analysis_slice_id


def _write_label_cache(root: Path) -> tuple[Path, Path, AnalysisPlan]:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    inputs = {
        "measurement_events": root
        / "multimodal"
        / battery_id
        / experiment_id
        / "measurement_events.parquet",
        "records": root / "electrical" / battery_id / experiment_id / "records.parquet",
        "cycles": root / "electrical" / battery_id / experiment_id / "cycles.parquet",
        "steps": root / "electrical" / battery_id / experiment_id / "steps.parquet",
        "ultrasound_manifest": root
        / "ultrasound"
        / battery_id
        / experiment_id
        / "parser_manifest.json",
    }
    for key, path in inputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if key == "measurement_events":
            pd.DataFrame(
                {
                    "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
                    "battery_id": [battery_id],
                    "experiment_id": [experiment_id],
                    "match_status": ["MATCHED_AMBIGUOUS"],
                    "electrical_asset_id": [None],
                    "electrical_record_locator": [None],
                }
            ).to_parquet(path, index=False)
        elif key == "records":
            pd.DataFrame(
                {
                    "electrical_asset_id": ["EA1"],
                    "source_row_index": [1],
                    "voltage_v": [3.7],
                }
            ).to_parquet(path, index=False)
        elif key in {"cycles", "steps"}:
            pd.DataFrame({"battery_id": [battery_id], "experiment_id": [experiment_id]}).to_parquet(
                path, index=False
            )
        else:
            path.write_bytes(path.name.encode())
    labels_dir = root / "labels" / battery_id / experiment_id
    labels_dir.mkdir(parents=True)
    outputs = {
        "event_labels": labels_dir / "event_labels.parquet",
        "cycle_labels": labels_dir / "cycle_labels.parquet",
        "definitions": labels_dir / "label_definitions.json",
        "tof_readiness": labels_dir / "tof_readiness.json",
    }
    for path in outputs.values():
        path.write_bytes(path.name.encode())
    manifest_path = labels_dir / "label_manifest.json"
    manifest = {
        "label_set_id": "LB::cache-integrity",
        "label_engine_version": ReferenceLabelsNode.node_version,
        "label_definition_version": "0.3.0",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "input_paths": {key: str(path) for key, path in inputs.items()},
        "input_checksums": {key: _checksum(path) for key, path in inputs.items()},
        "output_paths": {key: str(path) for key, path in outputs.items()},
        "output_checksums": {key: _checksum(path) for key, path in outputs.items()},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
    )
    return manifest_path, outputs["event_labels"], plan


def test_reference_label_node_verifies_all_sources_and_outputs(tmp_path: Path) -> None:
    manifest_path, output_path, plan = _write_label_cache(tmp_path)
    node = ReferenceLabelsNode()

    reference, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is not None, reason

    output_bytes = output_path.read_bytes()
    output_path.write_bytes(b"tampered-event-labels")
    stale_output, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert stale_output is None
    assert "OUTPUT_CHECKSUM_MISMATCH:event_labels" in reason

    output_path.write_bytes(output_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["input_checksums"].pop("ultrasound_manifest")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    stale_legacy, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert stale_legacy is None
    assert "INPUT_CHECKSUM_MISSING:ultrasound_manifest" in reason


def test_reference_label_node_rejects_semantically_invalid_inputs_even_with_current_checksums(
    tmp_path: Path,
) -> None:
    manifest_path, _, plan = _write_label_cache(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events_path = Path(manifest["input_paths"]["measurement_events"])
    events = pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["1"],
            "voltage_v": [3.8],
        }
    )
    events.to_parquet(events_path, index=False)
    manifest["input_checksums"]["measurement_events"] = _checksum(events_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reference, reason = ReferenceLabelsNode().resolve_existing_output(plan, {}, tmp_path)

    assert reference is None
    assert "LABEL_INPUT_SEMANTICS_INVALID" in reason
    assert "electrical value mismatch" in reason


def _write_cache_artifact(root: Path, node) -> tuple[Path, Path]:
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_A", experiment_id="EXP_A"),
    )
    output_dir = root / node.output_rel_dir(plan)
    output_dir.mkdir(parents=True)
    if isinstance(node, SynchronizationNode):
        name = "synchronization_manifest.json"
        manifest = {
            "schema_version": SYNCHRONIZATION_SCHEMA_VERSION,
            "sync_engine_version": node.node_version,
        }
        paths = {
            "ultrasound_timestamped": root / "synchronization/CELL_A/EXP_A/timestamped.parquet",
            "electrical_records": root / "electrical/CELL_A/EXP_A/records.parquet",
        }
        outputs = {
            "aligned": output_dir / "aligned_ultrasound_frames.parquet",
            "candidates": output_dir / "synchronization_candidates.parquet",
        }
    else:
        name = "measurement_event_manifest.json"
        manifest = {
            "builder_version": node.node_version,
            "temperature_channel_id": None,
        }
        paths = {
            "aligned": root / "synchronization/CELL_A/EXP_A/aligned.parquet",
            "sync_candidates": root / "synchronization/CELL_A/EXP_A/candidates.parquet",
            "electrical_records": root / "electrical/CELL_A/EXP_A/records.parquet",
        }
        outputs = {
            "events": output_dir / "measurement_events.parquet",
            "candidates": output_dir / "measurement_event_candidates.parquet",
        }
    for path in (*paths.values(), *outputs.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    manifest.update(
        {
            "battery_id": "CELL_A",
            "experiment_id": "EXP_A",
            "input_paths": {key: str(path) for key, path in paths.items()},
            "input_checksums": {key: _checksum(path) for key, path in paths.items()},
            "output_paths": {key: str(path) for key, path in outputs.items()},
            "output_checksums": {key: _checksum(path) for key, path in outputs.items()},
        }
    )
    manifest_path = output_dir / name
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, next(iter(outputs.values()))


@pytest.mark.parametrize("node_type", [SynchronizationNode, MeasurementEventsNode])
def test_node_reuses_only_when_declared_outputs_are_intact(tmp_path: Path, node_type) -> None:
    node = node_type()
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_A", experiment_id="EXP_A"),
    )
    manifest_path, output_path = _write_cache_artifact(tmp_path, node)

    reference, _ = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is not None
    output_path.write_bytes(b"tampered")

    reference, _ = node.resolve_existing_output(plan, {}, tmp_path)
    assert reference is None
    assert manifest_path.is_file()


@pytest.mark.parametrize("node_type", [SynchronizationNode, MeasurementEventsNode])
def test_node_does_not_reuse_when_processed_input_changes(tmp_path: Path, node_type) -> None:
    node = node_type()
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id="CELL_A", experiment_id="EXP_A"),
    )
    manifest_path, _ = _write_cache_artifact(tmp_path, node)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_input = Path(next(iter(manifest["input_paths"].values())))
    first_input.write_bytes(b"changed")

    reference, _ = node.resolve_existing_output(plan, {}, tmp_path)

    assert reference is None


def test_timestamp_node_does_not_reuse_tampered_timestamp_table(tmp_path: Path) -> None:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    node = UltrasoundTimestampsNode()
    plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
    )
    output_dir = tmp_path / node.output_rel_dir(plan)
    output_dir.mkdir(parents=True)
    frames_path = tmp_path / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    anchor_path = output_dir / "time_anchors.json"
    frames_path.parent.mkdir(parents=True)
    frames_path.write_bytes(b"frames")
    anchor_path.write_bytes(b"anchors")
    timestamped_path = output_dir / "timestamped_ultrasound_frames.parquet"
    timestamped_path.write_bytes(b"timestamped frames")
    manifest = {
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "engine_version": node.node_version,
        "input_paths": {
            "frames": str(frames_path),
            "time_anchor_state": str(anchor_path),
        },
        "input_checksums": {
            "frames": _checksum(frames_path),
            "time_anchor_state": _checksum(anchor_path),
        },
        "output_path": str(timestamped_path),
        "output_checksum": _checksum(timestamped_path),
    }
    manifest_path = output_dir / "timestamp_engine_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    ref, _ = node.resolve_existing_output(plan, {}, tmp_path)
    assert ref is not None

    anchor_path.write_bytes(b"changed anchor")
    ref, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert ref is None
    assert "time_anchor_state" in reason and "changed" in reason
    anchor_path.write_bytes(b"anchors")

    manifest["input_checksums"].pop("time_anchor_state")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ref, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert ref is None
    assert "INPUT_CHECKSUM_MISSING:time_anchor_state" in reason
    manifest["input_checksums"]["time_anchor_state"] = _checksum(anchor_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    timestamped_path.write_bytes(b"tampered")
    ref, reason = node.resolve_existing_output(plan, {}, tmp_path)

    assert ref is None
    assert "OUTPUT_CHECKSUM_MISMATCH:timestamped_frames" in reason


def test_label_consumer_integrity_rejects_tampered_reference_soc(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    labels_dir = root / "labels" / "CELL_A" / "EXP_A"
    labels_dir.mkdir(parents=True)
    inputs = {
        key: root / relative
        for key, relative in {
            "measurement_events": "multimodal/CELL_A/EXP_A/measurement_events.parquet",
            "records": "electrical/CELL_A/EXP_A/records.parquet",
            "cycles": "electrical/CELL_A/EXP_A/cycles.parquet",
            "steps": "electrical/CELL_A/EXP_A/steps.parquet",
        }.items()
    }
    outputs = {
        "event_labels": labels_dir / "event_labels.parquet",
        "cycle_labels": labels_dir / "cycle_labels.parquet",
    }
    for path in (*inputs.values(), *outputs.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    manifest = {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "label_set_id": "LS::fixture",
        "input_paths": {key: str(path) for key, path in inputs.items()},
        "input_checksums": {key: _checksum(path) for key, path in inputs.items()},
        "output_paths": {key: str(path) for key, path in outputs.items()},
        "output_checksums": {key: _checksum(path) for key, path in outputs.items()},
    }
    (labels_dir / "label_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    outputs["event_labels"].write_bytes(b"tampered")

    with pytest.raises(APIError, match="integrity verification failed") as error:
        _assert_current_measurement_event_labels(root, "CELL_A", "EXP_A")

    assert "OUTPUT_CHECKSUM_MISMATCH:event_labels" in error.value.details["integrity_reasons"]


def test_split_node_does_not_reuse_tampered_assignments(tmp_path: Path) -> None:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    dataset_id = "DS::fixture"
    plan = AnalysisPlan(
        profile="EVALUATION_SPLIT",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        split={"strategy": "LEAVE_ONE_GROUP_OUT"},
    )
    node = SplitNode()
    spec = SplitSpec(dataset_id=dataset_id)
    split_dir = tmp_path / "splits" / battery_id / experiment_id / dataset_id / spec.split_id
    split_dir.mkdir(parents=True)
    outputs = {
        "split_assignments": split_dir / "split_assignments.parquet",
        "leakage_audit": split_dir / "leakage_audit.json",
        "evaluation_readiness": split_dir / "evaluation_readiness.json",
    }
    for path in outputs.values():
        path.write_bytes(path.name.encode())
    manifest = {
        "split_id": spec.split_id,
        "dataset_id": dataset_id,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "output_checksums": {key: _checksum(path) for key, path in outputs.items()},
    }
    manifest_path = split_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_ref = ArtifactRef(
        artifact_type="DATASET",
        artifact_id=dataset_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        path=str(tmp_path / "datasets"),
        manifest_path=str(tmp_path / "datasets" / "dataset_manifest.json"),
    )
    inputs = {"DATASET": dataset_ref}

    reused, _ = node.resolve_existing_output(plan, inputs, tmp_path)
    assert reused is None  # missing Dataset manifest/source checksums are not reusable
    (tmp_path / "datasets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "datasets" / "dataset.parquet").write_bytes(b"dataset-v1")
    Path(dataset_ref.manifest_path).write_text("{}", encoding="utf-8")
    manifest["source_checksums"] = {
        "dataset_parquet": _checksum(tmp_path / "datasets" / "dataset.parquet"),
        "dataset_manifest": _checksum(Path(dataset_ref.manifest_path)),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reused, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert reused is None, reason  # source is structurally unverifiable without a Dataset contract

    outputs["split_assignments"].write_bytes(b"tampered")
    reused, reason = node.resolve_existing_output(plan, inputs, tmp_path)

    assert reused is None
    assert "OUTPUT_CHECKSUM_MISMATCH:split_assignments" in reason


def _write_model_set_cache(
    root: Path, *, strategies: list[str]
) -> tuple[AnalysisPlan, dict[str, ArtifactRef], Path, Path]:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    dataset_id, split_id = "DS::fixture", "SPLIT::fixture"
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        feature_analysis={"analysis_mode": "TRAIN_ONLY_ML_SAFE"},
        modeling={"strategies": strategies},
    )
    dataset_ref = ArtifactRef(
        artifact_type="DATASET",
        artifact_id=dataset_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        path=str(root / "datasets"),
        manifest_path=str(root / "datasets" / "dataset_manifest.json"),
    )
    split_ref = ArtifactRef(
        artifact_type="SPLIT",
        artifact_id=split_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        path=str(root / "splits"),
        manifest_path=str(root / "splits" / "split_manifest.json"),
    )
    inputs = {"DATASET": dataset_ref, "SPLIT": split_ref}
    selection_dir = root / "feature_analysis" / battery_id / experiment_id / dataset_id / "AN::1"
    selection_dir.mkdir(parents=True)
    (selection_dir / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "analysis_mode": "TRAIN_ONLY_ML_SAFE",
                "target": "soc_reference_percent",
                "split_id": split_id,
                "fold_index": 1,
                "analysis_id": "AN::1",
                "selection": {
                    "commit_status": "CONFIRMED",
                    "selection_id": "SEL::1",
                    "selected_features": ["amplitude_a_u"],
                },
            }
        ),
        encoding="utf-8",
    )
    model_root = root / "models" / battery_id / experiment_id / dataset_id / split_id
    model_root.mkdir(parents=True)
    model_id = "MODEL::fixture"
    model_dir = model_root / model_id
    model_dir.mkdir()
    model_file = model_dir / "model.joblib"
    prediction_file = model_dir / "held_out_predictions.parquet"
    model_file.write_bytes(b"model bytes")
    prediction_file.write_bytes(b"held out rows")
    model_manifest = {
        "model_id": model_id,
        "dataset_id": dataset_id,
        "split_id": split_id,
        "fold_index": 1,
        "selection_id": "SEL::1",
        "strategy": "DUMMY_MEAN",
        "output_checksums": {
            "model": _checksum(model_file),
            "held_out_predictions": _checksum(prediction_file),
        },
    }
    model_manifest_path = model_dir / "model_manifest.json"
    model_manifest_path.write_text(json.dumps(model_manifest), encoding="utf-8")
    comparison_parquet = model_root / "model_comparison.parquet"
    comparison_json = model_root / "model_comparison.json"
    comparison_parquet.write_bytes(b"comparison rows")
    comparison_json.write_text("[]\n", encoding="utf-8")
    model_set_id = (
        "MODELSET::"
        + hashlib.sha256(
            f"{battery_id}:{experiment_id}:{dataset_id}:{split_id}".encode()
        ).hexdigest()[:24]
    )
    model_set_payload = {
        "model_set_id": model_set_id,
        "modeling_policy_version": "0.1.0",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "dataset_id": dataset_id,
        "split_id": split_id,
        "confirmed_fold_selections": ["1:SEL::1"],
        "strategies": ["DUMMY_MEAN"],
        "model_artifacts": [
            {"model_id": model_id, "manifest_sha256": _checksum(model_manifest_path)}
        ],
        "output_checksums": {
            "model_comparison_parquet": _checksum(comparison_parquet),
            "model_comparison_json": _checksum(comparison_json),
        },
    }
    model_set_manifest_path = model_root / "model_set_manifest.json"
    model_set_manifest_path.write_text(json.dumps(model_set_payload), encoding="utf-8")
    return plan, inputs, model_root, prediction_file


def test_model_set_reuse_requires_complete_inventory_and_intact_outputs(tmp_path: Path) -> None:
    plan, inputs, _model_root, predictions = _write_model_set_cache(
        tmp_path, strategies=["DUMMY_MEAN"]
    )
    node = SocModelingNode()

    ref, _ = node.resolve_existing_output(plan, inputs, tmp_path)
    assert ref is not None
    assert ref.artifact_id.startswith("MODELSET::")

    predictions.write_bytes(b"tampered")
    ref, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert ref is None
    assert "held_out_predictions" in reason

    predictions.write_bytes(b"held out rows")
    plan.modeling["strategies"] = ["DUMMY_MEAN", "RIDGE"]
    ref, reason = node.resolve_existing_output(plan, inputs, tmp_path)
    assert ref is None
    assert "strategy inventory changed" in reason or "inventory is incomplete" in reason

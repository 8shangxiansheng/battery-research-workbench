"""T47-T52: dataset persistence contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.datasets.builder import build_soc_dataset
from battery_workbench.datasets.freshness import dataset_freshness
from battery_workbench.datasets.persistence import write_dataset_payload
from battery_workbench.datasets.schemas import DatasetConfig
from battery_workbench.datasets.test_helpers import make_inputs
from battery_workbench.provenance.processed_manifest import (
    content_sha256,
    feature_waveform_store_sha256,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build(tmp_path: Path):
    feats, lbls, cyc = make_inputs()
    report, df = build_soc_dataset(
        features=feats, event_labels=lbls, cycle_labels=cyc, config=DatasetConfig()
    )
    paths = write_dataset_payload(
        report=report,
        df=df,
        config=DatasetConfig(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        dataset_family="SOC",
        feature_set_path=Path("/dev/null"),
        label_set_path=Path("/dev/null"),
        output_root=tmp_path,
    )
    return report, df, paths


def test_parquet_roundtrip_t47(tmp_path: Path) -> None:
    _report, df, paths = _build(tmp_path)
    reread = pd.read_parquet(paths["dataset"])
    assert len(reread) == len(df)
    assert list(reread.columns) == list(df.columns)


def test_schema_persistence_t48(tmp_path: Path) -> None:
    _report, df, paths = _build(tmp_path)
    schema = json.loads(Path(paths["dataset_schema"]).read_text(encoding="utf-8"))
    assert isinstance(schema, list)
    assert len(schema) == len(df.columns)
    for entry in schema:
        for key in ("name", "dtype", "role", "predictor_enabled"):
            assert key in entry


def test_leakage_policy_persistence_t49(tmp_path: Path) -> None:
    _report, _df, paths = _build(tmp_path)
    policy = json.loads(Path(paths["leakage_policy"]).read_text(encoding="utf-8"))
    assert policy["frame_level_random_split_prohibited"] is True
    assert "reasons" in policy
    assert "minimum_safe_grouping_key" in policy


def test_manifest_checksums_t50(tmp_path: Path) -> None:
    report, _df, paths = _build(tmp_path)
    manifest = json.loads(Path(paths["dataset_manifest"]).read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == report.dataset_id
    assert manifest["output_checksum"] != ""
    assert manifest["dataset_builder_version"] == "0.4.0"


def test_dataset_manifest_pins_label_manifest_identity_and_checksum(tmp_path: Path) -> None:
    features, labels, cycles = make_inputs()
    report, frame = build_soc_dataset(
        features=features,
        event_labels=labels,
        cycle_labels=cycles,
        config=DatasetConfig(),
    )
    label_path = tmp_path / "labels/CELL_X/EXP_X/event_labels.parquet"
    label_path.parent.mkdir(parents=True)
    label_path.write_bytes(b"event labels")
    label_manifest_path = label_path.parent / "label_manifest.json"
    label_manifest_path.write_text('{"label_set_id":"LB::writer"}', encoding="utf-8")

    paths = write_dataset_payload(
        report=report,
        df=frame,
        config=DatasetConfig(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        dataset_family="SOC",
        feature_set_path=Path("/dev/null"),
        label_set_path=label_path,
        output_root=tmp_path,
    )
    manifest = json.loads(Path(paths["dataset_manifest"]).read_text(encoding="utf-8"))

    assert manifest["label_set_manifest_path"] == str(label_manifest_path)
    assert manifest["label_set_manifest_checksum"] == _sha256(label_manifest_path)


def test_dataset_manifest_pins_feature_set_manifest_identity_and_checksum(tmp_path: Path) -> None:
    features, labels, cycles = make_inputs()
    report, frame = build_soc_dataset(
        features=features,
        event_labels=labels,
        cycle_labels=cycles,
        config=DatasetConfig(),
    )
    feature_path = tmp_path / "features/CELL_X/EXP_X/AS::writer/FS::writer/features.parquet"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_bytes(b"feature rows")
    feature_manifest_path = feature_path.parent / "feature_set_manifest.json"
    feature_manifest_path.write_text('{"feature_set_id":"FS::writer"}', encoding="utf-8")
    label_path = tmp_path / "labels/CELL_X/EXP_X/event_labels.parquet"
    label_path.parent.mkdir(parents=True)
    label_path.write_bytes(b"event labels")

    paths = write_dataset_payload(
        report=report,
        df=frame,
        config=DatasetConfig(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        dataset_family="SOC",
        feature_set_path=feature_path,
        label_set_path=label_path,
        output_root=tmp_path,
    )
    manifest = json.loads(Path(paths["dataset_manifest"]).read_text(encoding="utf-8"))

    assert manifest["feature_set_manifest_path"] == str(feature_manifest_path)
    assert manifest["feature_set_manifest_checksum"] == _sha256(feature_manifest_path)


def test_dataset_manifest_pins_canonical_tof_sources(tmp_path: Path) -> None:
    feats, labels, cycles = make_inputs()
    feats["tof_us"] = 12.5
    report, frame = build_soc_dataset(
        features=feats,
        event_labels=labels,
        cycle_labels=cycles,
        config=DatasetConfig(),
        selected_features=["tof_us"],
        canonical_tof_checksum="tof-manifest-checksum",
    )
    canonical_manifest = tmp_path / "features_physical/CELL_X/EXP_X/canonical_tof_manifest.json"
    canonical_manifest.parent.mkdir(parents=True)
    canonical_manifest.write_text('{"tof_method_id":"SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"}')
    canonical_data = canonical_manifest.parent / "canonical_tof.parquet"
    canonical_data.write_bytes(b"canonical-tof")

    paths = write_dataset_payload(
        report=report,
        df=frame,
        config=DatasetConfig(),
        battery_id="CELL_X",
        experiment_id="EXP_X",
        dataset_family="SOC",
        feature_set_path=Path("/dev/null"),
        label_set_path=Path("/dev/null"),
        output_root=tmp_path,
        canonical_tof_manifest_path=canonical_manifest,
    )
    manifest = json.loads(Path(paths["dataset_manifest"]).read_text(encoding="utf-8"))

    assert manifest["canonical_tof_manifest_path"] == str(canonical_manifest)
    assert manifest["canonical_tof_manifest_checksum"] == _sha256(canonical_manifest)
    assert manifest["canonical_tof_path"] == str(canonical_data)
    assert manifest["canonical_tof_checksum"] == _sha256(canonical_data)


def test_exclusion_breakdown_t51(tmp_path: Path) -> None:
    _report, df, paths = _build(tmp_path)
    manifest = json.loads(Path(paths["dataset_manifest"]).read_text(encoding="utf-8"))
    assert "exclusion_breakdown" in manifest
    assert manifest["eligible_rows"] == len(df)


def test_input_immutability_t52(tmp_path: Path) -> None:
    feats, lbls, cyc = make_inputs()
    # Inputs are DataFrames, not files — immutability is structural.
    feats_copy = feats.copy(deep=True)
    lbls_copy = lbls.copy(deep=True)
    _report, _df = build_soc_dataset(
        features=feats, event_labels=lbls, cycle_labels=cyc, config=DatasetConfig()
    )
    pd.testing.assert_frame_equal(feats, feats_copy)
    pd.testing.assert_frame_equal(lbls, lbls_copy)


def test_parser_source_integrity_invalidates_materialized_dataset(tmp_path: Path) -> None:
    _report, _df, paths = _build(tmp_path)
    parser_manifest = tmp_path / "electrical/CELL_X/EXP_X/parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    manifest_path = Path(paths["dataset_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assessment = dataset_freshness(tmp_path, manifest_path, manifest)

    assert assessment["freshness_status"] == "STALE_SOURCE"
    assert "SOURCE_PROVENANCE_INVALID:ELECTRICAL" in assessment["freshness_reasons"]


def test_current_raw_asset_mutation_invalidates_dataset_freshness(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    battery_id, experiment_id, dataset_id = "CELL_X", "EXP_X", "DS::raw-check"
    raw_assets = {
        "electrical": ("E_X", "batteries/CELL_X/EXP_X/electrical/source.xlsx", b"electrical"),
        "ultrasound": ("U_X", "batteries/CELL_X/EXP_X/ultrasound/source.txt", b"ultrasound"),
    }
    manifest_rows = ["asset_id,battery_id,experiment_id,modality,relative_path"]
    for modality, (asset_id, relative_path, content) in raw_assets.items():
        source = raw / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        manifest_rows.append(
            f"{asset_id},{battery_id},{experiment_id},{modality},{relative_path}"
        )
        parser_dir = processed / modality / battery_id / experiment_id
        parser_dir.mkdir(parents=True)
        detail_key = "source_asset_details" if modality == "electrical" else "assets"
        path_key = "relative_path" if modality == "electrical" else "source_file"
        outputs = (
            {"records": "records.parquet", "cycles": "cycles.parquet", "steps": "steps.parquet"}
            if modality == "electrical"
            else {"frames": "frames.parquet", "waveforms": "waveforms.zarr"}
        )
        output_checksums = {}
        for output_key, filename in outputs.items():
            output_path = parser_dir / filename
            if output_key == "waveforms":
                output_path.mkdir()
                (output_path / "chunk.bin").write_bytes(b"waveforms")
            else:
                output_path.write_bytes(output_key.encode())
            output_checksums[output_key] = content_sha256(output_path)
        (parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "source_sha256": {asset_id: _sha256(source)},
                    detail_key: [{"asset_id": asset_id, path_key: relative_path}],
                    "output_files": outputs,
                    "output_checksums": output_checksums,
                }
            ),
            encoding="utf-8",
        )
    assets_csv = raw / "manifests" / "data_assets.csv"
    assets_csv.parent.mkdir(parents=True)
    assets_csv.write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")

    feature_path = processed / "features/CELL_X/EXP_X/AS_X/FS_X/features.parquet"
    label_path = processed / "labels/CELL_X/EXP_X/event_labels.parquet"
    cycle_label_path = processed / "labels/CELL_X/EXP_X/cycle_labels.parquet"
    dataset_dir = processed / "datasets/CELL_X/EXP_X/SOC" / dataset_id
    for path, content in (
        (feature_path, b"features"),
        (label_path, b"labels"),
        (cycle_label_path, b"cycle labels"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    dataset_path = dataset_dir / "dataset.parquet"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "battery_id": [battery_id],
            "experiment_id": [experiment_id],
            "soc_reference_percent": [25.0],
            "features": [0.2],
        }
    ).to_parquet(dataset_path, index=False)
    label_manifest_path = label_path.parent / "label_manifest.json"
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LS_X",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "output_paths": {
                    "event_labels": str(label_path.relative_to(processed)),
                    "cycle_labels": str(cycle_label_path.relative_to(processed)),
                },
                "output_checksums": {
                    "event_labels": _sha256(label_path),
                    "cycle_labels": _sha256(cycle_label_path),
                },
            }
        ),
        encoding="utf-8",
    )
    analysis_slice_path = processed / "analysis_slices/CELL_X/EXP_X/AS_X.parquet"
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"slice")
    waveform_store_path = processed / "waveform_inputs/CELL_X/EXP_X/waveforms.zarr"
    waveform_store_path.mkdir(parents=True)
    (waveform_store_path / "chunk.bin").write_bytes(b"waveforms")
    feature_manifest_path = feature_path.parent / "feature_set_manifest.json"
    definitions_path = feature_path.parent / "feature_definitions.json"
    definitions_path.write_text('{"features":["features"]}', encoding="utf-8")
    feature_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS_X",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "analysis_slice_id": "AS_X",
                "analysis_slice_path": str(analysis_slice_path.relative_to(processed)),
                "analysis_slice_checksum": content_sha256(analysis_slice_path),
                "waveform_store_path": str(waveform_store_path.relative_to(processed)),
                "waveform_store_checksum": feature_waveform_store_sha256(waveform_store_path),
                "output_paths": {
                    "features": str(feature_path.relative_to(processed)),
                    "definitions": str(definitions_path.relative_to(processed)),
                },
                "output_checksums": {
                    "features": _sha256(feature_path),
                    "definitions": _sha256(definitions_path),
                },
            }
        ),
        encoding="utf-8",
    )
    dataset_manifest = {
        "dataset_id": dataset_id,
        "dataset_family": "SOC",
        "target_name": "soc_reference_percent",
        "target_column": "soc_reference_percent",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "predictor_columns": ["features"],
        "output_checksum": _sha256(dataset_path),
        "feature_set_id": "FS_X",
        "feature_set_path": "features/CELL_X/EXP_X/AS_X/FS_X/features.parquet",
        "feature_set_checksum": _sha256(feature_path),
        "feature_set_manifest_path": str(feature_manifest_path.relative_to(processed)),
        "feature_set_manifest_checksum": _sha256(feature_manifest_path),
        "label_set_id": "LS_X",
        "label_set_path": "labels/CELL_X/EXP_X/event_labels.parquet",
        "label_set_checksum": _sha256(label_path),
        "label_set_manifest_path": str(label_manifest_path.relative_to(processed)),
        "label_set_manifest_checksum": _sha256(label_manifest_path),
    }
    dataset_manifest_path = dataset_dir / "dataset_manifest.json"
    dataset_manifest_path.write_text(json.dumps(dataset_manifest), encoding="utf-8")

    current = dataset_freshness(
        processed, dataset_manifest_path, dataset_manifest, raw_root=raw
    )
    assert current["freshness_status"] == "FRESH", current["freshness_reasons"]

    (raw / raw_assets["electrical"][1]).write_bytes(b"replaced electrical source")
    stale = dataset_freshness(
        processed, dataset_manifest_path, dataset_manifest, raw_root=raw
    )
    assert stale["freshness_status"] == "STALE_SOURCE"
    assert "SOURCE_RAW_MISMATCH:ELECTRICAL" in stale["freshness_reasons"]


def _tof_dataset_fixture(root: Path) -> tuple[Path, dict[str, object], Path]:
    battery_id, experiment_id, dataset_id = "CELL_X", "EXP_X", "DS::tof"
    feature_path = root / "features/CELL_X/EXP_X/AS_X/FS_X/features.parquet"
    label_path = root / "labels/CELL_X/EXP_X/event_labels.parquet"
    cycle_label_path = root / "labels/CELL_X/EXP_X/cycle_labels.parquet"
    dataset_path = root / "datasets/CELL_X/EXP_X/SOC/DS::tof/dataset.parquet"
    tof_manifest_path = root / "features_physical/CELL_X/EXP_X/canonical_tof_manifest.json"
    for path in (feature_path, label_path, cycle_label_path, tof_manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "battery_id": [battery_id],
            "experiment_id": [experiment_id],
            "soc_reference_percent": [25.0],
            "tof_us": [12.5],
        }
    ).to_parquet(dataset_path, index=False)
    analysis_slice_path = root / "analysis_slices/CELL_X/EXP_X/AS_X.parquet"
    analysis_slice_path.parent.mkdir(parents=True)
    analysis_slice_path.write_bytes(b"slice")
    waveform_store_path = root / "waveform_inputs/CELL_X/EXP_X/waveforms.zarr"
    waveform_store_path.mkdir(parents=True)
    (waveform_store_path / "chunk.bin").write_bytes(b"waveforms")
    feature_manifest_path = feature_path.parent / "feature_set_manifest.json"
    definitions_path = feature_path.parent / "feature_definitions.json"
    definitions_path.write_text('{"features":["features"]}', encoding="utf-8")
    feature_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS_X",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "analysis_slice_id": "AS_X",
                "analysis_slice_path": str(analysis_slice_path.relative_to(root)),
                "analysis_slice_checksum": content_sha256(analysis_slice_path),
                "waveform_store_path": str(waveform_store_path.relative_to(root)),
                "waveform_store_checksum": feature_waveform_store_sha256(waveform_store_path),
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
    label_manifest_path = label_path.parent / "label_manifest.json"
    label_manifest_path.write_text(
        json.dumps(
            {
                "label_set_id": "LS_X",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
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
    tof_data_path = tof_manifest_path.parent / "canonical_tof.parquet"
    tof_data_path.write_bytes(b"canonical tof")
    tof_manifest_payload = {
        "feature_set_id": "FS_X",
        "parameter_set_id": "PS_X",
        "tof_method_id": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
    }
    tof_manifest_path.write_text(json.dumps(tof_manifest_payload), encoding="utf-8")
    manifest = {
        "dataset_id": dataset_id,
        "dataset_family": "SOC",
        "target_name": "soc_reference_percent",
        "target_column": "soc_reference_percent",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "output_checksum": _sha256(dataset_path),
        "feature_set_id": "FS_X",
        "feature_set_path": "features/CELL_X/EXP_X/AS_X/FS_X/features.parquet",
        "feature_set_checksum": _sha256(feature_path),
        "feature_set_manifest_path": str(feature_manifest_path.relative_to(root)),
        "feature_set_manifest_checksum": _sha256(feature_manifest_path),
        "label_set_id": "LS_X",
        "label_set_path": "labels/CELL_X/EXP_X/event_labels.parquet",
        "label_set_checksum": _sha256(label_path),
        "label_set_manifest_path": str(label_manifest_path.relative_to(root)),
        "label_set_manifest_checksum": _sha256(label_manifest_path),
        "predictor_columns": ["tof_us"],
        "parameter_set_id": "PS_X",
        "selected_features": ["tof_us"],
        "tof_method_id": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
        "canonical_tof_path": str(tof_data_path),
        "canonical_tof_checksum": _sha256(tof_data_path),
        "canonical_tof_manifest_path": str(tof_manifest_path),
        "canonical_tof_manifest_checksum": _sha256(tof_manifest_path),
    }
    manifest_path = dataset_path.parent / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest, tof_manifest_path


def test_tof_dataset_freshness_tracks_canonical_manifest_and_integrity(
    tmp_path: Path, monkeypatch
) -> None:
    from battery_workbench.features_physical import canonical_tof

    manifest_path, manifest, tof_manifest_path = _tof_dataset_fixture(tmp_path)
    monkeypatch.setattr(canonical_tof, "canonical_tof_integrity_reasons", lambda *_: [])

    current = dataset_freshness(tmp_path, manifest_path, manifest)
    assert current["freshness_status"] == "FRESH"

    tof_manifest_path.write_text('{"tampered":true}', encoding="utf-8")
    stale = dataset_freshness(tmp_path, manifest_path, manifest)
    assert stale["freshness_status"] == "STALE_SOURCE"
    assert "CANONICAL_TOF_MANIFEST_CHECKSUM_MISMATCH" in stale["freshness_reasons"]

    tof_manifest_path.write_text(
        json.dumps(
            {
                "feature_set_id": "FS_X",
                "parameter_set_id": "PS_X",
                "tof_method_id": "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
            }
        ),
        encoding="utf-8",
    )
    manifest["canonical_tof_manifest_checksum"] = _sha256(tof_manifest_path)
    monkeypatch.setattr(
        canonical_tof,
        "canonical_tof_integrity_reasons",
        lambda *_: ["OUTPUT_CHECKSUM_MISMATCH:canonical_tof"],
    )
    corrupt = dataset_freshness(tmp_path, manifest_path, manifest)
    assert "CANONICAL_TOF_INTEGRITY_INVALID:OUTPUT_CHECKSUM_MISMATCH:canonical_tof" in corrupt[
        "freshness_reasons"
    ]


def test_tof_dataset_legacy_manifest_is_stale(tmp_path: Path) -> None:
    manifest_path, manifest, _ = _tof_dataset_fixture(tmp_path)
    manifest.pop("canonical_tof_manifest_path")
    manifest.pop("canonical_tof_manifest_checksum")

    stale = dataset_freshness(tmp_path, manifest_path, manifest)

    assert stale["freshness_status"] == "STALE_SOURCE"
    assert "CANONICAL_TOF_PROVENANCE_MISSING" in stale["freshness_reasons"]

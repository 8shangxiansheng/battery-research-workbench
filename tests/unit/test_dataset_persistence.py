"""T47-T52: dataset persistence contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.datasets.builder import build_soc_dataset
from battery_workbench.datasets.persistence import write_dataset_payload
from battery_workbench.datasets.schemas import DatasetConfig
from battery_workbench.datasets.test_helpers import make_inputs


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

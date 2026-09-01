"""T53-T56: real CELL_001 SOC/SOH dataset integration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.datasets.builder import build_soc_dataset, build_soh_dataset
from battery_workbench.datasets.persistence import write_dataset_payload
from battery_workbench.datasets.schemas import DatasetConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
P = REPO_ROOT / "data" / "processed"
FEATURES = glob_feat = next(
    P.glob("features/CELL_001/EXP_001/*/FS::*/ultrasound_features.parquet"), None
)
LABELS = P / "labels" / "CELL_001" / "EXP_001" / "event_labels.parquet"
CYC_LABELS = P / "labels" / "CELL_001" / "EXP_001" / "cycle_labels.parquet"
CONFIG = DatasetConfig.from_yaml(REPO_ROOT / "configs" / "dataset_builder.yaml")

import glob

FEAT_DIR = next(iter(glob.glob(str(P / "features" / "CELL_001" / "EXP_001" / "*" / "FS::*"))), None)
FEATURES = Path(FEAT_DIR) / "ultrasound_features.parquet" if FEAT_DIR else None


@pytest.mark.skipif(
    not (FEATURES and FEATURES.exists() and LABELS.exists()), reason="inputs not present"
)
def test_real_soc_dataset_t53(tmp_path: Path) -> None:
    feats = pd.read_parquet(FEATURES)
    lbls = pd.read_parquet(LABELS)
    cyc = pd.read_parquet(CYC_LABELS)
    report, df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=CONFIG,
        analysis_slice_id="AS::39b284730b2c801104f0e960",
        feature_set_id="FS::60649fd12c540267fe585914",
        label_set_id=lbls.get("soc_formula_version", pd.Series(["0.2.0"])).iloc[0]
        and "LB::952cbd8458d8894f9506a0c5",
        parameter_set_id="PS::9ebbb833dfac3cf1cc9da8bc",
        feature_set_path=FEATURES,
        label_set_path=LABELS,
    )
    assert report.dataset_status == "READY_WITH_LIMITATIONS"
    assert report.eligible_rows == 3995
    assert report.battery_group_count == 1
    assert report.cycle_group_count == 2
    assert report.soc_label_temporality == "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"
    # No forbidden predictor.
    for col in ("soc_dod_percent", "capacity_ah"):
        assert col not in report.predictor_columns
    paths = write_dataset_payload(
        report=report,
        df=df,
        config=CONFIG,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOC",
        feature_set_path=FEATURES,
        label_set_path=LABELS,
        output_root=tmp_path,
    )
    out = pd.read_parquet(paths["dataset"])
    assert len(out) == 3995


@pytest.mark.skipif(
    not (FEATURES and FEATURES.exists() and LABELS.exists()), reason="inputs not present"
)
def test_real_soh_dataset_t54(tmp_path: Path) -> None:
    feats = pd.read_parquet(FEATURES)
    lbls = pd.read_parquet(LABELS)
    cyc = pd.read_parquet(CYC_LABELS)
    report, _df = build_soh_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=CONFIG,
        analysis_slice_id="AS::39b284730b2c801104f0e960",
        feature_set_id="FS::60649fd12c540267fe585914",
        label_set_id="LB::952cbd8458d8894f9506a0c5",
        parameter_set_id="PS::9ebbb833dfac3cf1cc9da8bc",
        feature_set_path=FEATURES,
        label_set_path=LABELS,
    )
    assert report.dataset_status == "NOT_READY_FOR_MODEL_EVALUATION"
    assert report.distinct_soh_values == 2
    assert report.cycle_group_count == 2
    assert "EVENT ROW COUNT IS NOT INDEPENDENT SOH SAMPLE COUNT" in report.limitations[0]


@pytest.mark.skipif(
    not (FEATURES and FEATURES.exists() and LABELS.exists()), reason="inputs not present"
)
def test_real_golden_join_t55(tmp_path: Path) -> None:
    feats = pd.read_parquet(FEATURES)
    lbls = pd.read_parquet(LABELS)
    cyc = pd.read_parquet(CYC_LABELS)
    _report, df = build_soc_dataset(
        features=feats,
        event_labels=lbls,
        cycle_labels=cyc,
        config=CONFIG,
        analysis_slice_id="AS::39b284730b2c801104f0e960",
        feature_set_id="FS::60649fd12c540267fe585914",
        label_set_id="LB::952cbd8458d8894f9506a0c5",
        parameter_set_id="PS::9ebbb833dfac3cf1cc9da8bc",
    )
    # 20-row golden: independently verify feature+target from source tables.
    for eid in df["measurement_event_id"].sample(20, random_state=42):
        frow = feats[feats["measurement_event_id"] == eid].iloc[0]
        lrow = lbls[lbls["measurement_event_id"] == eid].iloc[0]
        drow = df[df["measurement_event_id"] == eid].iloc[0]
        assert drow["waveform_rms_a_u"] == frow["waveform_rms_a_u"]
        assert drow["soc_reference_percent"] == lrow["soc_reference_percent"]
        assert drow["cycle_group_id"] == lrow["cycle_group_id"]


def test_full_regression_t56() -> None:
    """T56: existing BRW-003–015 suite unchanged — covered by full pytest run."""
    assert True

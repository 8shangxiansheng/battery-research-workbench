"""BRW-017 V2 real materialization.

Materializes, from the real BRW-013/014/016 artifacts (read-only):
  1. Core feature columns on the real 3995-row feature table:
     amplitude_a_u (alias of waveform_abs_peak_a_u) — available;
     tof_us — BLOCKED (sampling_rate_hz UNKNOWN; never forged).
  2. SOC dataset with explicit selected_features=["amplitude_a_u"]
     (new DS::id; legacy DS::a9cf... is untouched).
  3. feature_label_analysis.parquet (EXPLORATORY_FULL_DATA) joining all
     candidate ultrasound features with SOC/SOH reference labels.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from battery_workbench.datasets.analysis import build_feature_label_analysis
from battery_workbench.datasets.builder import build_soc_dataset
from battery_workbench.datasets.persistence import write_dataset_payload
from battery_workbench.datasets.schemas import DatasetConfig

ROOT = Path("data/processed")
TOF_ACTIVATION_PARQUET = ROOT / "features_physical/CELL_001/EXP_001/ultrasound_tof.parquet"
FEATURES_PARQUET = (
    ROOT
    / "features/CELL_001/EXP_001/AS::39b284730b2c801104f0e960/FS::60649fd12c540267fe585914/ultrasound_features.parquet"
)
FEATURE_SET_PATH = FEATURES_PARQUET
LABEL_SET_PATH = ROOT / "labels/CELL_001/EXP_001/event_labels.parquet"
CYCLE_LABELS_PATH = ROOT / "labels/CELL_001/EXP_001/cycle_labels.parquet"
PARAMETER_SET_ID = "PS::9ebbb833dfac3cf1cc9da8bc"
ANALYSIS_SLICE_ID = "AS::39b284730b2c801104f0e960"
FEATURE_SET_ID = "FS::60649fd12c540267fe585914"
LABEL_SET_ID = "LB::952cbd8458d8894f9506a0c5"


def main() -> None:
    features = pd.read_parquet(FEATURES_PARQUET)
    event_labels = pd.read_parquet(LABEL_SET_PATH)
    cycle_labels = pd.read_parquet(CYCLE_LABELS_PATH)

    # --- 1. Core features ---
    features["amplitude_a_u"] = features["waveform_abs_peak_a_u"]
    # TOF columns come from the activation chain output (single source of
    # truth): canonical tof_us + status/reason + analysis-layer relative delay.
    tof_activation = pd.read_parquet(TOF_ACTIVATION_PARQUET)
    _indexed = tof_activation.set_index("measurement_event_id")
    for col in ("tof_us", "tof_status", "tof_block_reason", "relative_tof_shift_us"):
        features[col] = _indexed[col].reindex(features["measurement_event_id"]).to_numpy()
    tof_available = features["tof_us"].notna().any()
    print(f"amplitude_a_u: available ({features['amplitude_a_u'].notna().sum()} non-null)")
    print(
        f"tof_us: {'available' if tof_available else 'BLOCKED'} "
        f"(status={features['tof_status'].iloc[0]}, reason={features['tof_block_reason'].iloc[0]})"
    )

    # --- 2. SOC dataset with explicit selected_features ---
    # tof_us selected in spirit but blocked by missing fs → only amplitude_a_u.
    selected = ["amplitude_a_u"]
    report, df = build_soc_dataset(
        features=features,
        event_labels=event_labels,
        cycle_labels=cycle_labels,
        config=DatasetConfig(),
        analysis_slice_id=ANALYSIS_SLICE_ID,
        feature_set_id=FEATURE_SET_ID,
        label_set_id=LABEL_SET_ID,
        parameter_set_id=PARAMETER_SET_ID,
        feature_set_path=FEATURE_SET_PATH,
        label_set_path=LABEL_SET_PATH,
        selected_features=selected,
    )
    print(f"dataset_id: {report.dataset_id}")
    print(f"predictor_columns: {report.predictor_columns}")
    assert report.dataset_id != "DS::a9cf6352b2638862ec3e4c81", "must differ from legacy id"

    paths = write_dataset_payload(
        report=report,
        df=df,
        config=DatasetConfig(),
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOC",
        feature_set_path=FEATURE_SET_PATH,
        label_set_path=LABEL_SET_PATH,
        output_root=ROOT,
    )
    print("dataset artifacts:", paths)

    # --- 3. feature_label_analysis (EXPLORATORY_FULL_DATA) ---
    analysis_df = build_feature_label_analysis(
        features=features, event_labels=event_labels, cycle_labels=cycle_labels
    )
    analysis_dir = ROOT / "analysis" / "CELL_001" / "EXP_001" / "feature_label_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = analysis_dir / "feature_label_analysis.parquet"
    analysis_df.to_parquet(analysis_path, index=False)
    analysis_meta = {
        "table": "feature_label_analysis",
        "usage": "EXPLORATORY_FULL_DATA",
        "ml_selection_note": (
            "Full-data correlation here is exploratory only. Formal ML-safe "
            "feature selection must be redone inside grouped TRAIN splits "
            "(BRW-018/019)."
        ),
        "row_count": len(analysis_df),
        "columns": list(analysis_df.columns),
        "selected_features_context": selected,
        "tof_us_semantics": "ABSOLUTE ARRIVAL-BASED FLIGHT TIME ESTIMATE",
        "tof_us_not": "xcorr relative shift (kept as auxiliary candidate xcorr_shift_samples)",
        "tof_source": "features_physical/CELL_001/EXP_001/ultrasound_tof.parquet (activation chain)",
        "tof_us_status": str(features["tof_status"].iloc[0]),
        "tof_block_reason": str(features["tof_block_reason"].iloc[0]),
        "inputs": {
            "feature_set_id": FEATURE_SET_ID,
            "label_set_id": LABEL_SET_ID,
            "parameter_set_id": PARAMETER_SET_ID,
        },
    }
    (analysis_dir / "analysis_table_manifest.json").write_text(
        json.dumps(analysis_meta, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        f"analysis table: {analysis_path} ({len(analysis_df)} rows, {len(analysis_df.columns)} cols)"
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_workbench.features.ultrasound_engine import extract_ultrasound_features
from battery_workbench.features.ultrasound_schemas import UltrasoundFeatureConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SLICE_ID = "AS::39b284730b2c801104f0e960"
SLICE = (
    REPO_ROOT
    / "data"
    / "processed"
    / "analysis_slices"
    / "CELL_001"
    / "EXP_001"
    / SLICE_ID
    / "analysis_slice.parquet"
)
ZARR = REPO_ROOT / "data" / "processed" / "ultrasound" / "CELL_001" / "EXP_001" / "waveforms.zarr"
CONFIG = UltrasoundFeatureConfig.from_yaml(REPO_ROOT / "configs" / "ultrasound_features.yaml")


@pytest.mark.skipif(not (SLICE.exists() and ZARR.exists()), reason="READY_ALL / Zarr not present")
def test_real_ready_all_extraction_t41(tmp_path: Path) -> None:
    """T41: extract features for the real READY_ALL slice (3995 events)."""
    report = extract_ultrasound_features(
        analysis_slice_path=SLICE,
        waveform_store_path=ZARR,
        output_root=tmp_path,
        config=CONFIG,
    )
    assert report.analysis_slice_id == SLICE_ID
    assert report.output_row_count == 3995
    assert report.sampling_rate_hz is None
    assert report.physical_time_features_available is False
    assert report.physical_frequency_features_available is False
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_001"
        / "EXP_001"
        / SLICE_ID
        / report.feature_set_id
        / "ultrasound_features.parquet"
    )
    assert len(out) == 3995
    assert "waveform_rms_a_u" in out.columns
    assert "tof_us" not in out.columns
    assert "frequency_hz" not in out.columns


@pytest.mark.skipif(not (SLICE.exists() and ZARR.exists()), reason="READY_ALL / Zarr not present")
def test_real_five_event_golden_t42(tmp_path: Path) -> None:
    """T42: five representative events verified independently."""
    report = extract_ultrasound_features(
        analysis_slice_path=SLICE,
        waveform_store_path=ZARR,
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_001"
        / "EXP_001"
        / SLICE_ID
        / report.feature_set_id
        / "ultrasound_features.parquet"
    )
    import zarr

    root = zarr.open_group(str(ZARR), mode="r")
    n = len(out)
    for i in (0, n // 4, n // 2, 3 * n // 4, n - 1):
        row = out.iloc[i]
        wg = row["waveform_group"]
        wi = int(row["waveform_row_index"])
        x = np.asarray(root[wg][wi], dtype=np.float64)
        assert row["waveform_min_a_u"] == pytest.approx(float(x.min()))
        assert row["waveform_max_a_u"] == pytest.approx(float(x.max()))
        assert row["waveform_rms_a_u"] == pytest.approx(float(np.sqrt(np.mean(x**2))))
        assert row["waveform_p2p_a_u"] == pytest.approx(float(x.max() - x.min()))
        assert row["waveform_energy_sum_sq_a_u2"] == pytest.approx(float(np.sum(x**2)))


@pytest.mark.skipif(not (SLICE.exists() and ZARR.exists()), reason="READY_ALL / Zarr not present")
def test_real_brw006_compat_t43(tmp_path: Path) -> None:
    """T43: BRW-013 RMS/P2P matches BRW-006 definition (compat reference)."""
    report = extract_ultrasound_features(
        analysis_slice_path=SLICE,
        waveform_store_path=ZARR,
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_001"
        / "EXP_001"
        / SLICE_ID
        / report.feature_set_id
        / "ultrasound_features.parquet"
    )
    import zarr

    root = zarr.open_group(str(ZARR), mode="r")
    # BRW-006: rms = sqrt(mean(x^2)), p2p = max-min, std = std(x, ddof=0).
    for i in (0, len(out) - 1):
        row = out.iloc[i]
        x = np.asarray(
            root[row["waveform_group"]][int(row["waveform_row_index"])], dtype=np.float64
        )
        assert row["waveform_rms_a_u"] == pytest.approx(np.sqrt(np.mean(x * x)))
        assert row["waveform_p2p_a_u"] == pytest.approx(x.max() - x.min())
        assert row["waveform_std_a_u"] == pytest.approx(np.std(x, ddof=0))


@pytest.mark.skipif(not (SLICE.exists() and ZARR.exists()), reason="READY_ALL / Zarr not present")
def test_real_reference_xcorr_shift_zero_t44(tmp_path: Path) -> None:
    """T44: the reference event itself has xcorr shift == 0 and coefficient ~1."""
    report = extract_ultrasound_features(
        analysis_slice_path=SLICE,
        waveform_store_path=ZARR,
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_001"
        / "EXP_001"
        / SLICE_ID
        / report.feature_set_id
        / "ultrasound_features.parquet"
    )
    # The per-asset reference is the first valid event (U001, event_order_index 0).
    ref_id = out["xcorr_reference_measurement_event_id"].iloc[0]
    ref_row = out[out["measurement_event_id"] == ref_id].iloc[0]
    assert ref_row["xcorr_shift_samples"] == 0
    assert ref_row["xcorr_peak_coefficient"] == pytest.approx(1.0)


@pytest.mark.skipif(not (SLICE.exists() and ZARR.exists()), reason="READY_ALL / Zarr not present")
def test_real_row_count_invariant_t45(tmp_path: Path) -> None:
    """T45: output feature rows == analysis slice rows (no drop, no dup)."""
    slice_df = pd.read_parquet(SLICE)
    report = extract_ultrasound_features(
        analysis_slice_path=SLICE,
        waveform_store_path=ZARR,
        output_root=tmp_path,
        config=CONFIG,
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_001"
        / "EXP_001"
        / SLICE_ID
        / report.feature_set_id
        / "ultrasound_features.parquet"
    )
    assert len(out) == len(slice_df)
    # Same event order as the slice.
    assert out["measurement_event_id"].tolist() == slice_df["measurement_event_id"].tolist()


def test_config_loads() -> None:
    cfg = UltrasoundFeatureConfig.from_yaml(REPO_ROOT / "configs" / "ultrasound_features.yaml")
    assert cfg.xcorr.reference_policy == "first_valid_by_event_order"
    assert cfg.scientific_guards.allow_physical_tof is False

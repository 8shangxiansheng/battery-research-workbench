from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import zarr

from battery_workbench.features.ultrasound_engine import extract_ultrasound_features
from battery_workbench.features.ultrasound_schemas import UltrasoundFeatureConfig


def _slice_df(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_event_id": [f"ME::CELL_X::EXP_X::U001::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "event_order_index": list(range(n)),
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * n),
            "elapsed_time_s": [float(i * 10) for i in range(n)],
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
            "cycle_index_raw": [1.0] * n,
            "step_index_raw": [1.0] * n,
            "step_type": ["恒流充电"] * n,
            "voltage_v": [3.5] * n,
            "current_a": [1.0] * n,
            "capacity_ah": [0.0] * n,
            "temperature_c": [25.0] * n,
            "soc_dod_percent": [10.0] * n,
            "sync_error_s": [0.03] * n,
            "event_quality_status": ["READY"] * n,
            "analysis_eligible": [True] * n,
        }
    )


def _write_zarr(root: Path, frames: int = 8, samples: int = 16) -> Path:
    zpath = root / "waveforms.zarr"
    g = zarr.open_group(str(zpath), mode="w")
    arr = g.create_array("U001/waveform", data=np.zeros((frames, samples), dtype=np.int32))
    arr.attrs["sampling_rate_hz"] = None
    arr.attrs["asset_id"] = "U001"
    return zpath


def _config() -> UltrasoundFeatureConfig:
    return UltrasoundFeatureConfig()


def _write_slice(tmp_path: Path, n: int = 4) -> Path:
    """Write the slice under an AS::-prefixed directory so the engine can infer it."""
    d = tmp_path / "AS::slicetest"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "analysis_slice.parquet"
    _slice_df(n).to_parquet(p, index=False)
    # Write a minimal manifest so the engine can resolve identity even for empty slices.
    import json

    (d / "analysis_slice_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_X",
                "experiment_id": "EXP_X",
                "analysis_slice_id": "AS::slicetest",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_deterministic_feature_set_id_t20(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r1 = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    r2 = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    assert r1.feature_set_id == r2.feature_set_id
    assert r1.feature_set_id.startswith("FS::")


def test_preserve_event_id_and_row_count_t23(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    assert len(out) == 4
    assert "measurement_event_id" in out.columns


def test_preserve_order_t24(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    assert out["frame_index_raw"].tolist() == [0, 1, 2, 3]


def test_no_waveform_arrays_t27(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    for forbidden in (
        "waveform",
        "samples",
        "raw_waveform",
        "tof_us",
        "frequency_hz",
        "frequency_mhz",
        "fft_peak_hz",
    ):
        assert forbidden not in out.columns


def test_nonfinite_policy_t28(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = tmp_path / "waveforms.zarr"
    g = zarr.open_group(str(zpath), mode="w")
    arr = g.create_array("U001/waveform", data=np.zeros((4, 16), dtype=np.float64))
    arr[1] = np.nan  # a nonfinite frame
    arr.attrs["sampling_rate_hz"] = None
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    # Row preserved with NONFINITE status; numeric features null.
    assert len(out) == 4
    assert out["feature_status"].iloc[1] == "NONFINITE_WAVEFORM"
    assert pd.isna(out["waveform_rms_a_u"].iloc[1])


def test_empty_slice_t29(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    pd.DataFrame(columns=_slice_df(0).columns).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    assert len(out) == 0
    assert "measurement_event_id" in out.columns


def test_input_immutable_t40(tmp_path: Path) -> None:
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    before = _sha256(slice_p)
    zpath = _write_zarr(tmp_path)
    extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    assert _sha256(slice_p) == before


def test_no_filter_or_alignment_t34_t35(tmp_path: Path) -> None:
    """Engine must not filter or align waveforms — it only loads by locator."""
    slice_p = _write_slice(tmp_path)
    _slice_df(4).to_parquet(slice_p, index=False)
    zpath = _write_zarr(tmp_path)
    r = extract_ultrasound_features(
        analysis_slice_path=slice_p,
        waveform_store_path=zpath,
        output_root=tmp_path,
        config=_config(),
    )
    out = pd.read_parquet(
        tmp_path
        / "features"
        / "CELL_X"
        / "EXP_X"
        / r.analysis_slice_id
        / r.feature_set_id
        / "ultrasound_features.parquet"
    )
    # All rows present (no filtering); waveform locators preserved unchanged.
    assert len(out) == 4
    assert out["waveform_row_index"].tolist() == [0, 1, 2, 3]

"""Deterministic feature-series materialization shared by preview and datasets."""

from __future__ import annotations

from pathlib import Path

import numpy as np

PREDEFINED_PHYSICAL_CODES = frozenset(
    {"BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTEN_MAX", "ATTEN_MEAN", "ATTEN_ENERGY", "BPS"}
)

ALIAS_TO_RAW: dict[str, str] = {
    "amplitude_a_u": "waveform_abs_peak_a_u",
    "waveform_mean_a_u": "waveform_mean_a_u",
    "waveform_std_a_u": "waveform_std_a_u",
    "waveform_max_a_u": "waveform_max_a_u",
    "waveform_min_a_u": "waveform_min_a_u",
    "waveform_p2p_a_u": "waveform_p2p_a_u",
    "waveform_rms_a_u": "waveform_rms_a_u",
    "envelope_peak_a_u": "envelope_peak_a_u",
    "waveform_abs_peak_a_u": "waveform_abs_peak_a_u",
}


def load_waveform_frames(store: Path, frames_meta: object) -> np.ndarray:
    """Load frames in metadata order, including multi-asset Zarr groups."""
    import pandas as pd
    import zarr

    if isinstance(frames_meta, (str, Path)):
        metadata = pd.read_parquet(
            frames_meta, columns=["waveform_group", "waveform_row_index"]
        )
    else:
        metadata = pd.DataFrame(frames_meta)[["waveform_group", "waveform_row_index"]]
    if metadata.empty:
        return np.empty((0, 0), dtype=np.float64)
    group = zarr.open_group(str(store), mode="r")
    rows: list[np.ndarray] = []
    for item in metadata.itertuples(index=False):
        rows.append(np.asarray(group[str(item.waveform_group)][int(item.waveform_row_index)]))
    return np.asarray(rows, dtype=np.float64)


def selected_feature_series(frames: np.ndarray, features: list[str]) -> dict[str, np.ndarray]:
    """Compute requested catalogue, physical, and raw feature series."""
    from battery_workbench.features.envelope import compute_envelope_features
    from battery_workbench.features.matlab_features import (
        FD_CODES,
        TD_CODES,
        compute_frequency_domain,
        compute_time_domain,
    )
    from battery_workbench.features.physical_v2 import (
        bottom_attenuation_explicit,
        bottom_wave_amplitude,
        bottom_wave_phase_shift,
        surface_bottom_xcorr_tof,
        surface_wave_amplitude,
    )
    from battery_workbench.features.raw_features import compute_raw_amplitude_features
    from battery_workbench.features.spectral_transform import (
        SpectralTransformDefinition,
        spectrum_from_waveform,
    )

    requested = set(features)
    out: dict[str, np.ndarray] = {}
    physical = {
        "BOTTOM_AMP": lambda: bottom_wave_amplitude(frames)["raw"],
        "SWA": lambda: surface_wave_amplitude(frames)["raw"],
        "TOF_XCORR": lambda: surface_bottom_xcorr_tof(frames)["tof_samples"],
        "ATTEN_MAX": lambda: bottom_attenuation_explicit(frames)["amp_max"],
        "ATTEN_MEAN": lambda: bottom_attenuation_explicit(frames)["amp_mean"],
        "ATTEN_ENERGY": lambda: bottom_attenuation_explicit(frames)["amp_energy"],
        "BPS": lambda: bottom_wave_phase_shift(frames)["raw_radian"],
    }
    for code in sorted(requested & PREDEFINED_PHYSICAL_CODES):
        out[code] = np.asarray(physical[code](), dtype=np.float64)

    td_needed = sorted(requested & set(TD_CODES))
    fd_needed = sorted(requested & set(FD_CODES))
    td_rows = {code: [] for code in td_needed}
    fd_rows = {code: [] for code in fd_needed}
    transform = SpectralTransformDefinition(spectral_transform_id="SELECTED_FEATURE_DEFAULT")
    for frame in frames:
        signal = np.asarray(frame, dtype=np.float64)
        if td_needed:
            values = compute_time_domain(signal)
            for code in td_needed:
                td_rows[code].append(float(values[code]))
        if fd_needed:
            frequency, spectrum = spectrum_from_waveform(signal, transform)
            values = compute_frequency_domain(frequency, spectrum)
            for code in fd_needed:
                fd_rows[code].append(float(values[code]))
    out.update({code: np.asarray(values) for code, values in td_rows.items()})
    out.update({code: np.asarray(values) for code, values in fd_rows.items()})

    alias_requests = {code: ALIAS_TO_RAW[code] for code in requested if code in ALIAS_TO_RAW}
    if alias_requests:
        raw_names = set(alias_requests.values())
        raw_rows = {name: [] for name in raw_names}
        for frame in frames:
            values = compute_raw_amplitude_features(np.asarray(frame, dtype=np.float64))
            for name in raw_names:
                value = values.get(name)
                raw_rows[name].append(float(value) if value is not None else np.nan)
        for code, raw_name in alias_requests.items():
            out[code] = np.asarray(raw_rows[raw_name], dtype=np.float64)

    if "envelope_peak_a_u" in requested:
        out["envelope_peak_a_u"] = np.asarray(
            [
                float(compute_envelope_features(np.asarray(frame, dtype=np.float64))["envelope_peak_a_u"])
                for frame in frames
            ]
        )
    return out

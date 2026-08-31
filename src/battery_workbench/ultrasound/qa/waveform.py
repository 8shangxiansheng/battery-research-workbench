from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.ultrasound.qa.anomalies import anomaly
from battery_workbench.ultrasound.qa.schemas import QAAnomaly, UltrasoundQAConfig


def robust_outlier_mask(values: np.ndarray, mad_k: float) -> np.ndarray:
    finite = np.isfinite(values)
    result = np.zeros(len(values), dtype=bool)
    if not finite.any():
        return result
    center = float(np.median(values[finite]))
    mad = float(np.median(np.abs(values[finite] - center)))
    if mad == 0:
        result[finite] = values[finite] != center
    else:
        result[finite] = np.abs(values[finite] - center) / (1.4826 * mad) > mad_k
    return result


def analyze_waveforms(
    frames: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    config: UltrasoundQAConfig,
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]], list[QAAnomaly]]:
    quality_parts: list[pd.DataFrame] = []
    issues: list[QAAnomaly] = []
    asset_summaries: list[dict[str, Any]] = []
    all_values: list[np.ndarray] = []
    total_rail_hits = 0
    rails_known = config.saturation.adc_min is not None and config.saturation.adc_max is not None
    for asset_id, group in frames.groupby("ultrasound_asset_id", sort=False):
        asset_name = str(asset_id)
        if asset_name not in arrays:
            continue
        locators = group["waveform_row_index"].astype(int).to_numpy()
        array = arrays[asset_name]
        if len(locators) == 0 or np.any(locators < 0) or np.any(locators >= len(array)):
            continue
        values = np.asarray(array[locators], dtype=np.float64)
        all_values.append(values)
        waveform_min = np.min(values, axis=1)
        waveform_max = np.max(values, axis=1)
        waveform_mean = np.mean(values, axis=1)
        waveform_std = np.std(values, axis=1)
        waveform_rms = np.sqrt(np.mean(values * values, axis=1))
        waveform_p2p = waveform_max - waveform_min
        zero_fraction = np.mean(values == 0, axis=1)
        all_zero = np.all(values == 0, axis=1)
        constant = np.ptp(values, axis=1) == 0
        nonfinite = ~np.isfinite(values).all(axis=1)
        extreme_fraction = np.mean(
            (values == waveform_min[:, None]) | (values == waveform_max[:, None]), axis=1
        )
        rail_hits = np.zeros(len(values), dtype=int)
        if rails_known:
            rail_hits = np.sum(
                (values == config.saturation.adc_min) | (values == config.saturation.adc_max),
                axis=1,
            )
            total_rail_hits += int(rail_hits.sum())
        quality = pd.DataFrame(
            {
                "battery_id": group["battery_id"].astype(str).to_numpy(),
                "experiment_id": group["experiment_id"].astype(str).to_numpy(),
                "ultrasound_asset_id": group["ultrasound_asset_id"].astype(str).to_numpy(),
                "frame_index_raw": group["frame_index_raw"].astype(int).to_numpy(),
                "elapsed_time_s": group["elapsed_time_s"].astype(float).to_numpy(),
                "waveform_min": waveform_min,
                "waveform_max": waveform_max,
                "waveform_mean": waveform_mean,
                "waveform_std": waveform_std,
                "waveform_rms": waveform_rms,
                "waveform_p2p": waveform_p2p,
                "zero_sample_fraction": zero_fraction,
                "all_zero_frame_flag": all_zero,
                "constant_frame_flag": constant,
                "nan_or_nonfinite_flag": nonfinite,
                "extreme_plateau_fraction": extreme_fraction,
                "rail_hit_count": rail_hits,
            }
        )
        for flag_index in np.flatnonzero(all_zero):
            issues.append(
                _frame_anomaly(
                    quality,
                    int(flag_index),
                    "ALL_ZERO_FRAME",
                    "critical" if config.waveform.all_zero_is_critical else "warning",
                    "All waveform samples are zero",
                )
            )
        for flag_index in np.flatnonzero(constant & ~all_zero):
            issues.append(
                _frame_anomaly(
                    quality,
                    int(flag_index),
                    "CONSTANT_FRAME",
                    "warning",
                    "All waveform samples have one constant non-zero value",
                )
            )
        for flag_index in np.flatnonzero(nonfinite):
            issues.append(
                _frame_anomaly(
                    quality,
                    int(flag_index),
                    "NONFINITE_WAVEFORM",
                    "critical",
                    "Waveform contains NaN or nonfinite values",
                )
            )
        for metric, code in (
            ("waveform_rms", "RMS_OUTLIER"),
            ("waveform_p2p", "P2P_OUTLIER"),
            ("waveform_mean", "DC_OFFSET_OUTLIER"),
        ):
            mask = robust_outlier_mask(quality[metric].to_numpy(float), config.outlier.mad_k)
            for flag_index in np.flatnonzero(mask):
                issues.append(
                    _frame_anomaly(
                        quality,
                        int(flag_index),
                        code,
                        "warning",
                        f"{metric} is a robust MAD outlier",
                        metrics={metric: float(quality[metric].iloc[flag_index])},
                    )
                )
        possible = extreme_fraction >= config.saturation.extreme_plateau_warning_fraction
        for flag_index in np.flatnonzero(possible):
            issues.append(
                _frame_anomaly(
                    quality,
                    int(flag_index),
                    "POSSIBLE_SATURATION",
                    "warning",
                    "Repeated extreme-value plateau exceeds the configured fraction",
                    metrics={
                        "extreme_plateau_fraction": float(extreme_fraction[flag_index]),
                        "adc_rails_known": rails_known,
                        "rail_hit_count": int(rail_hits[flag_index]),
                    },
                )
            )
        asset_summaries.append(
            {
                "asset_id": asset_name,
                "frame_count": len(quality),
                "waveform_sample_count": values.shape[1],
                "waveform_min": int(waveform_min.min()),
                "waveform_max": int(waveform_max.max()),
                "rms_min": float(waveform_rms.min()),
                "rms_median": float(np.median(waveform_rms)),
                "rms_max": float(waveform_rms.max()),
                "p2p_min": float(waveform_p2p.min()),
                "p2p_median": float(np.median(waveform_p2p)),
                "p2p_max": float(waveform_p2p.max()),
                "dc_min": float(waveform_mean.min()),
                "dc_median": float(np.median(waveform_mean)),
                "dc_max": float(waveform_mean.max()),
                "all_zero_frame_count": int(all_zero.sum()),
                "constant_frame_count": int(constant.sum()),
            }
        )
        quality_parts.append(quality)
    quality_frame = pd.concat(quality_parts, ignore_index=True) if quality_parts else pd.DataFrame()
    if all_values:
        combined = np.concatenate(all_values, axis=0)
        global_min = np.min(combined)
        global_max = np.max(combined)
        summary = {
            "global_min": int(global_min),
            "global_max": int(global_max),
            "repeated_global_min_count": int(np.count_nonzero(combined == global_min)),
            "repeated_global_max_count": int(np.count_nonzero(combined == global_max)),
            "rms": _stats(quality_frame["waveform_rms"].to_numpy(float)),
            "p2p": _stats(quality_frame["waveform_p2p"].to_numpy(float)),
            "mean_dc": _stats(quality_frame["waveform_mean"].to_numpy(float)),
            "all_zero_frame_count": int(quality_frame["all_zero_frame_flag"].sum()),
            "constant_frame_count": int(quality_frame["constant_frame_flag"].sum()),
            "nonfinite_frame_count": int(quality_frame["nan_or_nonfinite_flag"].sum()),
            "adc_rails_known": rails_known,
            "rail_hit_count": total_rail_hits,
        }
    else:
        summary = {
            "global_min": None,
            "global_max": None,
            "repeated_global_min_count": 0,
            "repeated_global_max_count": 0,
            "all_zero_frame_count": 0,
            "constant_frame_count": 0,
            "nonfinite_frame_count": 0,
            "adc_rails_known": rails_known,
            "rail_hit_count": 0,
        }
    return quality_frame, summary, asset_summaries, issues


def _stats(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "median": float(np.median(values)),
        "max": float(np.max(values)),
    }


def _frame_anomaly(
    quality: pd.DataFrame,
    index: int,
    code: str,
    severity: str,
    message: str,
    *,
    metrics: dict[str, Any] | None = None,
) -> QAAnomaly:
    row = quality.iloc[index]
    return anomaly(
        code,
        severity,
        "frame",
        message,
        asset_id=str(row["ultrasound_asset_id"]),
        frame_index_raw=int(row["frame_index_raw"]),
        metrics=metrics,
    )

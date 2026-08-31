from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from battery_workbench.ultrasound.qa.anomalies import anomaly
from battery_workbench.ultrasound.qa.schemas import QAAnomaly, UltrasoundQAConfig
from battery_workbench.ultrasound.qa.waveform import robust_outlier_mask


def analyze_cross_frame(
    quality: pd.DataFrame,
    frames: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    config: UltrasoundQAConfig,
) -> tuple[pd.DataFrame, dict[str, Any], list[QAAnomaly]]:
    if quality.empty:
        return quality, {}, []
    output_parts: list[pd.DataFrame] = []
    issues: list[QAAnomaly] = []
    correlations: list[np.ndarray] = []
    for asset_id, asset_quality in quality.groupby("ultrasound_asset_id", sort=False):
        asset_name = str(asset_id)
        metadata = frames[frames["ultrasound_asset_id"].astype(str) == asset_name]
        locators = metadata["waveform_row_index"].astype(int).to_numpy()
        values = np.asarray(arrays[asset_name][locators], dtype=np.float64)
        means = values.mean(axis=1)
        centered = values - means[:, None]
        norms = np.linalg.norm(centered, axis=1)
        correlation = np.full(len(values), np.nan)
        if len(values) > 1:
            denominator = norms[1:] * norms[:-1]
            valid = denominator > 0
            adjacent = np.full(len(values) - 1, np.nan)
            adjacent[valid] = (
                np.einsum("ij,ij->i", centered[1:][valid], centered[:-1][valid])
                / denominator[valid]
            )
            correlation[1:] = adjacent
        part = asset_quality.copy()
        part["adjacent_frame_correlation"] = correlation
        part["delta_rms"] = np.r_[np.nan, np.abs(np.diff(part["waveform_rms"]))]
        part["delta_p2p"] = np.r_[np.nan, np.abs(np.diff(part["waveform_p2p"]))]
        part["delta_mean"] = np.r_[np.nan, np.abs(np.diff(part["waveform_mean"]))]
        for flag_index in np.flatnonzero(correlation < config.correlation.low_adjacent_warning):
            issues.append(
                _issue(
                    part,
                    int(flag_index),
                    "LOW_ADJACENT_CORRELATION",
                    "Adjacent waveform Pearson correlation is below the configured threshold",
                    {"correlation": float(correlation[flag_index])},
                )
            )
        for metric, code in (
            ("delta_rms", "FRAME_RMS_JUMP"),
            ("delta_p2p", "FRAME_P2P_JUMP"),
            ("delta_mean", "FRAME_DC_JUMP"),
        ):
            mask = robust_outlier_mask(part[metric].to_numpy(float), config.outlier.mad_k)
            for flag_index in np.flatnonzero(mask):
                issues.append(
                    _issue(
                        part,
                        int(flag_index),
                        code,
                        f"{metric} is a robust MAD jump outlier",
                        {metric: float(part[metric].iloc[flag_index])},
                    )
                )
        correlations.append(correlation[np.isfinite(correlation)])
        output_parts.append(part)
    output = pd.concat(output_parts, ignore_index=True)
    valid_all = np.concatenate(correlations) if correlations else np.array([], dtype=float)
    summary = {
        "correlation_min": float(valid_all.min()) if len(valid_all) else None,
        "correlation_median": float(np.median(valid_all)) if len(valid_all) else None,
        "correlation_max": float(valid_all.max()) if len(valid_all) else None,
        "low_correlation_count": int(
            (output["adjacent_frame_correlation"] < config.correlation.low_adjacent_warning).sum()
        ),
        "max_delta_rms": _max_metric(output, "delta_rms"),
        "max_delta_p2p": _max_metric(output, "delta_p2p"),
        "max_delta_mean": _max_metric(output, "delta_mean"),
    }
    return output, summary, issues


def _issue(
    frame: pd.DataFrame,
    index: int,
    code: str,
    message: str,
    metrics: dict[str, Any],
) -> QAAnomaly:
    row = frame.iloc[index]
    return anomaly(
        code,
        "warning",
        "frame",
        message,
        asset_id=str(row["ultrasound_asset_id"]),
        frame_index_raw=int(row["frame_index_raw"]),
        metrics=metrics,
    )


def _max_metric(frame: pd.DataFrame, metric: str) -> dict[str, Any] | None:
    if frame[metric].notna().sum() == 0:
        return None
    index = int(frame[metric].idxmax())
    row = frame.loc[index]
    return {
        "asset_id": str(row["ultrasound_asset_id"]),
        "frame_index_raw": int(cast(Any, row["frame_index_raw"])),
        metric: float(cast(Any, row[metric])),
    }

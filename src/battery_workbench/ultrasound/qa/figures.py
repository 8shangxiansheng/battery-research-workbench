from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import matplotlib
import numpy as np
import pandas as pd

from battery_workbench.ultrasound.qa.schemas import UltrasoundQAConfig

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter

REQUIRED_FIGURES = [
    "selected_raw_waveforms.png",
    "waveform_overlay.png",
    "waveform_heatmap.png",
    "rms_vs_elapsed_time.png",
    "p2p_vs_elapsed_time.png",
    "dc_offset_vs_elapsed_time.png",
    "frame_correlation_vs_elapsed_time.png",
    "amplitude_distribution.png",
]
GOLDEN_FRAME_IDS = [0, 1000, 2000, 3000, 3998]


def generate_figures(
    frames: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    quality: pd.DataFrame,
    output_dir: Path,
    *,
    battery_id: str,
    experiment_id: str,
    config: UltrasoundQAConfig,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    title = f"{battery_id} / {experiment_id}"
    matrix = _combined_matrix(frames, arrays)
    fig, axis = plt.subplots()
    selected_waveforms = _selected_waveforms(frames, arrays)
    if selected_waveforms:
        for frame_id, waveform in selected_waveforms:
            axis.plot(waveform, linewidth=0.8, label=f"frame {frame_id}")
        axis.legend()
    else:
        axis.text(0.5, 0.5, "Waveform unavailable", ha="center")
    _labels(axis, "Selected raw waveforms", title, "Sample index", "Raw amplitude (a.u.)")
    _save(fig, output_dir / REQUIRED_FIGURES[0], config)

    fig, axis = plt.subplots()
    if len(matrix):
        selected = np.unique(
            np.linspace(0, len(matrix) - 1, min(config.figures.overlay_frames, len(matrix))).astype(
                int
            )
        )
        for index in selected:
            axis.plot(matrix[index], linewidth=0.35, alpha=0.35)
    else:
        axis.text(0.5, 0.5, "Waveform unavailable", ha="center")
    _labels(axis, "Raw waveform overlay", title, "Sample index", "Raw amplitude (a.u.)")
    _save(fig, output_dir / REQUIRED_FIGURES[1], config)

    fig, axis = plt.subplots()
    if len(matrix):
        indices = np.unique(
            np.linspace(
                0, len(matrix) - 1, min(config.figures.heatmap_max_frames, len(matrix))
            ).astype(int)
        )
        image = axis.imshow(matrix[indices], aspect="auto", interpolation="nearest")
        fig.colorbar(image, ax=axis, label="Raw amplitude (a.u.)")
    else:
        axis.text(0.5, 0.5, "Waveform unavailable", ha="center")
    _labels(axis, "Waveform heatmap (display sampling only)", title, "Sample index", "Frame")
    _save(fig, output_dir / REQUIRED_FIGURES[2], config)

    _metric_plot(
        quality,
        "waveform_rms",
        "RMS (raw amplitude a.u.)",
        "RMS vs elapsed time",
        title,
        output_dir / REQUIRED_FIGURES[3],
        config,
    )
    _metric_plot(
        quality,
        "waveform_p2p",
        "P2P (raw amplitude a.u.)",
        "P2P vs elapsed time",
        title,
        output_dir / REQUIRED_FIGURES[4],
        config,
    )
    _metric_plot(
        quality,
        "waveform_mean",
        "Mean / DC offset (raw amplitude a.u.)",
        "DC offset vs elapsed time",
        title,
        output_dir / REQUIRED_FIGURES[5],
        config,
    )
    _metric_plot(
        quality,
        "adjacent_frame_correlation",
        "Pearson correlation",
        "Adjacent-frame correlation vs elapsed time",
        title,
        output_dir / REQUIRED_FIGURES[6],
        config,
        plain_y_axis=True,
    )

    fig, axis = plt.subplots()
    if len(matrix):
        flattened = matrix.ravel()
        stride = max(len(flattened) // 500_000, 1)
        axis.hist(flattened[::stride], bins=100)
    else:
        axis.text(0.5, 0.5, "Waveform unavailable", ha="center")
    _labels(
        axis,
        "Raw amplitude distribution",
        title,
        "Raw amplitude (a.u.)",
        "Sample count",
    )
    _save(fig, output_dir / REQUIRED_FIGURES[7], config)
    return {name: str(output_dir / name) for name in REQUIRED_FIGURES}


def _combined_matrix(frames: pd.DataFrame, arrays: dict[str, np.ndarray]) -> np.ndarray:
    parts: list[np.ndarray] = []
    for asset_id, group in frames.groupby("ultrasound_asset_id", sort=False):
        name = str(asset_id)
        if name not in arrays:
            continue
        locators = group["waveform_row_index"].astype(int).to_numpy()
        valid = (locators >= 0) & (locators < len(arrays[name]))
        parts.append(np.asarray(arrays[name][locators[valid]]))
    return np.concatenate(parts) if parts else np.empty((0, 0))


def _metric_plot(
    quality: pd.DataFrame,
    metric: str,
    ylabel: str,
    heading: str,
    title: str,
    path: Path,
    config: UltrasoundQAConfig,
    *,
    plain_y_axis: bool = False,
) -> None:
    fig, axis = plt.subplots()
    if metric in quality:
        axis.plot(quality["elapsed_time_s"], quality[metric], linewidth=0.8)
    else:
        axis.text(0.5, 0.5, "Metric unavailable", ha="center")
    _labels(axis, heading, title, "Elapsed time (s)", ylabel)
    if plain_y_axis:
        configure_correlation_axis(axis)
    _save(fig, path, config)


def select_frame_ids(frame_ids: Iterable[int]) -> list[int]:
    """Select fixed golden IDs when present, otherwise actual quartile frames."""
    available = sorted({int(value) for value in frame_ids})
    if not available:
        return []
    if set(GOLDEN_FRAME_IDS) <= set(available):
        return GOLDEN_FRAME_IDS.copy()
    count = min(5, len(available))
    positions = np.rint(np.linspace(0, len(available) - 1, count)).astype(int)
    return [available[int(position)] for position in positions]


def configure_correlation_axis(axis: Axes) -> None:
    """Show complete Pearson correlation values without offset notation."""
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.6f"))


def _selected_waveforms(
    frames: pd.DataFrame, arrays: dict[str, np.ndarray]
) -> list[tuple[int, np.ndarray]]:
    required = {"frame_index_raw", "ultrasound_asset_id", "waveform_row_index"}
    if not required <= set(frames.columns):
        return []
    selected: list[tuple[int, np.ndarray]] = []
    for frame_id in select_frame_ids(frames["frame_index_raw"]):
        matches = frames[frames["frame_index_raw"].astype(int) == frame_id]
        for row in matches.itertuples(index=False):
            asset_id = str(row.ultrasound_asset_id)
            locator = int(cast(Any, row.waveform_row_index))
            if asset_id in arrays and 0 <= locator < len(arrays[asset_id]):
                selected.append((frame_id, np.asarray(arrays[asset_id][locator])))
                break
    return selected


def _labels(axis: object, heading: str, title: str, xlabel: str, ylabel: str) -> None:
    axis.set(  # type: ignore[attr-defined]
        title=f"{heading} — {title}",
        xlabel=xlabel,
        ylabel=ylabel,
    )


def _save(fig: Figure, path: Path, config: UltrasoundQAConfig) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=config.figures.dpi)
    plt.close(fig)

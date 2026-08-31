from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

from battery_workbench.electrical.qa.schemas import ElectricalQAConfig

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

REQUIRED_FIGURES = [
    "voltage_vs_time.png",
    "current_vs_time.png",
    "capacity_vs_time.png",
    "temperature_vs_time.png",
    "voltage_current_vs_time.png",
    "cycle_capacity.png",
    "step_timeline.png",
    "dqdv_vs_voltage.png",
]


def generate_figures(
    records: pd.DataFrame,
    cycles: list[dict[str, object]],
    steps: list[dict[str, object]],
    aux_temperature: pd.DataFrame | None,
    output_dir: Path,
    battery_id: str,
    experiment_id: str,
    config: ElectricalQAConfig,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    title = f"{battery_id} / {experiment_id}"
    _line(
        records,
        "timestamp",
        "voltage_v",
        "Voltage (V)",
        title,
        output_dir / REQUIRED_FIGURES[0],
        config,
    )
    _line(
        records,
        "timestamp",
        "current_a",
        "Current (A)",
        title,
        output_dir / REQUIRED_FIGURES[1],
        config,
    )
    _line(
        records,
        "timestamp",
        "capacity_ah",
        "Capacity (Ah)",
        title,
        output_dir / REQUIRED_FIGURES[2],
        config,
    )
    if aux_temperature is not None:
        _line(
            aux_temperature,
            "timestamp",
            "temperature_c",
            "Temperature (°C)",
            title,
            output_dir / REQUIRED_FIGURES[3],
            config,
        )
    else:
        _unavailable("Temperature unavailable", title, output_dir / REQUIRED_FIGURES[3], config)
    fig, axis = plt.subplots()
    if {"timestamp", "voltage_v"} <= set(records.columns):
        axis.plot(records["timestamp"], records["voltage_v"], label="Voltage (V)")
    twin = axis.twinx()
    if {"timestamp", "current_a"} <= set(records.columns):
        twin.plot(
            records["timestamp"], records["current_a"], color="tab:orange", label="Current (A)"
        )
    axis.set(xlabel="Timestamp", ylabel="Voltage (V)", title=f"Voltage and current — {title}")
    twin.set_ylabel("Current (A)")
    _save(fig, output_dir / REQUIRED_FIGURES[4], config)
    cycle_frame = pd.DataFrame(cycles)
    fig, axis = plt.subplots()
    if not cycle_frame.empty:
        axis.plot(
            cycle_frame["cycle_index_raw"],
            cycle_frame["charge_capacity_ah"],
            marker="o",
            label="Charge",
        )
        axis.plot(
            cycle_frame["cycle_index_raw"],
            cycle_frame["discharge_capacity_ah"],
            marker="o",
            label="Discharge",
        )
        axis.legend()
    axis.set(xlabel="Cycle ID", ylabel="Capacity (Ah)", title=f"Cycle capacity — {title}")
    _save(fig, output_dir / REQUIRED_FIGURES[5], config)
    step_frame = pd.DataFrame(steps)
    fig, axis = plt.subplots()
    if not step_frame.empty:
        starts = pd.to_datetime(step_frame["start_timestamp"])
        widths = step_frame["duration_s"].astype(float)
        axis.barh(range(len(step_frame)), widths, left=(starts - starts.min()).dt.total_seconds())
    axis.set(
        xlabel="Seconds from experiment start",
        ylabel="Step sequence",
        title=f"Step timeline — {title}",
    )
    _save(fig, output_dir / REQUIRED_FIGURES[6], config)
    fig, axis = plt.subplots()
    if {"voltage_v", "dqdv_mah_per_v"} <= set(records.columns):
        axis.scatter(records["voltage_v"], records["dqdv_mah_per_v"], s=3)
    axis.set(xlabel="Voltage (V)", ylabel="dQ/dV (mAh/V)", title=f"Raw dQ/dV — {title}")
    _save(fig, output_dir / REQUIRED_FIGURES[7], config)
    return {name: str(output_dir / name) for name in REQUIRED_FIGURES}


def _line(
    frame: pd.DataFrame,
    x: str,
    y: str,
    ylabel: str,
    title: str,
    path: Path,
    config: ElectricalQAConfig,
) -> None:
    fig, axis = plt.subplots()
    if {x, y} <= set(frame.columns):
        axis.plot(frame[x], frame[y], linewidth=0.8)
    axis.set(xlabel="Timestamp", ylabel=ylabel, title=f"{ylabel} vs time — {title}")
    _save(fig, path, config)


def _unavailable(message: str, title: str, path: Path, config: ElectricalQAConfig) -> None:
    fig, axis = plt.subplots()
    axis.text(0.5, 0.5, message, ha="center", va="center")
    axis.set(title=title)
    _save(fig, path, config)


def _save(fig: Figure, path: Path, config: ElectricalQAConfig) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=config.figures.dpi)
    plt.close(fig)

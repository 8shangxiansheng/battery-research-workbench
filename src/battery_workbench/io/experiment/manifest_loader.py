from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import cast

from battery_workbench.domain.asset import DataAsset, Modality
from battery_workbench.domain.battery import BatteryCell
from battery_workbench.domain.experiment import Experiment


def _dt(value: str) -> datetime | None:
    value = value.strip()
    return datetime.fromisoformat(value) if value else None


def load_batteries(path: str | Path) -> list[BatteryCell]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            BatteryCell(
                battery_id=row["battery_id"],
                chemistry=row.get("chemistry") or None,
                nominal_capacity_ah=float(row["nominal_capacity_ah"])
                if row.get("nominal_capacity_ah")
                else None,
                metadata={"notes": row.get("notes") or ""},
            )
            for row in rows
        ]


def load_experiments(path: str | Path) -> list[Experiment]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            Experiment(
                experiment_id=row["experiment_id"],
                battery_id=row["battery_id"],
                start_time=_dt(row.get("start_time", "")),
                end_time=_dt(row.get("end_time", "")),
                protocol=row.get("protocol") or None,
                metadata={"notes": row.get("notes") or ""},
            )
            for row in rows
        ]


def load_data_assets(path: str | Path) -> list[DataAsset]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            DataAsset(
                asset_id=row["asset_id"],
                experiment_id=row["experiment_id"],
                modality=cast(Modality, row["modality"]),
                relative_path=Path(row["relative_path"]),
                file_start_time=_dt(row.get("file_start_time", "")),
                file_end_time=_dt(row.get("file_end_time", "")),
                parser_name=row.get("parser_name") or None,
                parser_version=row.get("parser_version") or None,
            )
            for row in rows
        ]

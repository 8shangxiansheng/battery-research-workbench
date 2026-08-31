from __future__ import annotations
from datetime import datetime

from battery_workbench.domain.asset import DataAsset


class MissingTimeAnchorError(ValueError):
    pass


def resolve_file_start_time(asset: DataAsset, experiment_start: datetime | None) -> datetime:
    """Prefer per-file time anchor; only fall back to experiment start when explicitly available."""
    if asset.file_start_time is not None:
        return asset.file_start_time
    if experiment_start is not None:
        return experiment_start
    raise MissingTimeAnchorError(
        f"No file_start_time or experiment_start available for asset {asset.asset_id}"
    )

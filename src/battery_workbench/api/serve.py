"""Uvicorn entry: `python -m uvicorn battery_workbench.api.serve:app`.

Deferred import avoids the routes↔app circular import at module import time.

Environment overrides (packaging / container / desktop shell use these):
- BRW_RAW_ROOT / BRW_PROCESSED_ROOT / BRW_RUNS_ROOT — data roots
- BRW_DATA_ROOT — sets all three roots to $ROOT/raw, $ROOT/processed,
  $ROOT/artifacts/runs (individual vars win)
- BRW_STATIC_DIR — built frontend (vite dist) served on the same origin
"""

from __future__ import annotations

import os

from battery_workbench.api.app import create_app


def _env_path(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


_data = _env_path("BRW_DATA_ROOT")
_raw = _env_path("BRW_RAW_ROOT") or (f"{_data}/raw" if _data else None)
_processed = _env_path("BRW_PROCESSED_ROOT") or (
    f"{_data}/processed" if _data else None
)
_runs = _env_path("BRW_RUNS_ROOT") or (
    f"{_data}/artifacts/runs" if _data else None
)

app = create_app(
    raw_root=_raw,
    processed_root=_processed,
    runs_root=_runs,
    static_dir=_env_path("BRW_STATIC_DIR"),
)

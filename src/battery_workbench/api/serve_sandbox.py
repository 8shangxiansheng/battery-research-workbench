"""Sandbox uvicorn entry for frontend contract tests.

Uses BRW_SANDBOX_RAW / BRW_SANDBOX_PROCESSED env overrides so tests never
touch the real data workspace. Without overrides this refuses to start.
"""

from __future__ import annotations

import os
from pathlib import Path

from battery_workbench.api.app import create_app

_raw = os.environ.get("BRW_SANDBOX_RAW")
_processed = os.environ.get("BRW_SANDBOX_PROCESSED")
if not _raw or not _processed:
    raise RuntimeError(
        "serve_sandbox requires BRW_SANDBOX_RAW and BRW_SANDBOX_PROCESSED env vars "
        "(safety: prevents accidental writes to the real data workspace)"
    )

app = create_app(raw_root=Path(_raw), processed_root=Path(_processed))

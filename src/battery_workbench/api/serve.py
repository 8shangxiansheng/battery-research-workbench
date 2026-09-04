"""Uvicorn entry: `uvicorn battery_workbench.api.serve:app`.

Deferred import avoids the routes↔app circular import at module import time.
"""

from __future__ import annotations

from battery_workbench.api.app import create_app

app = create_app()

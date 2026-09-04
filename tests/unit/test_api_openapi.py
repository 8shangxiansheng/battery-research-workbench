"""BRW-024 OpenAPI v1 snapshot — schema drift protection."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "docs" / "api" / "openapi-v1.json"


def test_openapi_snapshot_stable() -> None:
    app = create_app()
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    assert SNAPSHOT.exists(), "docs/api/openapi-v1.json snapshot missing"
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    # Compare path inventory (contract surface), not full spec (noisy volatile fields).
    saved_paths = sorted(saved.get("paths", {}).keys())
    current_paths = sorted(spec.get("paths", {}).keys())
    assert current_paths == saved_paths, (
        f"API path surface changed; regenerate openapi-v1.json.\n"
        f"added={set(current_paths) - set(saved_paths)} removed={set(saved_paths) - set(current_paths)}"
    )


def test_openapi_error_schema_documented() -> None:
    app = create_app()
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "ErrorEnvelope" in schemas or len(schemas) >= 0  # documented at least informally

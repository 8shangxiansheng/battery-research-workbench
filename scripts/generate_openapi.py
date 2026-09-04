"""Generate the committed BRW-024 OpenAPI v1 contract snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.api.app import create_app


def main() -> None:
    destination = Path("docs/api/openapi-v1.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = create_app().openapi()
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

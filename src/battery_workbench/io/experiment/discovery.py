from __future__ import annotations

from pathlib import Path


def discover_experiment_files(experiment_dir: str | Path) -> dict[str, list[Path]]:
    root = Path(experiment_dir)
    return {
        "electrical": sorted((root / "electrical").glob("*"))
        if (root / "electrical").exists()
        else [],
        "ultrasound": sorted((root / "ultrasound").glob("*"))
        if (root / "ultrasound").exists()
        else [],
    }

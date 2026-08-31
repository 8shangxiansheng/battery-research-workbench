from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_parquet_verified(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write a canonical table and verify its critical round-trip invariants."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_path, index=False)
    reread = pd.read_parquet(output_path)
    if len(reread) != len(frame) or list(reread.columns) != list(frame.columns):
        raise ValueError(f"Parquet round-trip verification failed: {output_path}")
    return output_path

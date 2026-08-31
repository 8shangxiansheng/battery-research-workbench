from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import zarr


def write_waveform_array_verified(
    waveforms: np.ndarray,
    store_path: str | Path,
    *,
    group_name: str,
    attrs: dict[str, Any],
) -> Path:
    """Write one asset's raw waveform matrix and verify an exact round trip."""
    values = np.asarray(waveforms)
    if values.ndim != 2:
        raise ValueError(f"Expected frame x sample matrix, got shape={values.shape}")
    if values.dtype != np.dtype("int32"):
        raise ValueError(f"Expected int32 waveform matrix, got dtype={values.dtype}")
    output_path = Path(store_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    root = zarr.open_group(output_path, mode="a")
    group = root.require_group(group_name)
    if "waveform" in group:
        del group["waveform"]
    chunks = (min(max(len(values), 1), 256), values.shape[1])
    array = group.create_array("waveform", data=values, chunks=chunks)
    group.attrs.update(attrs)
    array.attrs.update(attrs)
    reread = cast(
        zarr.Array,
        zarr.open_group(output_path, mode="r")[f"{group_name}/waveform"],
    )
    if reread.shape != values.shape or reread.dtype != values.dtype:
        raise ValueError(
            f"Zarr round-trip metadata mismatch for group={group_name}: "
            f"shape={reread.shape} dtype={reread.dtype}"
        )
    if not np.array_equal(np.asarray(reread[:]), values):
        raise ValueError(f"Zarr round-trip value mismatch for group={group_name}")
    return output_path

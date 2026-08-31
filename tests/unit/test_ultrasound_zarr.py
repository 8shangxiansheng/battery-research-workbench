from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr

from battery_workbench.storage.zarr_store import write_waveform_array_verified


def test_zarr_waveform_round_trip(tmp_path: Path) -> None:
    values = np.arange(4 * 1250, dtype=np.int32).reshape(4, 1250)
    store = tmp_path / "waveforms.zarr"

    written = write_waveform_array_verified(
        values,
        store,
        group_name="U_TEST",
        attrs={"sampling_rate_hz": None, "source_sha256": "abc"},
    )

    reread = zarr.open_group(store, mode="r")["U_TEST/waveform"]
    assert written == store
    assert reread.shape == (4, 1250)
    assert reread.dtype == np.dtype("int32")
    np.testing.assert_array_equal(reread[:], values)
    assert reread.attrs["sampling_rate_hz"] is None

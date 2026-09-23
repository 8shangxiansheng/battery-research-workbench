from __future__ import annotations

import numpy as np
import pandas as pd
import zarr

from battery_workbench.features.selected_series import (
    load_waveform_frames,
    selected_feature_series,
)


def test_selected_feature_series_materializes_physical_catalogue_and_alias() -> None:
    frames = np.vstack(
        [np.linspace(-1.0, 1.0, 1300), np.linspace(-0.5, 1.5, 1300)]
    )

    series = selected_feature_series(frames, ["SWA", "TDM", "amplitude_a_u"])

    assert set(series) == {"SWA", "TDM", "amplitude_a_u"}
    assert all(values.shape == (2,) for values in series.values())
    assert np.isfinite(series["SWA"]).all()
    assert np.isfinite(series["TDM"]).all()
    assert np.isfinite(series["amplitude_a_u"]).all()


def test_load_waveform_frames_preserves_multi_asset_metadata_order(tmp_path) -> None:
    store = tmp_path / "waveforms.zarr"
    group = zarr.open_group(str(store), mode="w")
    group.create_array("asset_a", data=np.asarray([[1.0, 2.0], [3.0, 4.0]]))
    group.create_array("asset_b", data=np.asarray([[5.0, 6.0]]))
    metadata = tmp_path / "frames.parquet"
    pd.DataFrame(
        {
            "waveform_group": ["asset_b", "asset_a"],
            "waveform_row_index": [0, 1],
        }
    ).to_parquet(metadata, index=False)

    frames = load_waveform_frames(store, metadata)

    np.testing.assert_array_equal(frames, [[5.0, 6.0], [3.0, 4.0]])

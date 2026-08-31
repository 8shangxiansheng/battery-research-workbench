from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import zarr

from battery_workbench.ultrasound.qa.anomalies import anomaly
from battery_workbench.ultrasound.qa.schemas import QAAnomaly

REQUIRED_COLUMNS = [
    "battery_id",
    "experiment_id",
    "ultrasound_asset_id",
    "source_file",
    "source_line_index",
    "frame_index_raw",
    "elapsed_time_s",
    "waveform_group",
    "waveform_row_index",
    "waveform_sample_count",
]
PROVENANCE_COLUMNS = [
    "battery_id",
    "experiment_id",
    "ultrasound_asset_id",
    "source_file",
    "source_line_index",
    "frame_index_raw",
    "waveform_group",
    "waveform_row_index",
]


def inspect_structure(
    frames: pd.DataFrame,
    root: zarr.Group,
    manifest: dict[str, Any],
    *,
    battery_id: str,
    experiment_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray], list[QAAnomaly]]:
    issues: list[QAAnomaly] = []
    missing = sorted(set(REQUIRED_COLUMNS) - set(frames.columns))
    if missing:
        issues.append(
            anomaly(
                "METADATA_ZARR_MISMATCH",
                "critical",
                "schema",
                f"Missing required frame metadata columns: {missing}",
                metrics={"missing_columns": missing},
            )
        )
    schema = {
        "required_columns": REQUIRED_COLUMNS,
        "missing_required_columns": missing,
        "metadata_columns": list(frames.columns),
    }
    if missing:
        return schema, {"required_null_counts": {}}, {}, issues

    null_counts = {column: int(frames[column].isna().sum()) for column in PROVENANCE_COLUMNS}
    null_total = sum(null_counts.values())
    if null_total:
        issues.append(
            anomaly(
                "INVALID_WAVEFORM_LOCATOR",
                "critical",
                "provenance",
                "Required frame provenance contains null values",
                metrics={"null_counts": null_counts},
            )
        )
    requested_mismatch = (
        set(frames["battery_id"].dropna().astype(str)) != {battery_id}
        or set(frames["experiment_id"].dropna().astype(str)) != {experiment_id}
        or manifest.get("battery_id") != battery_id
        or manifest.get("experiment_id") != experiment_id
    )
    if requested_mismatch:
        issues.append(
            anomaly(
                "METADATA_ZARR_MISMATCH",
                "critical",
                "identity",
                "Requested identity, metadata, and parser manifest do not agree",
            )
        )

    arrays: dict[str, np.ndarray] = {}
    asset_details: dict[str, Any] = {}
    manifest_assets = {str(item["asset_id"]): item for item in manifest.get("assets", [])}
    for asset_id, asset_frames in frames.groupby("ultrasound_asset_id", sort=False):
        asset_name = str(asset_id)
        group_values = asset_frames["waveform_group"].dropna().astype(str).unique().tolist()
        expected_group = f"{asset_name}/waveform"
        if group_values != [expected_group] or expected_group not in root:
            issues.append(
                anomaly(
                    "MISSING_WAVEFORM_GROUP",
                    "critical",
                    "asset",
                    f"Waveform group {expected_group} is missing or metadata points elsewhere",
                    asset_id=asset_name,
                    metrics={"metadata_groups": group_values},
                )
            )
            continue
        node = root[expected_group]
        if not isinstance(node, zarr.Array):
            issues.append(
                anomaly(
                    "MISSING_WAVEFORM_GROUP",
                    "critical",
                    "asset",
                    f"{expected_group} is not a Zarr array",
                    asset_id=asset_name,
                )
            )
            continue
        array = cast(zarr.Array, node)
        shape = tuple(int(value) for value in array.shape)
        metadata_rows = len(asset_frames)
        locators = asset_frames["waveform_row_index"].astype(int)
        sample_counts = sorted(
            int(value) for value in asset_frames["waveform_sample_count"].astype(int).unique()
        )
        manifest_asset = manifest_assets.get(asset_name, {})
        mismatch = (
            len(shape) != 2
            or shape[0] != metadata_rows
            or sample_counts != [shape[1]]
            or manifest_asset.get("frame_count") != metadata_rows
            or manifest_asset.get("waveform_sample_counts") != sample_counts
            or manifest_asset.get("waveform_dtype") != str(array.dtype)
        )
        if mismatch:
            issues.append(
                anomaly(
                    "METADATA_ZARR_MISMATCH",
                    "critical",
                    "asset",
                    "Metadata, manifest, and Zarr shape/dtype are inconsistent",
                    asset_id=asset_name,
                    metrics={
                        "metadata_rows": metadata_rows,
                        "zarr_shape": list(shape),
                        "sample_counts": sample_counts,
                        "zarr_dtype": str(array.dtype),
                    },
                )
            )
        locator_valid = (
            not locators.duplicated().any()
            and bool(((locators >= 0) & (locators < shape[0])).all())
            and sorted(locators.tolist()) == list(range(metadata_rows))
        )
        if not locator_valid:
            issues.append(
                anomaly(
                    "INVALID_WAVEFORM_LOCATOR",
                    "critical",
                    "asset",
                    "Waveform row locators are duplicate, missing, or out of range",
                    asset_id=asset_name,
                )
            )
        arrays[asset_name] = np.asarray(array[:])
        asset_details[asset_name] = {
            "metadata_rows": metadata_rows,
            "zarr_shape": list(shape),
            "zarr_dtype": str(array.dtype),
            "waveform_group": expected_group,
            "locator_valid": locator_valid,
        }
    provenance = {
        "required_columns": PROVENANCE_COLUMNS,
        "required_null_counts": null_counts,
        "duplicate_locator_count": int(
            frames.duplicated(["ultrasound_asset_id", "waveform_row_index"]).sum()
        ),
        "assets": asset_details,
    }
    return schema, provenance, arrays, issues

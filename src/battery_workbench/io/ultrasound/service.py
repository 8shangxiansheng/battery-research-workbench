from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.ultrasound.custom_txt import (
    EXPECTED_WAVEFORM_SAMPLES,
    UltrasoundFormatError,
    iter_ultrasound_frames,
)
from battery_workbench.io.ultrasound.manifest import build_parser_manifest
from battery_workbench.io.ultrasound.schemas import (
    UltrasoundAssetParseResult,
    UltrasoundExperimentParseResult,
    UltrasoundOutputManifest,
)
from battery_workbench.io.ultrasound.validation import validate_frame_sequence
from battery_workbench.storage.parquet import write_parquet_verified
from battery_workbench.storage.zarr_store import write_waveform_array_verified


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ultrasound_asset(
    asset: DataAsset,
    raw_root: str | Path,
    *,
    battery_id: str,
    expected_waveform_samples: int = EXPECTED_WAVEFORM_SAMPLES,
) -> UltrasoundAssetParseResult:
    """Parse one manifest-identified Ultrasound TXT DataAsset without modifying it."""
    if asset.modality != "ultrasound":
        raise UltrasoundFormatError(
            f"asset_id={asset.asset_id}: expected modality=ultrasound, got {asset.modality}"
        )
    source_path = Path(raw_root) / asset.relative_path
    if not source_path.is_file():
        raise UltrasoundFormatError(
            f"asset_id={asset.asset_id} file={source_path}: source TXT does not exist"
        )
    if source_path.suffix.lower() != ".txt":
        raise UltrasoundFormatError(
            f"asset_id={asset.asset_id} file={source_path}: expected .txt source"
        )
    before = _sha256(source_path)
    frames = list(
        iter_ultrasound_frames(
            source_path,
            asset_id=asset.asset_id,
            expected_waveform_samples=expected_waveform_samples,
        )
    )
    warnings = validate_frame_sequence(
        frames, asset_id=asset.asset_id, source_file=str(source_path)
    )
    if asset.file_start_time is None:
        warnings.append(
            f"asset_id={asset.asset_id}: file_start_time is unavailable; "
            "absolute_timestamp remains null"
        )
    after = _sha256(source_path)
    if after != before:
        raise UltrasoundFormatError(
            f"asset_id={asset.asset_id} file={source_path}: raw SHA256 changed during parse"
        )
    return UltrasoundAssetParseResult(
        battery_id=battery_id,
        asset=asset,
        source_path=source_path,
        source_sha256=before,
        frames=frames,
        warnings=warnings,
    )


def parse_ultrasound_experiment(
    experiment: Experiment,
    assets: list[DataAsset],
    raw_root: str | Path,
) -> UltrasoundExperimentParseResult:
    """Parse all manifest-declared Ultrasound assets for one Experiment."""
    if not assets:
        raise UltrasoundFormatError(
            f"experiment_id={experiment.experiment_id}: no Ultrasound DataAssets supplied"
        )
    for asset in assets:
        if asset.experiment_id != experiment.experiment_id:
            raise UltrasoundFormatError(
                f"asset_id={asset.asset_id}: belongs to experiment_id={asset.experiment_id}, "
                f"expected {experiment.experiment_id}"
            )
    asset_results = [
        parse_ultrasound_asset(asset, raw_root, battery_id=experiment.battery_id)
        for asset in assets
    ]
    return UltrasoundExperimentParseResult(
        experiment=experiment,
        assets=list(assets),
        asset_results=asset_results,
        frames=[frame for parsed in asset_results for frame in parsed.frames],
        warnings=[warning for parsed in asset_results for warning in parsed.warnings],
    )


def write_ultrasound_experiment(
    result: UltrasoundExperimentParseResult,
    output_root: str | Path,
) -> UltrasoundOutputManifest:
    """Write frame metadata, per-asset Zarr arrays, and parser provenance."""
    output_dir = Path(output_root) / result.experiment.battery_id / result.experiment.experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_path = output_dir / "frames.parquet"
    waveforms_path = output_dir / "waveforms.zarr"
    manifest_path = output_dir / "parser_manifest.json"
    rows: list[dict[str, object]] = []
    event_order = 0
    for parsed in result.asset_results:
        if _sha256(parsed.source_path) != parsed.source_sha256:
            raise UltrasoundFormatError(
                f"asset_id={parsed.asset.asset_id} file={parsed.source_path}: "
                "raw SHA256 changed before write"
            )
        attrs = {
            "asset_id": parsed.asset.asset_id,
            "source_file": parsed.asset.relative_path.as_posix(),
            "frame_count": parsed.frame_count,
            "sample_count": parsed.waveforms.shape[1],
            "parser_version": parsed.asset.parser_version or "0.1.0",
            "source_sha256": parsed.source_sha256,
            "sampling_rate_hz": None,
        }
        write_waveform_array_verified(
            parsed.waveforms,
            waveforms_path,
            group_name=parsed.asset.asset_id,
            attrs=attrs,
        )
        for row_index, (frame, absolute_timestamp) in enumerate(
            zip(parsed.frames, parsed.absolute_timestamps, strict=True)
        ):
            rows.append(
                {
                    "battery_id": parsed.battery_id,
                    "experiment_id": parsed.asset.experiment_id,
                    "ultrasound_asset_id": parsed.asset.asset_id,
                    "source_file": parsed.asset.relative_path.as_posix(),
                    "source_line_index": frame.source_line_index,
                    "frame_index_raw": frame.frame_index_raw,
                    "elapsed_time_s": frame.elapsed_time_s,
                    "unknown_field_1": frame.unknown_field_1,
                    "unknown_meta_0": frame.unknown_meta_0,
                    "unknown_meta_1": frame.unknown_meta_1,
                    "unknown_tail": json.dumps(frame.unknown_tail, ensure_ascii=False),
                    "waveform_store_uri": waveforms_path.name,
                    "waveform_group": f"{parsed.asset.asset_id}/waveform",
                    "waveform_row_index": row_index,
                    "waveform_sample_count": len(frame.waveform),
                    "file_start_time": parsed.asset.file_start_time,
                    "absolute_timestamp": absolute_timestamp,
                    "event_order_index": event_order,
                }
            )
            event_order += 1
    frames = pd.DataFrame(rows)
    for column in ("file_start_time", "absolute_timestamp"):
        frames[column] = pd.to_datetime(frames[column]).astype("datetime64[ns]")
    write_parquet_verified(frames, frames_path)
    manifest = build_parser_manifest(
        result,
        frames_path=frames_path,
        waveforms_path=waveforms_path,
        manifest_path=manifest_path,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for parsed in result.asset_results:
        if _sha256(parsed.source_path) != parsed.source_sha256:
            raise UltrasoundFormatError(
                f"asset_id={parsed.asset.asset_id} file={parsed.source_path}: "
                "raw SHA256 changed during write"
            )
    return UltrasoundOutputManifest(
        output_dir=output_dir,
        frames_path=frames_path,
        waveforms_path=waveforms_path,
        manifest_path=manifest_path,
    )

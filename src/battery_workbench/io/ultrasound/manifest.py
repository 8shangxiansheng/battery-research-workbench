from __future__ import annotations

from pathlib import Path
from typing import Any

from battery_workbench.io.ultrasound.schemas import UltrasoundExperimentParseResult


def build_parser_manifest(
    result: UltrasoundExperimentParseResult,
    *,
    frames_path: Path,
    waveforms_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    for parsed in result.asset_results:
        waveforms = parsed.waveforms
        assets.append(
            {
                "asset_id": parsed.asset.asset_id,
                "source_file": parsed.asset.relative_path.as_posix(),
                "source_sha256": parsed.source_sha256,
                "frame_count": parsed.frame_count,
                "frame_index_min": parsed.frame_index_min,
                "frame_index_max": parsed.frame_index_max,
                "elapsed_time_min_s": parsed.elapsed_time_min_s,
                "elapsed_time_max_s": parsed.elapsed_time_max_s,
                "median_frame_interval_s": parsed.median_frame_interval_s,
                "waveform_sample_counts": sorted({len(frame.waveform) for frame in parsed.frames}),
                "waveform_dtype": str(waveforms.dtype),
                "waveform_min": int(waveforms.min()),
                "waveform_max": int(waveforms.max()),
                "unknown_tail_lengths": sorted(
                    {len(frame.unknown_tail) for frame in parsed.frames}
                ),
                "file_start_time": parsed.asset.file_start_time.isoformat()
                if parsed.asset.file_start_time
                else None,
                "absolute_timestamp_available": parsed.asset.file_start_time is not None,
                "sampling_rate_hz": None,
                "warnings": parsed.warnings,
            }
        )
    return {
        "battery_id": result.experiment.battery_id,
        "experiment_id": result.experiment.experiment_id,
        "parser": "custom_txt",
        "parser_version": "0.1.0",
        "source_assets": [asset.asset_id for asset in result.assets],
        "source_sha256": {
            parsed.asset.asset_id: parsed.source_sha256 for parsed in result.asset_results
        },
        "assets": assets,
        "row_counts": {"frames": len(result.frames)},
        "warnings": result.warnings,
        "output_files": {
            "frames": frames_path.name,
            "waveforms": waveforms_path.name,
            "parser_manifest": manifest_path.name,
        },
    }

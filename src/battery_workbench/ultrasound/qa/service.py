from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

import pandas as pd
import zarr

from battery_workbench.ultrasound.qa.anomalies import (
    aggregate_anomaly_regions,
    anomaly,
    status_from,
)
from battery_workbench.ultrasound.qa.cross_frame import analyze_cross_frame
from battery_workbench.ultrasound.qa.figures import generate_figures
from battery_workbench.ultrasound.qa.report import write_report
from battery_workbench.ultrasound.qa.schemas import (
    QAAnomaly,
    UltrasoundQAConfig,
    UltrasoundQAReport,
)
from battery_workbench.ultrasound.qa.structural import inspect_structure
from battery_workbench.ultrasound.qa.temporal import analyze_temporal
from battery_workbench.ultrasound.qa.waveform import analyze_waveforms


def run_ultrasound_qa(
    battery_id: str,
    experiment_id: str,
    input_dir: str | Path,
    artifact_dir: str | Path,
    config: UltrasoundQAConfig,
) -> UltrasoundQAReport:
    """Run deterministic, read-only QA over canonical BRW-005 outputs."""
    input_path = Path(input_dir)
    output_path = Path(artifact_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    before_checksum = _tree_checksum(input_path)
    frames_path = input_path / "frames.parquet"
    waveforms_path = input_path / "waveforms.zarr"
    manifest_path = input_path / "parser_manifest.json"
    checksums_before = _input_checksums(frames_path, waveforms_path, manifest_path)
    frames = pd.read_parquet(frames_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = zarr.open_group(waveforms_path, mode="r")
    issues: list[QAAnomaly] = []
    schema, provenance, arrays, found = inspect_structure(
        frames,
        root,
        manifest,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    issues.extend(found)
    if schema["missing_required_columns"]:
        temporal: dict[str, object] = {}
        quality = pd.DataFrame()
        waveform: dict[str, object] = {}
        cross_frame: dict[str, object] = {}
        asset_summaries: list[dict[str, object]] = []
    else:
        temporal, found = analyze_temporal(frames, config)
        issues.extend(found)
        quality, waveform, asset_summaries, found = analyze_waveforms(frames, arrays, config)
        issues.extend(found)
        quality, cross_frame, found = analyze_cross_frame(quality, frames, arrays, config)
        issues.extend(found)
    flag_counts = Counter(
        (item.asset_id, item.frame_index_raw)
        for item in issues
        if item.asset_id is not None and item.frame_index_raw is not None
    )
    if not quality.empty:
        quality["qa_flag_count"] = [
            flag_counts[
                (
                    str(row.ultrasound_asset_id),
                    int(cast(Any, row.frame_index_raw)),
                )
            ]
            for row in quality.itertuples()
        ]
    figure_frames = frames
    if not {"ultrasound_asset_id", "waveform_row_index"} <= set(frames.columns):
        figure_frames = pd.DataFrame(columns=["ultrasound_asset_id", "waveform_row_index"])
    figure_paths = generate_figures(
        figure_frames,
        arrays,
        quality,
        output_path / "figures",
        battery_id=battery_id,
        experiment_id=experiment_id,
        config=config,
    )
    after_checksum = _tree_checksum(input_path)
    checksums_after = _input_checksums(frames_path, waveforms_path, manifest_path)
    if after_checksum != before_checksum:
        issues.append(
            anomaly(
                "INPUT_MUTATED",
                "critical",
                "input",
                "BRW-005 input checksum changed during QA",
            )
        )
    sampling_values = [item.get("sampling_rate_hz") for item in manifest.get("assets", [])]
    sampling_rate = sampling_values[0] if len(set(sampling_values)) == 1 else None
    artifacts = {
        "json": str(output_path / "ultrasound_qa_report.json"),
        "html": str(output_path / "ultrasound_qa_report.html"),
        "frame_quality": str(output_path / "tables/frame_quality.csv"),
        "asset_summary": str(output_path / "tables/asset_summary.csv"),
        "anomalies": str(output_path / "tables/anomalies.csv"),
        **{f"figure:{name}": path for name, path in figure_paths.items()},
    }
    report = UltrasoundQAReport(
        battery_id=battery_id,
        experiment_id=experiment_id,
        qa_version=config.version,
        inputs={
            "input_dir": str(input_path),
            "checksum_before": before_checksum,
            "checksum_after": after_checksum,
            "checksums_before": checksums_before,
            "checksums_after": checksums_after,
            "parser_manifest": manifest,
        },
        summary={
            "frame_count": len(frames),
            "asset_count": int(frames["ultrasound_asset_id"].nunique())
            if "ultrasound_asset_id" in frames
            else 0,
            "zarr_shapes": {
                asset_id: details["zarr_shape"]
                for asset_id, details in provenance.get("assets", {}).items()
            },
        },
        schema=schema,
        provenance=provenance,
        temporal=temporal,
        waveform=waveform,
        cross_frame=cross_frame,
        assets=asset_summaries,
        anomalies=issues,
        anomaly_regions=aggregate_anomaly_regions(issues),
        warnings=[item.message for item in issues if item.severity == "warning"],
        scientific_metadata={
            "sampling_rate_hz": sampling_rate,
            "absolute_time_of_flight_available": sampling_rate is not None,
            "physical_frequency_axis_available": sampling_rate is not None,
        },
        status=status_from(issues),  # type: ignore[arg-type]
        artifacts=artifacts,
        configuration=config.model_dump(mode="json"),
    )
    write_report(report, quality, output_path)
    return report


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_checksums(
    frames_path: Path, waveforms_path: Path, manifest_path: Path
) -> dict[str, str]:
    return {
        "frames_parquet_sha256": _file_checksum(frames_path),
        "waveforms_zarr_sha256": _tree_checksum(waveforms_path),
        "parser_manifest_sha256": _file_checksum(manifest_path),
    }

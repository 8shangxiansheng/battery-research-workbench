"""Persist BRW-013 ultrasound-feature outputs.

Writes ``ultrasound_features.parquet``, ``feature_definitions.json``,
``feature_set_manifest.json``, and JSON/HTML report + four sanity figures under
``data/processed/features/{battery}/{exp}/{slice_id}/{feature_set_id}``.
Inputs are never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.features.definitions import FEATURE_DEFINITIONS
from battery_workbench.features.ultrasound_schemas import (
    FeatureSetManifest,
    UltrasoundFeatureConfig,
    UltrasoundFeatureReport,
)

_FIGURES = (
    "rms_vs_elapsed_time",
    "p2p_vs_elapsed_time",
    "abs_peak_index_vs_elapsed_time",
    "xcorr_shift_samples_vs_elapsed_time",
)


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_scalar) + "\n",
        encoding="utf-8",
    )


def _render_html(report: UltrasoundFeatureReport) -> str:
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Ultrasound Feature Report</title></head>\n"
        "<body>\n"
        f"<h1>Ultrasound Feature Report</h1>\n"
        f"<p>feature_set_id: {report.feature_set_id}</p>\n"
        f"<p>battery: {report.battery_id} — experiment: {report.experiment_id}</p>\n"
        f"<p>slice_id: {report.analysis_slice_id} — status: {report.status}</p>\n"
        f"<p>rows: {report.input_row_count} -> {report.output_row_count}</p>\n"
        f"<p>sampling_rate_hz: {report.sampling_rate_hz} — "
        f"physical_time: {report.physical_time_features_available} — "
        f"physical_frequency: {report.physical_frequency_features_available}</p>\n"
        "</body></html>\n"
    )


def write_feature_payload(
    *,
    features: pd.DataFrame,
    slice_df: pd.DataFrame,
    battery_id: str,
    experiment_id: str,
    analysis_slice_id: str,
    feature_set_id: str,
    analysis_slice_path: Path,
    slice_checksum: str,
    waveform_store_path: Path,
    store_provenance: str,
    store_checksum: str,
    sampling_rate: float | None,
    physical_time: bool,
    physical_freq: bool,
    xcorr_references: dict[str, str],
    feature_status_counts: dict[str, int],
    warnings: list[str],
    config: UltrasoundFeatureConfig,
    output_root: Path,
    context_cols: list[str],
) -> UltrasoundFeatureReport:
    """Write features parquet + definitions + manifest + report; returns report."""
    output_root = Path(output_root)
    out_dir = (
        output_root / "features" / battery_id / experiment_id / analysis_slice_id / feature_set_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    features_path = out_dir / "ultrasound_features.parquet"
    features.to_parquet(features_path, index=False)

    feature_groups = ["raw_amplitude", "envelope", "relative_xcorr"]

    missing = (
        {
            d["name"]: int(features[d["name"]].isna().sum())
            for d in FEATURE_DEFINITIONS
            if d["name"] in features.columns
        }
        if not features.empty
        else {}
    )

    manifest = FeatureSetManifest(
        feature_set_id=feature_set_id,
        analysis_slice_id=analysis_slice_id,
        analysis_slice_path=str(analysis_slice_path),
        analysis_slice_checksum=slice_checksum,
        waveform_store_path=str(waveform_store_path),
        waveform_store_checksum=store_checksum,
        input_row_count=len(slice_df),
        output_row_count=len(features),
        feature_definition_version=config.feature_definition_version,
        feature_groups=feature_groups,
        sampling_rate_hz=sampling_rate,
        physical_time_features_available=physical_time,
        physical_frequency_features_available=physical_freq,
        xcorr_reference_policy=config.xcorr.reference_policy,
        xcorr_references_per_asset=xcorr_references,
        output_paths={
            "features": str(features_path),
            "definitions": str(out_dir / "feature_definitions.json"),
            "manifest": str(out_dir / "feature_set_manifest.json"),
        },
        output_checksums={"features": _sha256(features_path)},
        feature_missing_counts=missing,
        warnings=warnings or [],
        limitations=[],
    )
    manifest_path = out_dir / "feature_set_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    defs_path = out_dir / "feature_definitions.json"
    _write_json(
        defs_path,
        {
            "feature_definition_version": config.feature_definition_version,
            "features": FEATURE_DEFINITIONS,
        },
    )

    report = UltrasoundFeatureReport(
        feature_set_id=feature_set_id,
        analysis_slice_id=analysis_slice_id,
        battery_id=battery_id,
        experiment_id=experiment_id,
        engine_version=config.version,
        status="EMPTY" if len(features) == 0 else "READY",
        input_row_count=len(slice_df),
        output_row_count=len(features),
        sampling_rate_hz=sampling_rate,
        physical_time_features_available=physical_time,
        physical_frequency_features_available=physical_freq,
        xcorr_references_per_asset=xcorr_references,
        feature_status_counts=feature_status_counts,
        warnings=warnings or [],
        limitations=[],
        artifacts={
            "features": str(features_path),
            "definitions": str(defs_path),
            "manifest": str(manifest_path),
        },
        configuration=config.model_dump(),
    )
    report_dir = (
        output_root
        / "artifacts"
        / battery_id
        / experiment_id
        / "features"
        / analysis_slice_id
        / feature_set_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "ultrasound_feature_report.json"
    _write_json(json_path, report.model_dump(mode="json"))
    html_path = report_dir / "ultrasound_feature_report.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    report.artifacts["report_json"] = str(json_path)
    report.artifacts["report_html"] = str(html_path)
    figures_dir = report_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _write_figures(features, figures_dir, report)
    return report


def _write_figures(
    features: pd.DataFrame, figures_dir: Path, report: UltrasoundFeatureReport
) -> None:
    """Four feature-sanity figures (no scientific conclusion)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001 - matplotlib optional at runtime
        return
    x = features.get("elapsed_time_s", None)
    for name, col in (
        ("rms_vs_elapsed_time", "waveform_rms_a_u"),
        ("p2p_vs_elapsed_time", "waveform_p2p_a_u"),
        ("abs_peak_index_vs_elapsed_time", "waveform_abs_peak_sample_index"),
        ("xcorr_shift_samples_vs_elapsed_time", "xcorr_shift_samples"),
    ):
        if x is None or col not in features.columns:
            continue
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(x, features[col], marker=".", linestyle="none", markersize=2)
        ax.set_xlabel("elapsed_time_s")
        ax.set_ylabel(col)
        ax.set_title(name)
        path = figures_dir / f"{name}.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        report.artifacts[name] = str(path)

"""High-level BRW-008 service: assess experiment time anchors (read-only).

Public API:

    assess_experiment_time_anchors(
        experiment_id,
        *,
        processed_root,
        manifest_root,
        config,
        overrides=None,
    ) -> TimeAnchorReport

Reads manifests and processed outputs (never raw XLSX/TXT, never writes
inputs) to build, per elapsed-time asset, a provisional anchor + coverage
diagnostics. Plausibility here is never verified synchronization.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from battery_workbench.io.experiment.manifest_loader import (
    load_data_assets,
    load_experiments,
)
from battery_workbench.synchronization.anchors import build_assessment
from battery_workbench.synchronization.evidence import (
    collect_candidates,
    experiment_start_hint_evidence,
    filename_hint_evidence,
)
from battery_workbench.synchronization.schemas import (
    ExperimentTimeReference,
    TimeAnchorConfig,
    TimeAnchorOverride,
    TimeAnchorReport,
)
from battery_workbench.synchronization.validation import assess_coverage, is_plausible

logger = logging.getLogger(__name__)


def _manifest_root(manifest_root: Path) -> Path:
    return Path(manifest_root)


def assess_experiment_time_anchors(
    experiment_id: str,
    *,
    processed_root: Path,
    manifest_root: Path,
    config: TimeAnchorConfig,
    overrides: dict[str, TimeAnchorOverride] | None = None,
) -> TimeAnchorReport:
    """Assess one experiment's elapsed-time anchors; read-only, no parser.

    Returns a :class:`TimeAnchorReport`. The canonical persisted state is
    written separately via :func:`persistence.write_time_anchor_state`.
    """
    processed_root = Path(processed_root)
    manifest_root = _manifest_root(manifest_root)
    overrides = overrides or {}

    # --- Experiment & asset metadata (read-only) ---
    experiments = load_experiments(manifest_root / "experiments.csv")
    experiment = next((e for e in experiments if e.experiment_id == experiment_id), None)
    if experiment is None:
        return TimeAnchorReport(
            battery_id="",
            experiment_id=experiment_id,
            anchor_version=config.version,
            status="FAIL",
            assets=[],
            warnings=[f"experiment {experiment_id} not found in manifest"],
            limitations=["EXPERIMENT_NOT_FOUND"],
            validated_sync=False,
        )

    assets = load_data_assets(manifest_root / "data_assets.csv")
    experiment_assets = [a for a in assets if a.experiment_id == experiment_id]

    # --- Electrical coverage window from processed records (read-only) ---
    electrical_start: pd.Timestamp | None = None
    electrical_end: pd.Timestamp | None = None
    electrical_path = processed_root / "electrical" / experiment.battery_id / experiment_id
    records_path = electrical_path / "records.parquet"
    if records_path.exists():
        records = pd.read_parquet(records_path)
        if "timestamp" in records and not records["timestamp"].empty:
            electrical_start = records["timestamp"].min()
            electrical_end = records["timestamp"].max()

    reference = ExperimentTimeReference(
        battery_id=experiment.battery_id,
        experiment_id=experiment.experiment_id,
        experiment_start_time=experiment.start_time,
        experiment_end_time=experiment.end_time,
        electrical_start_time=electrical_start.to_pydatetime()
        if electrical_start is not None
        else None,
        electrical_end_time=electrical_end.to_pydatetime() if electrical_end is not None else None,
        timezone_known=False,
        timezone_name=None,
        reference_sources=["experiments.csv", "records.parquet"],
    )

    warnings: list[str] = []
    limitations: list[str] = ["timezone unknown; no reliable timezone metadata"]
    assets_result: list[dict] = []
    validated_sync = False

    for asset in experiment_assets:
        if asset.modality != "ultrasound":
            continue

        # Read per-asset elapsed coverage from processed frames.parquet (read-only).
        frames_pool = _read_frames(processed_root, experiment.battery_id, experiment.experiment_id)
        elapsed_min, elapsed_max = _elapsed_range(frames_pool, asset.asset_id)
        if elapsed_min is None:
            warnings.append(
                f"asset {asset.asset_id}: no frames found; elapsed coverage unavailable"
            )

        candidates, evidence = collect_candidates(
            asset_id=asset.asset_id,
            modality=asset.modality,
            file_start_time=asset.file_start_time,
            overrides=overrides,
        )
        # Record filename hint (raw evidence, never authoritative) and experiment-start hint.
        evidence.append(filename_hint_evidence(asset.asset_id, asset.relative_path.name))
        hint = experiment_start_hint_evidence(asset.asset_id, experiment.start_time)
        if hint is not None:
            evidence.append(hint)

        assessment = build_assessment(
            asset_id=asset.asset_id,
            modality=asset.modality,
            elapsed_min_s=elapsed_min if elapsed_min is not None else 0.0,
            elapsed_max_s=elapsed_max if elapsed_max is not None else 0.0,
            candidates=candidates,
            evidence=evidence,
            overrides=overrides,
        )

        selected = next(
            (c for c in candidates if c.anchor_id == assessment.selected_anchor_id), None
        )
        if selected is not None and elapsed_min is not None and elapsed_max is not None:
            # Choose a reference window: prefer electrical coverage, fall back to experiment.
            ref_start = reference.electrical_start_time or reference.experiment_start_time
            ref_end = reference.electrical_end_time or reference.experiment_end_time
            if ref_start is not None and ref_end is not None:
                coverage = assess_coverage(
                    anchor_datetime=selected.anchor_datetime,
                    elapsed_min_s=elapsed_min,
                    elapsed_max_s=elapsed_max,
                    reference_start=ref_start,
                    reference_end=ref_end,
                )
                assessment.coverage = coverage
                if not is_plausible(coverage, config.plausibility):
                    warnings.append(
                        f"asset {asset.asset_id}: candidate coverage outside plausibility "
                        "thresholds (diagnostic only; anchor unchanged)"
                    )
            else:
                warnings.append(
                    f"asset {asset.asset_id}: no reference window; coverage not assessed"
                )
        elif selected is None:
            warnings.append(f"asset {asset.asset_id}: no anchor; status UNVERIFIED")

        assets_result.append(assessment.model_dump(mode="json"))

    # --- Report status ---
    status = _report_status(assets_result, warnings)
    if any(a.get("anchor_status") is None for a in assets_result):
        warnings.append("some ultrasound assets have no anchor")
    if status == "PASS" and any(
        a.get("anchor_status") in ("UNVERIFIED", None) for a in assets_result
    ):
        status = "PASS_WITH_WARNINGS"

    return TimeAnchorReport(
        battery_id=experiment.battery_id,
        experiment_id=experiment.experiment_id,
        anchor_version=config.version,
        status=status,
        assets=assets_result,
        warnings=warnings,
        limitations=limitations,
        validated_sync=validated_sync,
    )


def _report_status(assets: list[dict], warnings: list[str]) -> str:
    # No assets to judge or any unassessed anchor -> warn rather than fail.
    if warnings:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _read_frames(processed_root: Path, battery_id: str, experiment_id: str) -> pd.DataFrame | None:
    frames_path = processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
    if not frames_path.exists():
        return None
    return pd.read_parquet(frames_path)


def _elapsed_range(frames: pd.DataFrame | None, asset_id: str) -> tuple[float | None, float | None]:
    if frames is None or frames.empty:
        return None, None
    subset = (
        frames[frames["ultrasound_asset_id"] == asset_id]
        if "ultrasound_asset_id" in frames
        else frames
    )
    if subset.empty or "elapsed_time_s" not in subset:
        return None, None
    return float(subset["elapsed_time_s"].min()), float(subset["elapsed_time_s"].max())

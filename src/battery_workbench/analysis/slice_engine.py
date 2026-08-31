"""BRW-012 Condition Slice Engine — high-level entry.

``create_analysis_slice`` reads one canonical MeasurementEvents file, applies a
typed ``ConditionSliceSpec``, computes a deterministic slice id, and persists the
analysis slice + manifest + report. It never re-synchronizes, rebuilds events,
or computes waveform features.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

from battery_workbench.analysis.conditions import apply_condition_slice
from battery_workbench.analysis.schemas import (
    AnalysisSliceConfig,
    AnalysisSliceReport,
    ConditionSliceSpec,
)
from battery_workbench.analysis.slice_id import build_analysis_slice_id, normalize_spec

logger = logging.getLogger(__name__)

# Columns always preserved on a slice (identity + waveform locators).
_IDENTITY_COLS = [
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "ultrasound_asset_id",
    "frame_index_raw",
    "event_order_index",
    "waveform_group",
    "waveform_row_index",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_analysis_slice(
    *,
    measurement_events_path: Path,
    spec: ConditionSliceSpec,
    output_root: Path,
    config: AnalysisSliceConfig | None = None,
) -> AnalysisSliceReport:
    """Build one analysis slice from a MeasurementEvents file."""
    from battery_workbench.analysis.persistence import write_slice_payload
    from battery_workbench.analysis.validation import compute_slice_status

    measurement_events_path = Path(measurement_events_path)
    output_root = Path(output_root)
    config = config or AnalysisSliceConfig()

    if not measurement_events_path.exists():
        raise FileNotFoundError(f"measurement events not found: {measurement_events_path}")

    events = pd.read_parquet(measurement_events_path)
    input_checksum = _sha256(measurement_events_path)
    input_row_count = len(events)

    # Normalize + deterministic id.
    requested_spec = spec.model_dump(mode="json")
    normalized_spec = normalize_spec(requested_spec)
    slice_id = build_analysis_slice_id(input_checksum, normalized_spec)

    # Apply filter.
    sliced, breakdown = apply_condition_slice(events, spec)
    output_row_count = len(sliced)
    excluded_row_count = input_row_count - output_row_count

    warnings: list[str] = []
    if spec.step_types:
        available = set(events["step_type"].dropna().unique()) if "step_type" in events else set()
        missing = [s for s in spec.step_types if s not in available]
        warnings.extend(f"unknown step_type '{s}' matches 0 rows" for s in missing)

    status = compute_slice_status(
        rows_before=input_row_count, rows_after=output_row_count, warning=bool(warnings)
    )

    # Determine battery/experiment from the input (preserve identity).
    battery_id = str(events["battery_id"].iloc[0]) if not events.empty else ""
    experiment_id = str(events["experiment_id"].iloc[0]) if not events.empty else ""

    report = write_slice_payload(
        sliced=sliced,
        battery_id=battery_id,
        experiment_id=experiment_id,
        analysis_slice_id=slice_id,
        events_path=measurement_events_path,
        input_checksum=input_checksum,
        input_row_count=input_row_count,
        output_row_count=output_row_count,
        excluded_row_count=excluded_row_count,
        breakdown=breakdown,
        requested_spec=requested_spec,
        normalized_spec=normalized_spec,
        analysis_eligible_only=spec.analysis_eligible_only,
        status=status,
        warnings=warnings,
        config=config,
        output_root=output_root,
        identity_cols=_IDENTITY_COLS,
    )
    return report

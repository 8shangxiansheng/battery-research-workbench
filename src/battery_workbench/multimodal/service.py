"""High-level BRW-011 measurement-event service.

Convenience entry that resolves the canonical BRW-010 aligned/candidates paths
under ``data/processed`` and delegates to :func:`builder.build_measurement_events`.
Pure composition; contains no matching or enrichment logic itself.
"""

from __future__ import annotations

from pathlib import Path

from battery_workbench.multimodal.builder import build_measurement_events
from battery_workbench.multimodal.schemas import (
    MeasurementEventConfig,
    MeasurementEventReport,
)


def build_events_for_experiment(
    battery_id: str,
    experiment_id: str,
    *,
    processed_root: Path,
    config: MeasurementEventConfig | None = None,
) -> MeasurementEventReport:
    """Build canonical events for one battery/experiment from BRW-010 outputs."""
    processed_root = Path(processed_root)
    sync_dir = processed_root / "synchronization" / battery_id / experiment_id
    aligned = sync_dir / "aligned_ultrasound_frames.parquet"
    candidates = sync_dir / "synchronization_candidates.parquet"
    electrical = processed_root / "electrical" / battery_id / experiment_id / "records.parquet"
    aux_temp = (
        processed_root / "electrical" / battery_id / experiment_id / "aux_temperature.parquet"
    )

    config = config or MeasurementEventConfig()
    return build_measurement_events(
        aligned_frames_path=aligned,
        sync_candidates_path=candidates,
        electrical_records_path=electrical,
        aux_temperature_path=aux_temp,
        output_dir=processed_root,
        config=config,
    )

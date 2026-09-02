"""BRW-011 MeasurementEvent builder.

Builds one ``CanonicalMeasurementEvent`` per aligned ultrasound frame from
BRW-010 output, propagating (never recomputing) synchronization state and
exact-joining the selected electrical record for unique, in-tolerance matches.
No timestamp re-matching occurs here.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from battery_workbench.multimodal.electrical_index import (
    LocatorError,
    build_aux_index,
    build_electrical_index,
    normalize_locator,
    resolve_selected,
)
from battery_workbench.multimodal.event_id import build_measurement_event_id
from battery_workbench.multimodal.schemas import (
    CanonicalMeasurementEvent,
    MeasurementEventConfig,
    MeasurementEventReport,
)
from battery_workbench.multimodal.validation import (
    compute_event_quality,
    validate_ambiguous_no_selection,
    validate_candidate_invariant,
)

# Logical whitelist -> BRW-003 canonical record column.
_ENRICH_SOURCE: dict[str, str] = {
    "cycle_index_raw": "cycle_index_raw",
    "step_index_raw": "step_index_raw",
    "step_type": "step_type_raw",
    "voltage_v": "voltage_v",
    "current_a": "current_a",
    "capacity_ah": "capacity_ah",
    "charge_capacity_ah": "charge_capacity_ah",
    "discharge_capacity_ah": "discharge_capacity_ah",
    "energy_wh": "energy_wh",
    "power_w": "power_w",
    "soc_dod_percent": "soc_dod_percent",
    "contact_resistance_mohm": "contact_resistance_mohm",
    "dq_dv_raw": "dqdv_mah_per_v",
}


def build_candidate_relation(
    candidates: pd.DataFrame,
    identity_lookup: dict[int, tuple[str, str, str]] | None = None,
) -> pd.DataFrame:
    """Attach ``measurement_event_id`` to BRW-010 candidate evidence.

    Adds the canonical event id for each candidate row using its frame identity.
    ``identity_lookup`` maps ``frame_index_raw -> (battery_id, experiment_id,
    ultrasound_asset_id)`` for candidate tables missing those columns. Does not
    recompute, reorder, or collapse candidates.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame(columns=["measurement_event_id"])
    out = candidates.copy()
    ids: list[str] = []
    for _, row in out.iterrows():
        frame = int(row["frame_index_raw"])
        if (
            "battery_id" in out.columns
            and "experiment_id" in out.columns
            and "ultrasound_asset_id" in out.columns
        ):
            battery = str(row["battery_id"])
            experiment = str(row["experiment_id"])
            asset = str(row["ultrasound_asset_id"])
        elif identity_lookup is not None and frame in identity_lookup:
            battery, experiment, asset = identity_lookup[frame]
        else:
            raise ValueError(f"candidate row for frame {frame} lacks identity columns")
        ids.append(build_measurement_event_id(battery, experiment, asset, frame))
    out["measurement_event_id"] = ids
    cols = ["measurement_event_id"] + [c for c in out.columns if c != "measurement_event_id"]
    return out[cols]


def _enrich(
    record: dict,
    aux_index: dict[tuple[str, int], float],
    locator: tuple[str, int] | str | int | None,
) -> dict:
    """Exact electrical enrichment from a resolved record + auxiliary temp."""
    result: dict = {}
    for logical, source in _ENRICH_SOURCE.items():
        result[logical] = record.get(source)
    # Auxiliary temperature exact join by composite (asset, locator). A
    # missing/invalid aux identity yields null temperature, never a recompute.
    try:
        if isinstance(locator, tuple):
            key = locator
        else:
            key = (str(record.get("electrical_asset_id")), normalize_locator(locator))
        result["temperature_c"] = aux_index.get(key)
    except ValueError:
        result["temperature_c"] = None
    return result


def _build_event(row: dict, cfg: MeasurementEventConfig) -> CanonicalMeasurementEvent:
    """Build one canonical event from one aligned row (no re-matching)."""
    eid = build_measurement_event_id(
        str(row["battery_id"]),
        str(row["experiment_id"]),
        str(row["ultrasound_asset_id"]),
        int(row["frame_index_raw"]),
    )
    status = str(row.get("match_status", ""))
    locator = row.get("electrical_record_locator")
    has_locator = locator is not None and pd.notna(locator) and str(locator).strip() != ""
    within = bool(row.get("within_tolerance", False))

    # Compute quality + eligibility.
    if status == "MATCHED_UNIQUE":
        quality = compute_event_quality(status, within=within, locator_valid=has_locator)
    else:
        quality = compute_event_quality(status, within=within, locator_valid=False)
    eligible = quality == "READY"

    return CanonicalMeasurementEvent(
        measurement_event_id=eid,
        battery_id=str(row["battery_id"]),
        experiment_id=str(row["experiment_id"]),
        ultrasound_asset_id=str(row["ultrasound_asset_id"]),
        frame_index_raw=int(row["frame_index_raw"]),
        event_order_index=int(row.get("event_order_index", row["frame_index_raw"])),
        source_file=row.get("source_file"),
        source_line_index=row.get("source_line_index"),
        waveform_group=row.get("waveform_group"),
        waveform_row_index=row.get("waveform_row_index"),
        provisional_absolute_timestamp=row.get("provisional_absolute_timestamp"),
        elapsed_time_s=row.get("elapsed_time_s"),
        timezone_known=bool(row.get("timezone_known", False)),
        timezone_name=row.get("timezone_name"),
        match_status=status,
        sync_error_s=row.get("sync_error_s"),
        within_tolerance=within,
        candidate_timestamp_count=int(row.get("candidate_timestamp_count", 0) or 0),
        candidate_record_count=int(row.get("candidate_record_count", 0) or 0),
        sync_ambiguous=bool(row.get("sync_ambiguous", False)),
        ambiguity_type=row.get("ambiguity_type"),
        boundary_flag=bool(row.get("boundary_flag", False)),
        boundary_reason=row.get("boundary_reason"),
        matching_performed=bool(row.get("matching_performed", True)),
        validated_sync=False,
        sync_semantics=row.get("sync_semantics", "MATCHED_USING_PROVISIONAL_TIMEBASE"),
        anchor_id=row.get("anchor_id"),
        anchor_status=row.get("anchor_status"),
        event_quality_status=quality,
        analysis_eligible=eligible,
        event_quality_reason="" if eligible else f"match_status={status}",
    )


def _apply_electrical(
    event: CanonicalMeasurementEvent,
    aligned_row: pd.Series,
    electrical_index: dict[tuple[str, int], dict],
    aux_index: dict[tuple[str, int], float],
) -> CanonicalMeasurementEvent:
    """Exact-join via composite (electrical_asset_id, locator); no rematch."""
    if event.match_status != "MATCHED_UNIQUE":
        return event
    locator = aligned_row.get("electrical_record_locator")
    if locator is None or pd.isna(locator) or str(locator).strip() == "":
        return event
    # G2: composite identity is mandatory under the new sync contract — a
    # unique match without an asset id is an integrity error, never a
    # locator-only fallback.
    asset_id = aligned_row.get("electrical_asset_id")
    if asset_id is None or pd.isna(asset_id) or str(asset_id).strip() == "":
        raise LocatorError(
            f"MATCHED_UNIQUE row {event.measurement_event_id} has no "
            "electrical_asset_id (composite selected identity contract)"
        )
    record = resolve_selected(str(locator), electrical_index, asset_id=str(asset_id))
    enrichment = _enrich(record, aux_index, (str(asset_id), locator))
    # Apply selected-identity + enriched state; quality stays deterministically READY.
    for field, value in enrichment.items():
        setattr(event, field, value)
    event.electrical_asset_id = str(asset_id)
    event.electrical_record_locator = str(locator)
    event.electrical_row_index = record.get("record_index_raw")
    event.electrical_timestamp = record.get("timestamp")
    return event


def build_measurement_events(
    *,
    aligned_frames_path: Path,
    sync_candidates_path: Path,
    electrical_records_path: Path,
    output_dir: Path,
    config: MeasurementEventConfig,
    aux_temperature_path: Path | None = None,
) -> MeasurementEventReport:
    """Build canonical measurement events from BRW-010 aligned + candidates."""
    aligned = pd.read_parquet(aligned_frames_path)
    candidates = (
        pd.read_parquet(sync_candidates_path) if Path(sync_candidates_path).exists() else None
    )
    records = pd.read_parquet(electrical_records_path)

    electrical_index = build_electrical_index(records)
    aux_index: dict[tuple[str, int], float] = {}
    if aux_temperature_path is not None and Path(aux_temperature_path).exists():
        aux = pd.read_parquet(aux_temperature_path)
        aux_index = build_aux_index(aux)

    # Integrity: ambiguous frames carry no selected locator.
    validate_ambiguous_no_selection(aligned)

    events = [
        _apply_electrical(
            _build_event(row, config),
            row,
            electrical_index,
            aux_index,
        )
        for _, row in aligned.iterrows()
    ]
    events_df = pd.DataFrame([e.model_dump(mode="python") for e in events])

    # Build candidate relation and enforce invariants.
    if candidates is not None and not candidates.empty:
        identity_lookup = {
            int(row["frame_index_raw"]): (
                str(row["battery_id"]),
                str(row["experiment_id"]),
                str(row["ultrasound_asset_id"]),
            )
            for _, row in aligned.iterrows()
        }
        rel = build_candidate_relation(candidates, identity_lookup=identity_lookup)
    else:
        rel = pd.DataFrame()
    if not rel.empty:
        validate_candidate_invariant(aligned, rel)

    from battery_workbench.multimodal.persistence import write_measurement_event_payload

    report = write_measurement_event_payload(
        events=events_df,
        candidates=rel,
        aligned=aligned,
        candidates_input=candidates,
        records=records,
        aux_row_count=len(aux_index),
        battery_id=str(events_df["battery_id"].iloc[0]) if not events_df.empty else "",
        experiment_id=str(events_df["experiment_id"].iloc[0]) if not events_df.empty else "",
        config=config,
        aligned_frames_path=Path(aligned_frames_path),
        sync_candidates_path=Path(sync_candidates_path),
        electrical_records_path=Path(electrical_records_path),
        aux_temperature_path=aux_temperature_path,
        output_dir=Path(output_dir),
    )
    return report

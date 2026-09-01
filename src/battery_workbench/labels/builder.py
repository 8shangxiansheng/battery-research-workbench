"""BRW-014 Reference Label builder.

Builds event-level SOC/SOH reference labels and cycle-level SOH labels from
canonical electrical artifacts. Layer isolation is strict: labels are derived
from electrical protocol/capacity data only — never from ultrasound features.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from battery_workbench.labels.leakage import build_group_ids
from battery_workbench.labels.schemas import LabelConfig, LabelReport
from battery_workbench.labels.soc import compute_soc_reference
from battery_workbench.labels.soh import build_cycle_soh_labels, select_reference_capacity
from battery_workbench.labels.tof_readiness import evaluate_tof_readiness
from battery_workbench.labels.validation import (
    validate_no_silent_clip,
    validate_no_ultrasound_features,
)

logger = logging.getLogger(__name__)

_STEP_TYPE_DIRECTION = {
    "恒流充电": "CHARGE",
    "恒压充电": "CHARGE",
    "恒流放电": "DISCHARGE",
    "搁置": "REST",
}


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cycle_complete(steps: pd.DataFrame) -> dict[tuple, bool]:
    """A cycle is complete when it has both a charge step and a discharge step."""
    out: dict[tuple, bool] = {}
    for key, sub in steps.groupby(["battery_id", "experiment_id", "cycle_index_raw"]):
        types = set(sub["step_type_raw"].dropna().unique())
        out[key] = ("恒流放电" in types) and ("恒流充电" in types or "恒压充电" in types)
    return out


def _charge_offsets(steps: pd.DataFrame) -> dict[tuple, float]:
    """Cumulative charged-since-empty at the START of each charge step.

    Steps within a cycle are ordered by step_index_raw; each charge step
    accumulates on top of the previous charge steps' step capacities.
    """
    offsets: dict[tuple, float] = {}
    for key, sub in steps.groupby(["battery_id", "experiment_id", "cycle_index_raw"]):
        ordered = sub.sort_values("step_index_raw")
        running = 0.0
        for _, row in ordered.iterrows():
            offsets[(key[0], key[1], row["cycle_index_raw"], row["step_index_raw"])] = running
            if row["step_type_raw"] in ("恒流充电", "恒压充电"):
                running += float(row["charge_capacity_ah"] or 0.0)
    return offsets


def build_reference_labels(
    *,
    measurement_events_path: Path,
    records_path: Path,
    cycles_path: Path,
    steps_path: Path,
    ultrasound_manifest_path: Path,
    output_root: Path,
    config: LabelConfig | None = None,
) -> LabelReport:
    """Build canonical reference labels for one experiment."""
    from battery_workbench.labels.persistence import write_label_payload

    measurement_events_path = Path(measurement_events_path)
    output_root = Path(output_root)
    config = config or LabelConfig()

    events = pd.read_parquet(measurement_events_path)
    cycles = pd.read_parquet(cycles_path)
    steps = pd.read_parquet(steps_path)

    # --- Cycle-level SOH labels ---
    reference = select_reference_capacity(cycles, rpt_capacity_ah=config.soh.rpt_capacity_ah)
    cycle_labels = build_cycle_soh_labels(cycles, reference=reference)
    cycle_complete_map = _cycle_complete(steps)

    # --- Per-step charge offsets for charged-since-empty ---
    offsets = _charge_offsets(steps)
    cycle_capacity = {
        (r["battery_id"], r["experiment_id"], r["cycle_index_raw"]): float(
            r["discharge_capacity_ah"]
        )
        for _, r in cycles.iterrows()
        if pd.notna(r["discharge_capacity_ah"])
    }

    # --- Event-level SOC + SOH propagation + groups ---
    rows: list[dict] = []
    soc_valid = soc_ineligible = 0
    for _, ev in events.iterrows():
        battery = str(ev["battery_id"])
        experiment = str(ev["experiment_id"])
        cycle = ev["cycle_index_raw"]
        step = ev["step_index_raw"]
        key = (battery, experiment, cycle)
        step_type = ev["step_type"] if pd.notna(ev["step_type"]) else None
        direction = _STEP_TYPE_DIRECTION.get(str(step_type), "REST")

        complete = cycle_complete_map.get(key, False)
        q_ref = cycle_capacity.get(key)
        anchor_ok = complete and q_ref is not None

        discharged = (
            float(ev["discharge_capacity_ah"])
            if direction == "DISCHARGE" and pd.notna(ev["discharge_capacity_ah"])
            else None
        )
        if direction == "CHARGE" and pd.notna(ev["charge_capacity_ah"]):
            base = offsets.get((battery, experiment, cycle, step), 0.0)
            charged = base + float(ev["charge_capacity_ah"])
        else:
            charged = None

        soc = compute_soc_reference(
            direction=direction,
            discharged_since_full_ah=discharged,
            charged_since_empty_ah=charged,
            q_ref_ah=q_ref,
            cycle_complete=complete,
            anchor_available=anchor_ok,
        )
        validate_no_silent_clip(soc.soc_reference_percent, soc.soc_reference_quality)
        if soc.soc_label_eligible:
            soc_valid += 1
        else:
            soc_ineligible += 1

        groups = (
            build_group_ids(battery, experiment, cycle)
            if pd.notna(cycle)
            else {
                k: None
                for k in (
                    "battery_group_id",
                    "experiment_group_id",
                    "cycle_group_id",
                    "label_group_id",
                )
            }
        )

        # SOH propagation by exact cycle key.
        cyc_row = cycle_labels[cycle_labels["cycle_index_raw"] == cycle]
        if not cyc_row.empty:
            cr = cyc_row.iloc[0]
            soh_pct = cr["soh_capacity_reference_percent"]
            soh_ref_ah = cr["reference_capacity_ah"]
            soh_ref_cycle = cr["soh_reference_cycle_index"]
            soh_quality = cr["soh_reference_quality"]
            soh_eligible = bool(cr["soh_label_eligible"])
        else:
            soh_pct = soh_ref_ah = soh_ref_cycle = soh_quality = None
            soh_eligible = False

        rows.append(
            {
                "measurement_event_id": ev["measurement_event_id"],
                "battery_id": battery,
                "experiment_id": experiment,
                "cycle_index_raw": cycle,
                "step_index_raw": step,
                "event_order_index": ev["event_order_index"],
                "soc_reference_percent": soc.soc_reference_percent,
                "soc_reference_method": config.soc.method,
                "soc_reference_capacity_ah": q_ref,
                "soc_anchor_type": "FULL_CHARGE_CV_END"
                if direction == "DISCHARGE"
                else ("EMPTY_DISCHARGE_END" if direction == "CHARGE" else None),
                "soc_anchor_event_id": None,
                "soc_direction": direction,
                "soc_label_temporality": soc.soc_label_temporality,
                "soc_reference_quality": soc.soc_reference_quality,
                "soc_label_eligible": soc.soc_label_eligible,
                "soc_formula_version": config.soc.formula_version,
                "soh_capacity_reference_percent": soh_pct,
                "soh_reference_capacity_ah": soh_ref_ah,
                "soh_reference_cycle_index": soh_ref_cycle,
                "soh_reference_method": "CAPACITY_BASELINE_RATIO",
                "soh_reference_quality": soh_quality,
                "soh_label_eligible": soh_eligible,
                "soh_formula_version": config.soh.formula_version,
                **groups,
            }
        )

    event_labels = pd.DataFrame(rows)
    validate_no_ultrasound_features(list(event_labels.columns))

    # --- Vendor SOC/DOD comparison diagnostic (never promoted) ---
    vendor = events["soc_dod_percent"] if "soc_dod_percent" in events.columns else None
    diagnostic: dict = {"valid_pair_count": 0}
    if vendor is not None:
        paired = pd.DataFrame(
            {
                "vendor": vendor,
                "derived": event_labels["soc_reference_percent"],
            }
        ).dropna()
        if not paired.empty:
            diff = (paired["derived"] - paired["vendor"]).abs()
            diagnostic = {
                "valid_pair_count": len(paired),
                "mean_abs_difference": float(diff.mean()),
                "median_difference": float(diff.median()),
                "max_difference": float(diff.max()),
            }

    # --- TOF readiness from the ultrasound manifest ---
    tof_input = {
        "sampling_rate_hz": None,
        "trigger_zero_available": False,
        "system_delay_calibration_available": False,
    }
    if Path(ultrasound_manifest_path).exists():
        um = json.loads(Path(ultrasound_manifest_path).read_text(encoding="utf-8"))
        assets = um.get("assets", [])
        if assets:
            first = assets[0]
            tof_input["sampling_rate_hz"] = first.get("sampling_rate_hz")
            tof_input["waveform_sample_count"] = (first.get("waveform_sample_counts") or [None])[0]
    tof = evaluate_tof_readiness(**tof_input)

    # --- Deterministic label_set_id ---
    from battery_workbench.labels.label_set_id import build_label_set_id

    label_set_id = build_label_set_id(
        input_checksum=_sha256(measurement_events_path),
        normalized_config=config.model_dump(mode="json"),
        label_definition_version=config.label_definition_version,
        reference_capacity_ah=reference.q_ref_ah,
    )

    return write_label_payload(
        event_labels=event_labels,
        cycle_labels=cycle_labels,
        tof=tof,
        battery_id=str(events["battery_id"].iloc[0]) if not events.empty else "",
        experiment_id=str(events["experiment_id"].iloc[0]) if not events.empty else "",
        label_set_id=label_set_id,
        measurement_events_path=measurement_events_path,
        records_path=Path(records_path),
        cycles_path=Path(cycles_path),
        steps_path=Path(steps_path),
        ultrasound_manifest_path=Path(ultrasound_manifest_path),
        soc_valid_count=soc_valid,
        soc_ineligible_count=soc_ineligible,
        soh_state_count=int(cycle_labels["cycle_index_raw"].nunique()),
        reference=reference,
        vendor_diagnostic=diagnostic,
        config=config,
        output_root=output_root,
    )

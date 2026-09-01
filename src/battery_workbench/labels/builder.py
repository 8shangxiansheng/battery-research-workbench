"""BRW-014 V2 Reference Label builder.

V2 SOC: direction-specific segment normalization (charge segment normalized by
its own measured charge total; discharge by its own discharge total) + rest
propagation within protocol-contiguous segments. The V1-style integral is kept
as a diagnostic. SOH unchanged (baseline capacity ratio) with an explicit
model-readiness guard. Layer isolation unchanged: labels never read ultrasound
features.
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
from battery_workbench.labels.soh import (
    build_cycle_soh_labels,
    select_reference_capacity,
    soh_model_readiness,
)
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
    out: dict[tuple, bool] = {}
    for key, sub in steps.groupby(["battery_id", "experiment_id", "cycle_index_raw"]):
        types = set(sub["step_type_raw"].dropna().unique())
        out[key] = ("恒流放电" in types) and ("恒流充电" in types or "恒压充电" in types)
    return out


def _charge_offsets(steps: pd.DataFrame) -> dict[tuple, float]:
    """Cumulative charged-since-empty at the START of each charge step."""
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
    supersedes_label_set_id: str | None = None,
) -> LabelReport:
    """Build canonical V2 reference labels for one experiment."""
    from battery_workbench.labels.persistence import write_label_payload

    measurement_events_path = Path(measurement_events_path)
    output_root = Path(output_root)
    config = config or LabelConfig()

    events = pd.read_parquet(measurement_events_path)
    cycles = pd.read_parquet(cycles_path)
    steps = pd.read_parquet(steps_path)

    # --- Cycle-level SOH labels (unchanged formula) ---
    reference = select_reference_capacity(cycles, rpt_capacity_ah=config.soh.rpt_capacity_ah)
    cycle_labels = build_cycle_soh_labels(cycles, reference=reference)
    cycle_complete_map = _cycle_complete(steps)

    # --- Segment denominators ---
    offsets = _charge_offsets(steps)
    charge_segment_total: dict[tuple, float] = {}
    discharge_segment_total: dict[tuple, float] = {}
    for (b, e, c), sub in steps.groupby(["battery_id", "experiment_id", "cycle_index_raw"]):
        charge_rows = sub[sub["step_type_raw"].isin(("恒流充电", "恒压充电"))]
        discharge_rows = sub[sub["step_type_raw"] == "恒流放电"]
        if not charge_rows.empty:
            charge_segment_total[(b, e, c)] = float(charge_rows["charge_capacity_ah"].sum())
        if not discharge_rows.empty:
            discharge_segment_total[(b, e, c)] = float(
                discharge_rows["discharge_capacity_ah"].max()
            )
    # V1-style single reference (discharge capacity) kept for the diagnostic only.
    discharge_ref_for_diagnostic = {
        (r["battery_id"], r["experiment_id"], r["cycle_index_raw"]): float(
            r["discharge_capacity_ah"]
        )
        for _, r in cycles.iterrows()
        if pd.notna(r["discharge_capacity_ah"])
    }

    # --- Build per-event context ---
    ctx_list: list[dict] = []
    for _, ev in events.iterrows():
        battery = str(ev["battery_id"])
        experiment = str(ev["experiment_id"])
        cycle = ev["cycle_index_raw"]
        step = ev["step_index_raw"]
        step_type = ev["step_type"] if pd.notna(ev["step_type"]) else None
        ctx_list.append(
            {
                "ev": ev,
                "battery": battery,
                "experiment": experiment,
                "cycle": cycle,
                "step": step,
                "key": (battery, experiment, cycle),
                "direction": _STEP_TYPE_DIRECTION.get(str(step_type), "REST"),
                "complete": cycle_complete_map.get((battery, experiment, cycle), False),
                "soc_result": None,
                "soc_value": None,
                "diag": None,
                "anchor_q": None,
            }
        )

    # --- Pass 1: active CHARGE / DISCHARGE segments ---
    for i, ctx in enumerate(ctx_list):
        ev = ctx["ev"]
        if ctx["direction"] == "REST":
            continue
        if ctx["direction"] == "CHARGE":
            q_total = charge_segment_total.get(ctx["key"])
            base = offsets.get((ctx["battery"], ctx["experiment"], ctx["cycle"], ctx["step"]), 0.0)
            q_progress = (
                base + float(ev["charge_capacity_ah"])
                if pd.notna(ev["charge_capacity_ah"])
                else None
            )
            # Experiment-initial charge start: no independent empty evidence.
            first_cycle = events["cycle_index_raw"].dropna().min()
            charge_rows_first = events[
                (events["cycle_index_raw"] == first_cycle) & (events["step_type"] == "恒流充电")
            ]
            is_initial = (
                ctx["cycle"] == first_cycle
                and not charge_rows_first.empty
                and ctx["step"] == charge_rows_first["step_index_raw"].min()
                and base == 0.0
            )
            anchor_q = "ASSUMED_INITIAL_ANCHOR" if is_initial else "REFERENCE_PROTOCOL_ANCHOR"
        else:  # DISCHARGE
            q_total = discharge_segment_total.get(ctx["key"])
            q_progress = (
                float(ev["discharge_capacity_ah"])
                if pd.notna(ev["discharge_capacity_ah"])
                else None
            )
            anchor_q = "REFERENCE_PROTOCOL_ANCHOR"

        soc = compute_soc_reference(
            direction=ctx["direction"],
            q_progress_ah=q_progress,
            q_segment_total_ah=q_total,
            cycle_complete=ctx["complete"],
            anchor_available=ctx["complete"],
            anchor_quality=anchor_q,
        )
        # V1-style unbounded diagnostic: charge normalized by discharge capacity.
        diag = None
        if ctx["direction"] == "CHARGE":
            q_dis_ref = discharge_ref_for_diagnostic.get(ctx["key"])
            if q_progress is not None and q_dis_ref:
                diag = 100.0 * q_progress / q_dis_ref
        elif ctx["direction"] == "DISCHARGE":
            diag = soc.soc_reference_percent
        ctx["soc_result"] = soc
        ctx["soc_value"] = soc.soc_reference_percent
        ctx["diag"] = diag
        ctx["anchor_q"] = soc.soc_anchor_quality

    # --- Pass 2: REST propagation (same cycle, protocol-contiguous only) ---
    for i, ctx in enumerate(ctx_list):
        if ctx["direction"] != "REST":
            continue
        prev_soc = None
        for j in range(i - 1, -1, -1):
            prev = ctx_list[j]
            prev_cycle = prev["cycle"]
            # Unattributable events (ambiguous frames, cycle=NaN) are not cycle
            # boundaries: skip them but keep walking the protocol chain.
            if pd.isna(prev_cycle):
                if prev["direction"] != "REST" and prev["soc_value"] is not None:
                    prev_soc = prev["soc_value"]
                    break
                continue
            if prev_cycle != ctx["cycle"]:
                break  # explicit cycle boundary: never forward-fill across cycles
            if prev["direction"] == "REST":
                if prev["soc_value"] is not None:
                    prev_soc = prev["soc_value"]  # contiguous rest keeps the value
                continue
            prev_soc = prev["soc_value"]  # last active segment end
            break
        soc = compute_soc_reference(
            direction="REST",
            prev_valid_soc=prev_soc,
            cycle_complete=ctx["complete"],
            anchor_available=ctx["complete"] and prev_soc is not None,
        )
        ctx["soc_result"] = soc
        ctx["soc_value"] = soc.soc_reference_percent
        ctx["diag"] = None
        ctx["anchor_q"] = soc.soc_anchor_quality

    # --- Assemble rows ---
    rows: list[dict] = []
    soc_valid = soc_ineligible = 0
    for ctx in ctx_list:
        ev = ctx["ev"]
        soc = ctx["soc_result"]
        if soc is None:
            soc = compute_soc_reference(
                direction="REST", prev_valid_soc=None, cycle_complete=ctx["complete"]
            )
        validate_no_silent_clip(soc.soc_reference_percent, soc.soc_reference_quality)
        if soc.soc_label_eligible:
            soc_valid += 1
        else:
            soc_ineligible += 1

        groups = (
            build_group_ids(ctx["battery"], ctx["experiment"], ctx["cycle"])
            if pd.notna(ctx["cycle"])
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

        cyc_row = cycle_labels[cycle_labels["cycle_index_raw"] == ctx["cycle"]]
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
                "battery_id": ctx["battery"],
                "experiment_id": ctx["experiment"],
                "cycle_index_raw": ctx["cycle"],
                "step_index_raw": ctx["step"],
                "event_order_index": ev["event_order_index"],
                "soc_reference_percent": soc.soc_reference_percent,
                "soc_reference_method": config.soc.method
                if ctx["direction"] != "REST"
                else "REST_PROPAGATED_FROM_PREVIOUS_VALID_REFERENCE",
                "soc_reference_capacity_ah": charge_segment_total.get(ctx["key"])
                if ctx["direction"] == "CHARGE"
                else discharge_segment_total.get(ctx["key"]),
                "soc_anchor_type": f"{ctx['direction']}_SEGMENT_ANCHOR",
                "soc_anchor_event_id": None,
                "soc_direction": ctx["direction"],
                "soc_label_temporality": soc.soc_label_temporality,
                "soc_reference_quality": soc.soc_reference_quality,
                "soc_label_eligible": soc.soc_label_eligible,
                "soc_formula_version": config.soc.formula_version,
                "soc_anchor_quality": soc.soc_anchor_quality,
                "soc_integral_unbounded_percent": ctx["diag"],
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

    # --- Vendor comparison diagnostic (per direction) ---
    vendor = events["soc_dod_percent"] if "soc_dod_percent" in events.columns else None
    vendor_diagnostic: dict = {"valid_pair_count": 0}
    if vendor is not None:
        merged = event_labels.merge(
            events[["measurement_event_id", "soc_dod_percent", "step_type"]],
            on="measurement_event_id",
        )
        paired = merged[merged["soc_reference_percent"].notna()]
        by_dir: dict = {}
        for st, g in paired.groupby("step_type"):
            d = (g["soc_reference_percent"] - g["soc_dod_percent"]).abs()
            by_dir[str(st)] = {
                "count": len(d),
                "mean_abs_difference": float(d.mean()),
                "median_difference": float(d.median()),
                "max_abs_difference": float(d.max()),
            }
        d_all = (paired["soc_reference_percent"] - paired["soc_dod_percent"]).abs()
        vendor_diagnostic = {
            "valid_pair_count": len(d_all),
            "mean_abs_difference": float(d_all.mean()),
            "median_difference": float(d_all.median()),
            "max_difference": float(d_all.max()),
            "by_step_type": by_dir,
        }

    # --- Apparent CE diagnostic ---
    ce_diag = {}
    for (b, e, c), sub in steps.groupby(["battery_id", "experiment_id", "cycle_index_raw"]):
        charge_rows = sub[sub["step_type_raw"].isin(("恒流充电", "恒压充电"))]
        discharge_rows = sub[sub["step_type_raw"] == "恒流放电"]
        qc = float(charge_rows["charge_capacity_ah"].sum()) if not charge_rows.empty else None
        qd = (
            float(discharge_rows["discharge_capacity_ah"].max())
            if not discharge_rows.empty
            else None
        )
        if qc and qd:
            ce_diag[f"cycle_{int(c)}"] = {
                "charge_capacity_total_ah": qc,
                "discharge_capacity_total_ah": qd,
                "apparent_coulombic_efficiency": qd / qc,
            }

    # --- SOH readiness guard ---
    readiness = soh_model_readiness(
        independent_state_count=int(cycle_labels["cycle_index_raw"].nunique()),
        frame_count=len(event_labels),
    )

    # --- TOF readiness (unchanged) ---
    tof_input = {
        "sampling_rate_hz": None,
        "trigger_zero_available": False,
        "system_delay_calibration_available": False,
    }
    if Path(ultrasound_manifest_path).exists():
        um = json.loads(Path(ultrasound_manifest_path).read_text(encoding="utf-8"))
        assets = um.get("assets", [])
        if assets:
            tof_input["sampling_rate_hz"] = assets[0].get("sampling_rate_hz")
            tof_input["waveform_sample_count"] = (
                assets[0].get("waveform_sample_counts") or [None]
            )[0]
    tof = evaluate_tof_readiness(**tof_input)

    # --- Deterministic label_set_id (V2 config changes it automatically) ---
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
        soh_readiness=readiness,
        reference=reference,
        vendor_diagnostic=vendor_diagnostic,
        ce_diagnostic=ce_diag,
        config=config,
        output_root=output_root,
        supersedes_label_set_id=supersedes_label_set_id,
    )

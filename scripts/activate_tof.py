"""Physical TOF Activation — run the real TOF computation chain.

Chain (BRW-017 pipeline step "Physical TOF Activation"):
  1. Synthetic arrival-detector validation (must pass; AGENTS.md #13).
  2. Run the validated detector on real waveforms → arrival_sample_index
     (pure sample domain — no fs needed).
  3. 参数录入: when user parameters are supplied (--sampling-rate-mhz,
     --trigger-sample-index), build a NEW parameter set (BRW-015
     user_overrides → new PS::id; legacy PS untouched).
  4. Compute canonical tof_us when the full chain is ready (fs AND trigger
     AND validated detector); otherwise materialize with an explicit
     tof_status / tof_block_reason.

Without user-supplied fs/trigger the tof_us column stays null and BLOCKED —
never forged from xcorr_shift_samples.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import zarr

from battery_workbench.features_physical.activation import build_tof_column
from battery_workbench.features_physical.arrival_detector import (
    DETECTOR_VERSION,
    detect_arrival_sample,
    validate_arrival_detector,
)
from battery_workbench.features_physical.engine import compute_relative_delay_us

ROOT = Path("data/processed")
WAVEFORM_STORE = ROOT / "ultrasound/CELL_001/EXP_001/waveforms.zarr"
FEATURES_PARQUET = (
    ROOT
    / "features/CELL_001/EXP_001/AS::39b284730b2c801104f0e960/FS::60649fd12c540267fe585914/ultrasound_features.parquet"
)
LEGACY_PS_DIR = ROOT / "parameters/CELL_001/EXP_001/PS::9ebbb833dfac3cf1cc9da8bc"
MEASUREMENT_EVENTS = ROOT / "multimodal/CELL_001/EXP_001/measurement_events.parquet"
LABEL_MANIFEST = ROOT / "labels/CELL_001/EXP_001/label_manifest.json"
ACTIVATION_DIR = ROOT / "features_physical/CELL_001/EXP_001"


def main(*, sampling_rate_mhz: float | None, trigger_sample_index: int | None) -> None:
    # --- 1. Synthetic validation (gate: must pass before touching real data) ---
    validation = validate_arrival_detector()
    assert validation["validated"], (
        f"arrival detector failed synthetic validation: {validation['failed_cases']}"
    )
    print(f"arrival detector validated: {DETECTOR_VERSION} ({validation['case_count']} cases)")

    # --- 2. Run detector on real waveforms (sample domain, no fs) ---
    features = pd.read_parquet(FEATURES_PARQUET)
    zg = zarr.open_group(str(WAVEFORM_STORE), mode="r")
    arrivals: list[int | None] = []
    for group, idx in zip(features["waveform_group"], features["waveform_row_index"], strict=True):
        wave = np.asarray(zg[str(group)][int(idx)])
        arrivals.append(detect_arrival_sample(wave))
    n_found = sum(a is not None for a in arrivals)
    print(f"arrival detection: {n_found}/{len(arrivals)} events")

    # --- 3. Parameter entry (optional; builds a NEW PS::id) ---
    effective: dict = json.loads((LEGACY_PS_DIR / "effective_parameters.json").read_text())
    parameter_set_id = "PS::9ebbb833dfac3cf1cc9da8bc (legacy; no user entry this run)"
    if sampling_rate_mhz is not None or trigger_sample_index is not None:
        from battery_workbench.parameters.service import build_parameter_set

        overrides: dict[str, dict] = {}
        if sampling_rate_mhz is not None:
            overrides["ultrasound.sampling_rate_hz"] = {
                "value": sampling_rate_mhz,
                "unit": "MHz",
                "evidence_note": "BRW-017 TOF activation user entry",
            }
        if trigger_sample_index is not None:
            overrides["ultrasound.trigger_sample_index"] = {
                "value": trigger_sample_index,
                "unit": "sample",
                "evidence_note": "BRW-017 TOF activation user entry",
            }
        report = build_parameter_set(
            output_root=ROOT,
            measurement_events_path=MEASUREMENT_EVENTS,
            waveform_store_path=WAVEFORM_STORE,
            label_manifest_path=LABEL_MANIFEST,
            user_overrides=overrides,
        )
        parameter_set_id = report.parameter_set_id
        effective = json.loads(
            (
                ROOT
                / "parameters/CELL_001/EXP_001"
                / parameter_set_id
                / "effective_parameters.json"
            ).read_text()
        )
        print(f"parameter entry → new {parameter_set_id}")

    # --- 4. Canonical tof_us (gated: fs AND trigger AND validated detector) ---
    fs_entry = effective.get("ultrasound.sampling_rate_hz", {})
    fs_resolved = fs_entry.get("value") if fs_entry.get("status") == "RESOLVED" else None
    tof_values, tof_status, tof_block_reason = build_tof_column(
        effective=effective,
        arrival_samples=arrivals,
        detector_validated=validation["validated"],
    )
    # Relative propagation-delay shift (analysis layer, NOT canonical tof_us).
    # With a user-supplied fs this quantity becomes interpretable in time.
    rel_values = [
        compute_relative_delay_us(xcorr_shift_samples=s, sampling_rate_hz=fs_resolved)
        for s in features["xcorr_shift_samples"]
    ]
    out = pd.DataFrame(
        {
            "measurement_event_id": features["measurement_event_id"],
            "arrival_sample_index": pd.array(arrivals, dtype="Int64"),
            "detector_version": DETECTOR_VERSION,
            "amplitude_a_u": features["waveform_abs_peak_a_u"],
            "tof_us": pd.array(tof_values, dtype="Float64"),
            "tof_status": tof_status,
            "tof_block_reason": tof_block_reason,
            "relative_tof_shift_us": pd.array(rel_values, dtype="Float64"),
            "parameter_set_id": parameter_set_id,
        }
    )
    ACTIVATION_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = ACTIVATION_DIR / "ultrasound_tof.parquet"
    out.to_parquet(parquet_path, index=False)

    manifest = {
        "table": "ultrasound_tof",
        "detector_version": DETECTOR_VERSION,
        "detector_validation": validation,
        "row_count": len(out),
        "arrival_detected": n_found,
        "tof_status": tof_status,
        "tof_block_reason": tof_block_reason,
        "parameter_set_id": parameter_set_id,
        "tof_us_semantics": "ABSOLUTE ARRIVAL-BASED FLIGHT TIME ESTIMATE",
        "tof_us_not": "xcorr relative shift (kept as auxiliary candidate xcorr_shift_samples)",
        "relative_tof_shift_us": {
            "available": any(v is not None for v in rel_values),
            "layer": "analysis (NOT canonical tof_us)",
            "definition": "xcorr_shift_samples / fs * 1e6",
        },
        "real_data_observation": (
            "Detected arrival is sample 0 for all events: the acquisition window "
            "starts with the main burst already in progress (no pre-trigger quiet "
            "region). A secondary burst appears later in the window. With the "
            "user-supplied trigger=0, absolute flight time computes to <= 0 and "
            "is therefore nonphysical — the true onset precedes the window."
        ),
        "chain": [
            "parameter entry (BRW-015 user_overrides → new PS::id)",
            "validated arrival detector (synthetic suite passed)",
            "tof_us = (arrival_sample_index - trigger_sample_index) / fs * 1e6",
        ],
    }
    (ACTIVATION_DIR / "tof_activation_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"tof_us: {tof_status} ({tof_block_reason or 'READY'})")
    print(f"artifacts: {parquet_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Physical TOF Activation")
    parser.add_argument("--sampling-rate-mhz", type=float, default=None)
    parser.add_argument("--trigger-sample-index", type=int, default=None)
    args = parser.parse_args()
    main(sampling_rate_mhz=args.sampling_rate_mhz, trigger_sample_index=args.trigger_sample_index)

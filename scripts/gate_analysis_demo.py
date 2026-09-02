"""BRW-018 real-data demo: waveform gate scientific analysis workflow.

waveform → user-defined gate → gated feature extraction → feature-label
analysis → explicit selected features → dataset.

Real gates (chosen from the waveform band-energy distribution, SIGNAL_ONLY):
  Gate A  PRIMARY_SIGNAL_GATE    samples 0-200    (main burst, onset in-window)
  Gate B  SECONDARY_SIGNAL_GATE  samples 800-980  (secondary burst)
Both ANALYSIS_SLICE_GATE. Between-gate delay is diagnostic (NOT tof_us) —
the physical interpretation is not confirmed.
A 5-event EXPLORATORY_FRAME_GATE demo (adaptive secondary-peak windows) is
materialized separately with not_ml_ready=true.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import zarr

from battery_workbench.datasets.builder import build_soc_dataset
from battery_workbench.datasets.schemas import DatasetConfig
from battery_workbench.gates.analysis import (
    build_gated_feature_label_analysis,
    delay_locator,
    gated_locator,
)
from battery_workbench.gates.engine import extract_gated_features, gate_stability_audit
from battery_workbench.gates.persistence import (
    write_gate_report_artifacts,
    write_gated_analysis_payload,
    write_gated_feature_payload,
)
from battery_workbench.gates.schemas import GateScope, GateSpec, TOFDefinitionSpec

ROOT = Path("data/processed")
WAVEFORM_STORE = ROOT / "ultrasound/CELL_001/EXP_001/waveforms.zarr"
FEATURES_PARQUET = (
    ROOT
    / "features/CELL_001/EXP_001/AS::39b284730b2c801104f0e960/FS::60649fd12c540267fe585914/ultrasound_features.parquet"
)
LABEL_SET_PATH = ROOT / "labels/CELL_001/EXP_001/event_labels.parquet"
CYCLE_LABELS_PATH = ROOT / "labels/CELL_001/EXP_001/cycle_labels.parquet"
MEASUREMENT_EVENTS = ROOT / "multimodal/CELL_001/EXP_001/measurement_events.parquet"
PARAMETER_SET_ID = "PS::99a655be1ffdffc6aa217fa8"  # fs=50MHz, trigger=0 (user entry)
FS_HZ = 50e6
SATURATION_LIMIT = 32000

INTEGRITY_PATHS = [
    WAVEFORM_STORE,
    MEASUREMENT_EVENTS,
    LABEL_SET_PATH,
    CYCLE_LABELS_PATH,
    FEATURES_PARQUET,
    ROOT / "datasets/CELL_001/EXP_001/SOC/DS::a9cf6352b2638862ec3e4c81",
    ROOT / "datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e",
]


def _path_digest(path: Path) -> str:
    if path.is_file():
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(path)).encode())
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _integrity_snapshot() -> dict[str, str]:
    return {str(p): _path_digest(p) for p in INTEGRITY_PATHS}


def main() -> None:
    integrity_before = _integrity_snapshot()

    # --- gates (bounds chosen from the band-energy distribution, SIGNAL_ONLY) ---
    gate_a = GateSpec(
        gate_name="primary_signal",
        start_sample=0,
        end_sample=200,
        scope=GateScope.ANALYSIS_SLICE_GATE,
        waveform_length=1250,
        semantic_role="ANALYSIS_WINDOW",
        source="band-energy distribution: main burst 0-160 + tail",
        created_by="BRW-018 demo",
    )
    gate_b = GateSpec(
        gate_name="secondary_signal",
        start_sample=800,
        end_sample=980,
        scope=GateScope.ANALYSIS_SLICE_GATE,
        waveform_length=1250,
        semantic_role="ANALYSIS_WINDOW",
        source="band-energy distribution: secondary burst ~820-960",
        created_by="BRW-018 demo",
    )
    tof_def = TOFDefinitionSpec(
        mode="BETWEEN_GATES",
        reference_gate_id=gate_a.gate_id,
        received_gate_id=gate_b.gate_id,
        physical_interpretation_confirmed=False,
        definition_note=(
            "Diagnostic between-gate delay only. Whether primary->secondary is "
            "the studied propagation TOF is NOT confirmed."
        ),
    )
    print(f"Gate A: {gate_a.gate_id} samples 0-200")
    print(f"Gate B: {gate_b.gate_id} samples 800-980")

    features = pd.read_parquet(FEATURES_PARQUET)
    zg = zarr.open_group(str(WAVEFORM_STORE), mode="r")

    # --- gated feature extraction (event x gate grain) ---
    rows: list[dict] = []
    delay_rows: list[dict] = []
    full_peaks = features["waveform_abs_peak_a_u"].to_numpy(dtype=float)
    for pos, (group, idx, event_id) in enumerate(
        zip(
            features["waveform_group"],
            features["waveform_row_index"],
            features["measurement_event_id"],
            strict=True,
        )
    ):
        wave = np.asarray(zg[str(group)][int(idx)])
        for gate in (gate_a, gate_b):
            feats = extract_gated_features(wave, gate)
            feats["measurement_event_id"] = event_id
            rows.append(feats)
        a_seg = np.abs(wave[gate_a.start_sample : gate_a.end_sample])
        b_seg = np.abs(wave[gate_b.start_sample : gate_b.end_sample])
        delay_samples = (
            gate_b.start_sample
            + int(np.argmax(b_seg))
            - (gate_a.start_sample + int(np.argmax(a_seg)))
        )
        delay_rows.append(
            {
                "measurement_event_id": event_id,
                "delay_samples": delay_samples,
                "delay_us": delay_samples / FS_HZ * 1e6,
                "gate_a_amplitude": float(a_seg.max()),
                "gate_b_amplitude": float(b_seg.max()),
                "full_peak": full_peaks[pos],
            }
        )
    gated = pd.DataFrame(rows)
    delays = pd.DataFrame(delay_rows)
    print(f"gated rows: {len(gated)} ({len(features)} events x 2 gates)")

    # --- gate stability audit (engine module, deterministic) ---
    all_waves = np.stack(
        [
            np.asarray(zg[str(g)][int(i)])
            for g, i in zip(
                features["waveform_group"],
                features["waveform_row_index"],
                strict=True,
            )
        ]
    )
    # audit runs on a deterministic sample of 400 events (performance); the
    # engine function is identical to the one validated by tests.
    sample_idx = np.linspace(0, len(all_waves) - 1, 400).astype(int)
    audit_waves = all_waves[sample_idx]
    audits = [
        gate_stability_audit(gate_a, waves=audit_waves),
        gate_stability_audit(gate_b, waves=audit_waves),
    ]
    print("gate stability audit:", json.dumps(audits, indent=1))

    # --- representative waveform plots with gate boundaries ---
    plots_dir = ROOT / "analysis/CELL_001/EXP_001/gate_analysis/plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_payloads: dict[str, bytes] = {}
    n = len(features)
    for tag, pos in [
        ("first", 0),
        ("p25", n // 4),
        ("p50", n // 2),
        ("p75", 3 * n // 4),
        ("last", n - 1),
    ]:
        group = features["waveform_group"].iloc[pos]
        idx = features["waveform_row_index"].iloc[pos]
        wave = np.asarray(zg[str(group)][int(idx)])
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(wave, lw=0.6)
        for gate, color in ((gate_a, "tab:red"), (gate_b, "tab:blue")):
            ax.axvspan(gate.start_sample, gate.end_sample, alpha=0.15, color=color)
            ax.axvline(gate.start_sample, color=color, ls="--", lw=0.8)
            ax.axvline(gate.end_sample, color=color, ls="--", lw=0.8)
        ax.set_title(
            f"{tag} event {features['measurement_event_id'].iloc[pos]} — "
            f"Gate A [0,200] / Gate B [800,980] @50MHz"
        )
        ax.set_xlabel("sample index")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plot_payloads[f"rep_{tag}"] = buf.getvalue()
        fig.savefig(plots_dir / f"representative_{tag}.png", dpi=120)
        plt.close(fig)
    print(f"plots: {plots_dir}/representative_*.png")

    # --- persist slice-gate payload (ML-ready from scope perspective) ---
    gated = gated.drop(columns=["full_peak"], errors="ignore")
    paths = write_gated_feature_payload(
        gated_features=gated,
        gate_specs=[gate_a, gate_b],
        tof_definitions=[tof_def],
        gate_selection_basis="SIGNAL_ONLY",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        output_root=ROOT,
        waveform_store_path=str(WAVEFORM_STORE),
    )
    print(f"gate_set: {paths['gate_set_id']}")

    # --- recommended report artifacts (artifacts/ contract) ---
    artifacts_paths = write_gate_report_artifacts(
        report={
            "gate_set_id": paths["gate_set_id"],
            "gates": [g.model_dump(mode="json") for g in (gate_a, gate_b)],
            "tof_definitions": [tof_def.model_dump(mode="json")],
            "gate_stability_audit": audits,
            "tof_mode": "BETWEEN_GATES (diagnostic delay; NOT promoted)",
            "plots_note": "representative_waveforms/ holds the png files",
        },
        plots=plot_payloads,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        gate_set_id=paths["gate_set_id"],
        output_root=ROOT.parent,  # data/artifacts (output contract)
    )
    print(f"report artifacts: {artifacts_paths['report_json']}")

    # --- gated feature-label analysis (event grain + delay locator) ---
    delay_loc = delay_locator(gate_a.gate_id, gate_b.gate_id)
    analysis = gated.pivot_table(
        index="measurement_event_id",
        columns="gate_id",
        values=[
            "amplitude_a_u",
            "waveform_rms_a_u",
            "waveform_p2p_a_u",
            "waveform_energy_sum_sq_a_u2",
        ],
    )
    analysis.columns = [f"{feat}@{gid}" for feat, gid in analysis.columns]
    analysis = analysis.reset_index()
    analysis[delay_loc] = (
        delays.set_index("measurement_event_id")["delay_us"]
        .reindex(analysis["measurement_event_id"])
        .to_numpy()
    )
    event_labels = pd.read_parquet(LABEL_SET_PATH)
    cycle_labels = pd.read_parquet(CYCLE_LABELS_PATH)
    analysis_full = build_gated_feature_label_analysis(
        gated_features=analysis,
        event_labels=event_labels,
        cycle_labels=cycle_labels,
        event_grain=True,
    )
    d = delays["delay_us"]
    analysis_paths = write_gated_analysis_payload(
        analysis_df=analysis_full,
        manifest={
            "gate_set_id": paths["gate_set_id"],
            "gate_selection_basis": "SIGNAL_ONLY",
            "row_count": len(analysis_full),
            "columns": list(analysis_full.columns),
            "join": "measurement_event_id exact join",
            "tof_definitions": [t.model_dump(mode="json") for t in [tof_def]],
        },
        report={
            "gate_stability_audit": audits,
            "delay_diagnostic_us": {
                "median": float(d.median()),
                "p5": float(d.quantile(0.05)),
                "p95": float(d.quantile(0.95)),
                "note": "NOT tof_us; physical interpretation unconfirmed",
            },
            "per_gate_stats": {
                g.gate_name: {
                    "amplitude_median": float(
                        gated[gated["gate_id"] == g.gate_id]["amplitude_a_u"].median()
                    ),
                    "rms_median": float(
                        gated[gated["gate_id"] == g.gate_id]["waveform_rms_a_u"].median()
                    ),
                    "p2p_median": float(
                        gated[gated["gate_id"] == g.gate_id]["waveform_p2p_a_u"].median()
                    ),
                }
                for g in (gate_a, gate_b)
            },
        },
        battery_id="CELL_001",
        experiment_id="EXP_001",
        gate_set_id=paths["gate_set_id"],
        output_root=ROOT,
    )
    print(
        f"analysis: {analysis_paths['analysis_parquet']} ({len(analysis_full)} rows, {len(analysis_full.columns)} cols)"
    )

    # summary stats per gate (reported, not saved as new features)
    for gate in (gate_a, gate_b):
        sub = gated[gated["gate_id"] == gate.gate_id]
        print(
            f"{gate.gate_name}: amplitude median={sub['amplitude_a_u'].median():.0f} "
            f"rms median={sub['waveform_rms_a_u'].median():.0f} "
            f"p2p median={sub['waveform_p2p_a_u'].median():.0f}"
        )
    print(
        f"between-gate delay (diagnostic): median={d.median():.2f}us p5={d.quantile(0.05):.2f} p95={d.quantile(0.95):.2f}"
    )

    # --- exploratory frame-gate demo (5 events, adaptive, not_ml_ready) ---
    frame_specs: list[GateSpec] = []
    frame_rows: list[dict] = []
    for tag, pos in [
        ("first", 0),
        ("p25", n // 4),
        ("p50", n // 2),
        ("p75", 3 * n // 4),
        ("last", n - 1),
    ]:
        group = features["waveform_group"].iloc[pos]
        idx = features["waveform_row_index"].iloc[pos]
        wave = np.asarray(zg[str(group)][int(idx)])
        region = np.abs(wave[600:1100])
        peak_pos = 600 + int(np.argmax(region))
        fg = GateSpec(
            gate_name=f"adaptive_secondary_{tag}_{features['measurement_event_id'].iloc[pos]}",
            start_sample=max(0, peak_pos - 50),
            end_sample=min(1250, peak_pos + 50),
            scope=GateScope.EXPLORATORY_FRAME_GATE,
            waveform_length=1250,
            semantic_role="ANALYSIS_WINDOW",
            source="per-frame adaptive secondary-peak +/-50 (manual demo)",
            created_by="BRW-018 demo",
        )
        frame_specs.append(fg)
        feats = extract_gated_features(wave, fg)
        feats["measurement_event_id"] = features["measurement_event_id"].iloc[pos]
        frame_rows.append(feats)
    frame_paths = write_gated_feature_payload(
        gated_features=pd.DataFrame(frame_rows),
        gate_specs=frame_specs,
        tof_definitions=[],
        gate_selection_basis="SIGNAL_ONLY",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        output_root=ROOT,
        waveform_store_path=str(WAVEFORM_STORE),
    )
    print(f"frame-gate demo: {frame_paths['gate_set_id']} (not_ml_ready=true, 5 events)")

    # --- dataset integration: explicit gated locators ---
    feats_full = features.copy()
    for feat in ("amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"):
        a_col = gated_locator(feat, gate_a.gate_id)
        b_col = gated_locator(feat, gate_b.gate_id)
        feats_full[a_col] = (
            gated[gated["gate_id"] == gate_a.gate_id]
            .set_index("measurement_event_id")[feat]
            .reindex(features["measurement_event_id"])
            .to_numpy()
        )
        feats_full[b_col] = (
            gated[gated["gate_id"] == gate_b.gate_id]
            .set_index("measurement_event_id")[feat]
            .reindex(features["measurement_event_id"])
            .to_numpy()
        )
    feats_full[delay_loc] = (
        delays.set_index("measurement_event_id")["delay_us"]
        .reindex(features["measurement_event_id"])
        .to_numpy()
    )
    selected = [
        gated_locator("amplitude_a_u", gate_a.gate_id),
        gated_locator("waveform_rms_a_u", gate_a.gate_id),
        gated_locator("waveform_p2p_a_u", gate_b.gate_id),
        delay_loc,
    ]
    report, _df = build_soc_dataset(
        features=feats_full,
        event_labels=event_labels,
        cycle_labels=cycle_labels,
        config=DatasetConfig(),
        analysis_slice_id="AS::39b284730b2c801104f0e960",
        feature_set_id="FS::60649fd12c540267fe585914",
        label_set_id="LB::952cbd8458d8894f9506a0c5",
        parameter_set_id=PARAMETER_SET_ID,
        feature_set_path=FEATURES_PARQUET,
        label_set_path=LABEL_SET_PATH,
        selected_features=selected,
    )
    print(f"dataset (gated locators): {report.dataset_id} predictors={report.predictor_columns}")

    # --- input integrity after ---
    integrity_after = _integrity_snapshot()
    changed = [k for k in integrity_before if integrity_before[k] != integrity_after[k]]
    assert not changed, f"input artifacts changed: {changed}"
    print("input integrity: all protected artifacts unchanged")


if __name__ == "__main__":
    main()

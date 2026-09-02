"""BRW-021 real demo: exploratory + fold ML-safe + SOH guard, integrity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from battery_workbench.orchestrator.engine import PipelineOrchestrator

PROCESSED = Path("data/processed")
RAW = Path("data/raw")


def _digest(p: Path) -> str:
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    h = hashlib.sha256()
    for f in sorted(x for x in p.rglob("*") if x.is_file()):
        h.update(str(f.relative_to(p)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def main() -> None:
    engine = PipelineOrchestrator(
        raw_root=RAW, processed_root=PROCESSED, runs_root=PROCESSED.parent / "artifacts/runs"
    )
    gate_a = "GATE::0c443fd8bb117e732a16"
    gate_b = "GATE::81448c66af7d3c8d944d"
    reports: dict[str, dict] = {}

    # --- 1. SOC exploratory (full data) ---
    plan_e = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["FEATURE_LABEL_ANALYSIS", "FEATURE_ANALYSIS"],
        target="soc_reference_percent",
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        feature_analysis={
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "candidate_features": [
                "amplitude_a_u",
                "waveform_rms_a_u",
                "waveform_p2p_a_u",
                "envelope_peak_a_u",
                "waveform_energy_sum_sq_a_u2",
                "tof_us",
                f"amplitude_a_u@{gate_a}",
                f"amplitude_a_u@{gate_b}",
            ],
            "methods": ["descriptive", "pearson", "spearman"],
        },
    )
    run_e = engine.start_run(plan_e)
    fa_e = next(n for n in run_e["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    m_e = json.loads(Path(fa_e["outputs"][0]["manifest_path"]).read_text())
    report_json = Path(
        PROCESSED.parent
        / "artifacts/CELL_001/EXP_001/feature_analysis"
        / m_e["analysis_id"]
        / "feature_analysis_report.json"
    )
    full_report = json.loads(report_json.read_text())
    print("=== SOC EXPLORATORY ===")
    print(
        "analysis_id:",
        m_e["analysis_id"],
        "| mode:",
        m_e["analysis_mode"],
        "| fold:",
        m_e["fold_index"],
    )
    top = sorted(
        (r for r in full_report["redundancy"]), key=lambda r: -(r["max_abs_association"] or 0)
    )[:3]
    print(
        "top redundancy:",
        [(r["feature_a"], r["feature_b"], round(r["max_abs_association"], 3)) for r in top],
    )
    reports["exploratory"] = {
        "analysis_id": m_e["analysis_id"],
        "mode": m_e["analysis_mode"],
        "availability": m_e["resolved_availability"],
        "redundancy_top": top,
    }

    # --- 2. SOC ML-safe fold1 / fold2 ---
    for fold in (1, 2):
        plan_f = engine.plan_run(
            profile="SCIENTIFIC_ANALYSIS",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=False,
            fold_index=fold,
            stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS"],
            target="soc_reference_percent",
            features={"selected_features": ["amplitude_a_u"]},
            analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
            parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
            split={
                "strategy": "LEAVE_ONE_GROUP_OUT",
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
            },
            feature_analysis={
                "analysis_mode": "TRAIN_ONLY_ML_SAFE",
                "candidate_features": [
                    "amplitude_a_u",
                    "waveform_rms_a_u",
                    "waveform_p2p_a_u",
                    "envelope_peak_a_u",
                ],
                "methods": ["descriptive", "spearman"],
                "selection": {
                    "requested": True,
                    "mode": "TRAIN_ONLY_RULE_BASED",
                    "policy": {"min_abs_spearman": 0.15, "max_missing_fraction": 0.05},
                },
            },
        )
        run_f = engine.start_run(plan_f)
        fa_f = next(n for n in run_f["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
        sel_manifests = sorted(
            (PROCESSED / "feature_analysis/CELL_001/EXP_001").glob("*/AN::*/feature_selection.json")
        )
        sel = None
        for p in sel_manifests:
            payload = json.loads(p.read_text())
            if payload["fold_index"] == fold:
                sel = payload
        assert sel is not None
        m_f = {
            "analysis_id": sel["analysis_id"],
            "split_id": sel["split_id"],
            "fold_index": sel["fold_index"],
            "held_out_target_accessed": False,
        }
        print(f"fold{fold} node state:", fa_f["state"])
        print(f"=== SOC ML-SAFE fold{fold} ===")
        print(
            "analysis_id:",
            m_f["analysis_id"],
            "| split:",
            m_f["split_id"][:20],
            "| fold:",
            m_f["fold_index"],
        )
        print("selected:", sel["selected_features"])
        print("held_out_target_accessed:", m_f["held_out_target_accessed"])
        reports[f"ml_safe_fold{fold}"] = {
            "analysis_id": m_f["analysis_id"],
            "split_id": m_f["split_id"],
            "fold_index": m_f["fold_index"],
            "selected_features": sel["selected_features"],
            "held_out_target_accessed": m_f["held_out_target_accessed"],
        }

    # --- 3. SOH: exploratory allowed, ML-safe BLOCKED ---
    plan_soh = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["FEATURE_LABEL_ANALYSIS", "FEATURE_ANALYSIS"],
        target="soh_capacity_reference_percent",
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        feature_analysis={
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "candidate_features": ["amplitude_a_u"],
            "methods": ["descriptive", "spearman"],
        },
    )
    run_soh = engine.start_run(plan_soh)
    fa_soh = next(n for n in run_soh["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    m_soh = json.loads(Path(fa_soh["outputs"][0]["manifest_path"]).read_text())
    print("=== SOH EXPLORATORY ===")
    print("analysis_id:", m_soh["analysis_id"], "| mode:", m_soh["analysis_mode"])

    plan_soh_ml = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        fold_index=1,
        stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS"],
        target="soh_capacity_reference_percent",
        features={"selected_features": ["amplitude_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        split={
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
        feature_analysis={
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "candidate_features": ["amplitude_a_u"],
            "methods": ["spearman"],
        },
    )
    run_soh_ml = engine.start_run(plan_soh_ml)
    fa_soh_ml = next(n for n in run_soh_ml["nodes"] if n["node_id"] == "FEATURE_ANALYSIS")
    print("=== SOH ML-SAFE ===")
    print("status:", fa_soh_ml["state"], "|", fa_soh_ml["reason"][:70])
    reports["soh"] = {
        "exploratory_analysis_id": m_soh["analysis_id"],
        "ml_safe_state": fa_soh_ml["state"],
        "ml_safe_reason": fa_soh_ml["reason"][:80],
    }

    out = Path("data/artifacts/CELL_001/EXP_001/feature_analysis/BRW-021_demo_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    print(f"summary: {out}")


if __name__ == "__main__":
    main()

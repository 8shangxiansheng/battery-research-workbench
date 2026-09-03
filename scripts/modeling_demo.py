"""BRW-022 real demo: fold1/fold2 selections confirmed -> 5 baselines x 2 folds."""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.orchestrator.engine import PipelineOrchestrator

PROCESSED = Path("data/processed")
RAW = Path("data/raw")


def main() -> None:
    engine = PipelineOrchestrator(
        raw_root=RAW, processed_root=PROCESSED, runs_root=PROCESSED.parent / "artifacts/runs"
    )
    reports: dict[str, dict] = {}

    for fold in (1, 2):
        plan = engine.plan_run(
            profile="SCIENTIFIC_ANALYSIS",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=False,
            fold_index=fold,
            stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING"],
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
            modeling={
                "strategies": [
                    "DUMMY_MEAN",
                    "LINEAR_REGRESSION",
                    "RIDGE",
                    "RANDOM_FOREST",
                    "GRADIENT_BOOSTING",
                ],
                "random_state": 42,
            },
        )
        run = engine.start_run(plan)
        actions = engine.list_user_actions(run["run_id"])
        sel_actions = [a for a in actions if a["action_type"] == "CONFIRM_FEATURE_SELECTION"]
        if sel_actions:
            sel_id = sel_actions[0]["required_fields"][0]["value"]
            run = engine.resume_run(
                run["run_id"],
                user_inputs={
                    "selection_id": sel_id,
                    "feature_analysis": {"selection": {"confirmed": True}},
                },
                action_id=sel_actions[0]["action_id"],
            )
        states = {n["node_id"]: n["state"] for n in run["nodes"]}
        print(f"=== fold{fold} === states: {states}")

        # read comparison rows for this fold (parquet = per model per fold)
        import pandas as pd

        comp_df = pd.read_parquet(
            PROCESSED / "models/CELL_001/EXP_001/DS::6a3142e5186fc684964ff09e/"
            "SPLIT::062cf007d21578a11ab2d728/model_comparison.parquet"
        )
        fold_rows = comp_df[comp_df["fold_index"] == fold].to_dict("records")
        for row in sorted(fold_rows, key=lambda r: r["MAE"]):
            print(
                f"  {row['strategy']:<18} MAE={row['MAE']:.3f} RMSE={row['RMSE']:.3f} "
                f"R2={row['R2']:.3f} OOB={row['out_of_bounds_count']} "
                f"features={row['selected_features']}"
            )
        reports[f"fold{fold}"] = fold_rows

    out = Path("data/artifacts/CELL_001/EXP_001/models/BRW-022_demo_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    print(f"summary: {out}")


if __name__ == "__main__":
    main()

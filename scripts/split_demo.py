"""BRW-020 real demo: SOC LEAVE_ONE_CYCLE_OUT materialization, SOH readiness
audit, orchestrator REUSE/WAITING demonstration. Read-only toward datasets."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from battery_workbench.orchestrator.engine import PipelineOrchestrator
from battery_workbench.splits.engine import build_assignments, leakage_audit
from battery_workbench.splits.persistence import write_split_payload
from battery_workbench.splits.readiness import evaluate_readiness
from battery_workbench.splits.schemas import SplitSpec

PROCESSED = Path("data/processed")
RAW = Path("data/raw")


def main() -> None:
    reports: dict[str, dict] = {}

    # --- 1. real group counts (from the datasets themselves) ---
    ds_soc = Path("data/processed/datasets/CELL_001/EXP_001/SOC/DS::6a3142e5186fc684964ff09e")
    ds_soh = Path(
        "data/processed/datasets/CELL_001/EXP_001/SOH_CAPACITY/DS::c10c43b1890949aff0e94663"
    )
    soc = pd.read_parquet(ds_soc / "dataset.parquet")
    soh = pd.read_parquet(ds_soh / "dataset.parquet")
    group_facts = {
        "battery_groups": int(soc["battery_group_id"].nunique()),
        "experiment_groups": int(soc["experiment_group_id"].nunique()),
        "cycle_groups": int(soc["cycle_group_id"].nunique()),
        "label_groups": int(soc["label_group_id"].nunique()),
        "independent_soh_groups": int(soh["independent_soh_group_id"].nunique()),
        "cycle_group_counts": {
            str(k): int(v) for k, v in soc["cycle_group_id"].value_counts().items()
        },
    }
    print("group facts:", json.dumps(group_facts, indent=1))
    reports["group_facts"] = group_facts

    # --- 2. SOC: LEAVE_ONE_GROUP_OUT over cycle_group_id ---
    spec = SplitSpec(
        strategy="LEAVE_ONE_GROUP_OUT",
        split_unit="CYCLE",
        group_column="cycle_group_id",
        dataset_id="DS::6a3142e5186fc684964ff09e",
        purpose="SCIENTIFIC_EVALUATION",
    )
    assignments = build_assignments(spec, soc)
    group_counts = {str(k): int(v) for k, v in soc.groupby("cycle_group_id").size().items()}
    write_split_payload(
        spec=spec,
        assignments=assignments,
        dataset_id="DS::6a3142e5186fc684964ff09e",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOC",
        output_root=PROCESSED,
        group_counts=group_counts,
        dataset_status="READY_WITH_LIMITATIONS",
    )
    fold_summary = (
        assignments.groupby("fold")
        .apply(
            lambda g: {
                "train_groups": sorted(g[g["role"] == "TRAIN"]["cycle_group_id"].unique()),
                "held_out_groups": sorted(g[g["role"] == "HELD_OUT"]["cycle_group_id"].unique()),
                "rows": len(g),
            },
            include_groups=False,
        )
        .to_dict()
    )
    print("SOC split:", spec.split_id, json.dumps(fold_summary, indent=1))
    reports["soc_split"] = {
        "split_id": spec.split_id,
        "strategy": "LEAVE_ONE_GROUP_OUT",
        "group_column": "cycle_group_id",
        "folds": fold_summary,
        "readiness": "READY_FOR_LIMITED_EVALUATION",
        "evaluation_scope": "WITHIN_BATTERY_CROSS_CYCLE",
        "leakage_audit": leakage_audit(spec, assignments, soc),
    }

    # --- 3. SOH: readiness audit only (no misleading protocol) ---
    soh_readiness = evaluate_readiness(
        dataset_family="SOH_CAPACITY",
        independent_soh_states=int(soh["independent_soh_group_id"].nunique()),
        battery_count=1,
        cycle_group_count=2,
    )
    print("SOH readiness:", soh_readiness["status"])
    reports["soh_readiness"] = soh_readiness
    spec_soh = SplitSpec(
        strategy="TRAIN_ONLY",
        split_unit="CYCLE",
        group_column="cycle_group_id",
        dataset_id="DS::c10c43b1890949aff0e94663",
        purpose="READINESS_AUDIT",
    )
    assignments_soh = build_assignments(spec_soh, soh)
    write_split_payload(
        spec=spec_soh,
        assignments=assignments_soh,
        dataset_id="DS::c10c43b1890949aff0e94663",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dataset_family="SOH_CAPACITY",
        output_root=PROCESSED,
        group_counts={str(k): int(v) for k, v in soh.groupby("cycle_group_id").size().items()},
        dataset_status="NOT_READY_FOR_MODEL_EVALUATION",
        independent_soh_states=2,
    )

    # --- 4. orchestrator: SPLIT reuse on second identical run ---
    engine = PipelineOrchestrator(
        raw_root=RAW, processed_root=PROCESSED, runs_root=PROCESSED.parent / "artifacts/runs"
    )
    plan = engine.plan_run(
        profile="BUILD_DATASET",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["DATASET", "SPLIT"],
        target="soc_reference_percent",
        features={"selected_features": ["amplitude_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        split={
            "strategy": "LEAVE_ONE_GROUP_OUT",
            "split_unit": "CYCLE",
            "group_column": "cycle_group_id",
        },
    )
    run1 = engine.start_run(plan)
    s1 = next(n for n in run1["nodes"] if n["node_id"] == "SPLIT")
    run2 = engine.start_run(plan)
    s2 = next(n for n in run2["nodes"] if n["node_id"] == "SPLIT")
    print(f"orchestrator SPLIT: run1={s1['state']} run2={s2['state']}")
    reports["orchestrator"] = {"run1_split": s1["state"], "run2_split": s2["state"]}
    assert s2["state"] == "REUSED"

    out = Path("data/artifacts/CELL_001/EXP_001/splits")
    out.mkdir(parents=True, exist_ok=True)
    out = out / "BRW-020_demo_summary.json"
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    print(f"summary: {out}")


if __name__ == "__main__":
    main()

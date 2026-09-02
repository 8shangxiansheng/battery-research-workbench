"""BRW-019 real E2E demo: Plan A/B/C on CELL_001/EXP_001 + synthetic waiting demo.

Plan A  INGEST_TO_MEASUREMENT_EVENTS — expected: mostly REUSE.
Plan B  SCIENTIFIC_ANALYSIS           — reuse/build slice/features/labels/params.
Plan C  BUILD_DATASET (SOC)           — AVAILABLE safe features only.
Synthetic demo: require_sampling_rate on a synthetic plan (user action +
resume in an isolated sandbox run manifest; no real parameter pollution).
"""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.orchestrator.engine import PipelineOrchestrator

REPO = Path(".")
RAW = REPO / "data/raw"
PROCESSED = REPO / "data/processed"
RUNS = REPO / "data/artifacts/runs"


def _report(title: str, run: dict) -> dict:
    states = [n["state"] for n in run["nodes"]]
    summary = {
        "plan": title,
        "run_id": run["run_id"],
        "status": run["status"],
        "REUSED": states.count("REUSED"),
        "EXECUTED": states.count("SUCCEEDED"),
        "BLOCKED": states.count("BLOCKED"),
        "USER_ACTION": len(run["user_actions"]),
        "final_artifact_ids": [
            a["artifact_id"] for a in run["final_artifacts"] if a["artifact_id"]
        ],
    }
    print(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    engine = PipelineOrchestrator(raw_root=RAW, processed_root=PROCESSED, runs_root=RUNS)
    reports = []

    # --- Plan A ---
    plan_a = engine.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
    )
    reports.append(_report("A: INGEST_TO_MEASUREMENT_EVENTS", engine.start_run(plan_a)))

    # --- Plan B ---
    plan_b = engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
    )
    reports.append(_report("B: SCIENTIFIC_ANALYSIS", engine.start_run(plan_b)))

    # --- Plan C ---
    plan_c = engine.plan_run(
        profile="BUILD_DATASET",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        target="soc_reference_percent",
        features={"selected_features": ["amplitude_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960"},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
    )
    reports.append(_report("C: BUILD_DATASET (SOC)", engine.start_run(plan_c)))

    # --- synthetic WAITING_FOR_USER + resume (sandbox, no real parameter pollution) ---
    import shutil
    import tempfile

    sandbox = Path(tempfile.mkdtemp()) / "processed"
    for rel in (
        "multimodal/CELL_001/EXP_001",
        "synchronization/CELL_001/EXP_001",
        "electrical/CELL_001/EXP_001",
        "labels/CELL_001/EXP_001",
        "ultrasound/CELL_001/EXP_001",
    ):
        (sandbox / rel).mkdir(parents=True)
        for f in (PROCESSED / rel).iterdir():
            if f.suffix in {".parquet", ".json"}:
                shutil.copy(f, sandbox / rel / f.name)
    sandbox_engine = PipelineOrchestrator(raw_root=RAW, processed_root=sandbox, runs_root=RUNS)
    plan_s = sandbox_engine.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=False,
        stages=["MEASUREMENT_EVENTS", "PARAMETER_SET"],
        parameters={"require_sampling_rate": True},
    )
    run_s = sandbox_engine.start_run(plan_s)
    print("synthetic run status:", run_s["status"])
    actions = sandbox_engine.list_user_actions(run_s["run_id"])
    assert run_s["status"] == "WAITING_FOR_USER" and actions, "expected user action"
    resumed = sandbox_engine.resume_run(
        run_s["run_id"],
        user_inputs={
            "ultrasound.sampling_rate_hz": {"value": 50.0, "unit": "MHz"},
            "ultrasound.trigger_sample_index": {"value": 0, "unit": "sample"},
        },
        action_id=actions[0]["action_id"],
    )
    states = {n["node_id"]: n["state"] for n in resumed["nodes"]}
    print("resumed status:", resumed["status"], "| PARAMETER_SET:", states["PARAMETER_SET"])
    reports.append(
        {
            "plan": "SYNTHETIC: WAITING_FOR_USER + resume (sandbox)",
            "status_before": run_s["status"],
            "status_after": resumed["status"],
            "param_set_after": next(
                a["artifact_id"]
                for a in resumed["final_artifacts"]
                if a["artifact_type"] == "PARAMETER_SET"
            ),
        }
    )

    out = RUNS / "BRW-019_demo_summary.json"
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    print(f"summary: {out}")


if __name__ == "__main__":
    main()

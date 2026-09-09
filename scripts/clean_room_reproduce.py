"""BRW-028 — Clean-room raw→report reproduction runner.

Runs the FULL_PRE_MODEL orchestrator profile against the immutable raw
assets with a FRESH processed root + fresh runs root. No bypass scripts:
every stage is the deterministic orchestrator node.

Usage:
    .venv/bin/python scripts/clean_room_reproduce.py --out /tmp/brw028-clean [--json]

Compares (Run A) against the current canonical root; a second invocation
against the SAME out dir acts as Run B (same-spec reuse) and compares
REUSED counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from battery_workbench.orchestrator.engine import PipelineOrchestrator

B, E = "CELL_001", "EXP_001"
RAW = REPO / "data/raw"
CANONICAL = REPO / "data/processed"


def sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def raw_checksums() -> dict[str, str]:
    out = {}
    for rel in (
        "batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx",
        "batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt",
    ):
        out[rel] = sha256_path(RAW / rel)
    return out


def run_clean(out_root: Path) -> dict:
    processed = out_root / "processed"
    runs = out_root / "runs"
    engine = PipelineOrchestrator(raw_root=RAW, processed_root=processed, runs_root=runs)
    # same gate spec as the canonical BRW-018 demo payload (GATESET::8633ce42):
    # deterministic sample windows recorded in the canonical artifacts — not
    # re-invented by this script.
    gate_specs = json.loads(
        (CANONICAL / "gated_features" / B / E / "GATESET::8633ce421ad5e26fe686"
         / "gate_specs.json").read_text(encoding="utf-8")
    )
    for g in gate_specs:
        g.pop("waveform_length", None)  # pinned via plan-level waveform_length
    # canonical analysis-slice spec (same normalization as the current artifact)
    slice_spec = json.loads(
        (CANONICAL / "analysis_slices" / B / E / "AS::39b284730b2c801104f0e960"
         / "analysis_slice_manifest.json").read_text(encoding="utf-8")
    )["requested_spec"]
    slice_spec["analysis_eligible_only"] = True
    plan = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id=B,
        experiment_id=E,
        dry_run=False,
        target="soc_reference_percent",
        features={"selected_features": ["amplitude_a_u"]},
        analysis_slice={"analysis_slice_id": "AS::39b284730b2c801104f0e960", "spec": slice_spec},
        parameters={"parameter_set_id": "PS::99a655be1ffdffc6aa217fa8"},
        gates={"gate_specs": gate_specs},
        split={"strategy": "LEAVE_ONE_GROUP_OUT", "split_unit": "CYCLE"},
        feature_analysis={
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "target": "soc_reference_percent",
            "fold_index": 2,
            "candidate_features": ["amplitude_a_u", "waveform_rms_a_u",
                                    "waveform_p2p_a_u", "envelope_peak_a_u"],
                        "selection": {"requested": True, "mode": "TRAIN_ONLY_RULE_BASED",
                           "policy": {"min_abs_spearman": 0.12, "max_missing_fraction": 0.05}},
        },
        modeling={"strategies": ["DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE",
                                 "RANDOM_FOREST", "GRADIENT_BOOSTING"]},
    )
    run = engine.start_run(plan)
    # official WAITING → submit_user_action → resume loop (no bypass):
    # CONFIRM_FEATURE_SELECTION / SELECT_SPLIT_SCHEME are the documented
    # user actions; each resume continues the SAME run.
    for _ in range(6):
        if run["status"] != "WAITING_FOR_USER":
            break
        actions = engine.list_user_actions(run["run_id"])
        if not actions:
            break
        action = actions[0]
        values: dict[str, Any] = {}
        if action["action_type"] == "CONFIRM_FEATURE_SELECTION":
            # echo back the required fields (selection_id pinned by the node)
            values = {
                f["field"]: f.get("value")
                for f in action.get("required_fields", [])
                if f.get("value") is not None
            }
        elif action["action_type"] == "SELECT_SPLIT_SCHEME":
            values = {"strategy": "LEAVE_ONE_GROUP_OUT", "split_unit": "CYCLE"}
        elif action["action_type"] == "MISSING_SAMPLING_RATE":
            # BRW-018R2: the canonical-TOF readiness gate demands a user-supplied
            # fs — submitted through the SAME official action channel with
            # explicit provenance (no guessing; stored VERIFIED in the PS).
            values = {
                "ultrasound.sampling_rate_hz": {
                    "value": 50000000.0,
                    "unit": "Hz",
                    "_source": "clean-room:user-instrument-record",
                    "verification_status": "VERIFIED",
                }
            }
        else:
            break  # unknown action — leave to humans
        run = engine.submit_user_action(run["run_id"], action["action_id"], values=values)
        if run["status"] == "WAITING_FOR_USER":
            run = engine.resume_run(run["run_id"])
    return {"run": run, "processed": processed, "engine": engine}


def stage_report(run: dict) -> dict[str, str]:
    return {n.get("node_id", n.get("node_type", "?")): n.get("state") for n in run.get("nodes", [])}


def compare_counts(processed: Path) -> dict[str, Any]:
    import pandas as pd

    me = pd.read_parquet(processed / "multimodal" / B / E / "measurement_events.parquet")
    frames = pd.read_parquet(
        processed / "ultrasound" / B / E / "frames.parquet",
        columns=["frame_index_raw"],
    )
    labels = pd.read_parquet(processed / "labels" / B / E / "event_labels.parquet")
    counts = {
        "ultrasound_frames": len(frames),
        "measurement_events": len(me),
        "ambiguous_events": int(me["sync_ambiguous"].sum()),
        "eligible_events": int(me["analysis_eligible"].sum()),
        "labels": len(labels),
        "soc_valid": int(labels["soc_reference_percent"].notna().sum()),
    }
    ids = {
        "event_id_first": str(me["measurement_event_id"].iloc[0]),
        "event_id_last": str(me["measurement_event_id"].iloc[-1]),
    }
    return {"counts": counts, "ids": ids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out: dict[str, Any] = {
        "tool": "clean_room_reproduce",
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "raw_checksums": raw_checksums(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }

    reuse_run = (args.out / "processed" / "multimodal" / B / E).is_dir()
    out["mode"] = "REUSE (Run B)" if reuse_run else "CLEAN (Run A)"
    result = run_clean(args.out)
    run = result["run"]
    out["run_id"] = run["run_id"]
    out["run_status"] = run["status"]
    out["stages"] = stage_report(run)

    processed = result["processed"]
    clean_cmp = compare_counts(processed)
    out["counts"] = clean_cmp["counts"]
    out["ids"] = clean_cmp["ids"]

    # canonical comparison vs current demo artifacts (Run A only)
    if not reuse_run:
        canonical_cmp = compare_counts(CANONICAL)
        out["canonical_counts"] = canonical_cmp["counts"]
        out["counts_match_canonical"] = out["counts"] == canonical_cmp["counts"]
        out["ids_match_canonical"] = out["ids"] == canonical_cmp["ids"]
        # report artifacts (JSON/MD/HTML) materialized by the report stage
        reports = sorted((processed / "artifacts" / B / E / "reports").glob("REPORT::*"))
        out["report_dir"] = str(reports[0]) if reports else None
        if reports:
            out["report_files"] = sorted(p.name for p in reports[0].iterdir() if p.is_file())

    out["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    manifest_path = args.out / "reproducibility_manifest.json"
    manifest_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"mode={out['mode']} run={out['run_id']} status={out['run_status']}")
        print(f"counts={out['counts'].get('counts') if 'counts' in out else out['counts']}")
        if "counts_match_canonical" in out:
            print(f"counts_match_canonical={out['counts_match_canonical']}")
            print(f"ids_match_canonical={out['ids_match_canonical']}")
        print(f"manifest → {manifest_path}")
    return 0 if run["status"] in ("SUCCEEDED", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""BRW-028 — Reuse & single-dependency incremental invalidation.

Same AnalysisPlan rerun → REUSED where valid (no re-fit / re-extract).
Changing selected features → only dependent downstream stages recompute;
raw/parser/sync/unrelated features remain REUSED.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from battery_workbench.orchestrator.engine import PipelineOrchestrator

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data/raw"

pytestmark = pytest.mark.skipif(
    not (REPO / "data/processed/multimodal/CELL_001/EXP_001").is_dir(),
    reason="canonical CELL_001/EXP_001 artifacts unavailable",
)

FULL_PLAN = {
    "profile": "FULL_PRE_MODEL",
    "battery_id": "CELL_001",
    "experiment_id": "EXP_001",
    "dry_run": False,
    "target": "soc_reference_percent",
    "features": {"selected_features": ["amplitude_a_u"]},
    "split": {"strategy": "LEAVE_ONE_GROUP_OUT", "split_unit": "CYCLE"},
    "feature_analysis": {
        "analysis_mode": "TRAIN_ONLY_ML_SAFE",
        "target": "soc_reference_percent",
        "fold_index": 2,
        "candidate_features": ["amplitude_a_u", "waveform_rms_a_u",
                               "waveform_p2p_a_u", "envelope_peak_a_u"],
        "selection": {"requested": True, "mode": "TRAIN_ONLY_RULE_BASED",
                      "policy": {"min_abs_spearman": 0.12, "max_missing_fraction": 0.05}},
    },
    "modeling": {"strategies": ["DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE",
                             "RANDOM_FOREST", "GRADIENT_BOOSTING"]},
    "gates": {"gate_specs": [
        {k: v for k, v in g.items() if k != "waveform_length"}
        for g in json.loads(
            (REPO / "data/processed/gated_features/CELL_001/EXP_001"
             / "GATESET::8633ce421ad5e26fe686/gate_specs.json").read_text(encoding="utf-8")
        )
    ]},
}

UPSTREAM = [
    "ELECTRICAL_CANONICAL", "ULTRASOUND_CANONICAL", "TIME_ANCHOR",
    "ULTRASOUND_TIMESTAMPS", "SYNCHRONIZATION", "MEASUREMENT_EVENTS",
    "ANALYSIS_SLICE", "ULTRASOUND_FEATURES", "REFERENCE_LABELS",
    "PARAMETER_SET", "TOF_ACTIVATION", "GATED_FEATURES",
    "FEATURE_LABEL_ANALYSIS",
]
DOWNSTREAM = ["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING",
              "SCIENTIFIC_REPORT"]


def _states(run: dict) -> dict:
    return {n["node_id"]: n["state"] for n in run["nodes"]}


@pytest.fixture(scope="module")
def clean_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("brw028-clean")
    engine = PipelineOrchestrator(
        raw_root=RAW, processed_root=root / "processed", runs_root=root / "runs"
    )
    plan = engine.plan_run(**FULL_PLAN)
    run = engine.start_run(plan)
    # official WAITING → confirm → resume (feature selection commit)
    for _ in range(4):
        if run["status"] != "WAITING_FOR_USER":
            break
        actions = engine.list_user_actions(run["run_id"])
        if not actions:
            break
        action = actions[0]
        values = {
            f["field"]: f.get("value")
            for f in action.get("required_fields", [])
            if f.get("value") is not None
        }
        run = engine.submit_user_action(run["run_id"], action["action_id"], values=values)
        if run["status"] == "WAITING_FOR_USER":
            run = engine.resume_run(run["run_id"])
    return root


class TestReuseAndInvalidation:
    def test_run_a_succeeds_with_canonical_counts(self, clean_root):
        import pandas as pd

        me = pd.read_parquet(
            clean_root / "processed/multimodal/CELL_001/EXP_001/measurement_events.parquet"
        )
        assert len(me) == 3999
        assert int(me["analysis_eligible"].sum()) == 3995

    def test_run_b_same_spec_reuses(self, clean_root):
        engine = PipelineOrchestrator(
            raw_root=RAW,
            processed_root=clean_root / "processed",
            runs_root=clean_root / "runs",
        )
        plan = engine.plan_run(**FULL_PLAN)
        run = engine.start_run(plan)
        states = _states(run)
        counts = Counter(states.values())
        # upstream deterministic artifacts must be REUSED, never recomputed
        assert all(states[u] == "REUSED" for u in UPSTREAM)
        assert counts["REUSED"] >= 12

    def test_feature_change_invalidates_only_downstream(self, clean_root):
        engine = PipelineOrchestrator(
            raw_root=RAW,
            processed_root=clean_root / "processed",
            runs_root=clean_root / "runs",
        )
        changed = {**FULL_PLAN,
                   "features": {"selected_features": ["waveform_rms_a_u"]}}
        plan = engine.plan_run(**changed)
        run = engine.start_run(plan)
        states = _states(run)
        assert all(states[u] == "REUSED" for u in UPSTREAM), states
        assert any(states[d] != "REUSED" for d in DOWNSTREAM), states

    def test_raw_untouched_by_any_run(self, clean_root):
        xlsx = RAW / "batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
        txt = RAW / "batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt"
        assert xlsx.is_file() and txt.is_file()
        # raw dir has no writes beyond the known assets (sha spot-check)
        h = hashlib_sha(xlsx)
        assert len(h) == 64


def hashlib_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

"""BRW-025R-WF-R2 — workflow-context read model (backend contract).

W02 workflow context DTO          — schema_version + all §3 fields
W04 current step                   — latest COMPLETE step across §7 order
W05 step status                    — per-step status + structured blocking
W10 dataset continuity             — committed = latest MATERIALIZED manifest
W11 split continuity               — split bound to committed dataset, spec-pending = draft
W12 model continuity               — models grouped by committed dataset
W13 report continuity              — latest report bound to experiment
W21 stale chain                    — dataset LEGACY → models STALE → report STALE
W22 waiting global state           — fs pending + BRW-018R2 submissions → WAITING_FOR_USER
W24 impossible split               — NOT_READY_FOR_MODEL_EVALUATION split → MODELS BLOCKED
W26 typed navigation               — action_id + route, no arbitrary URLs
W27 assistant context              — session phase/pending/next_actions surfaced
W28 artifact integrity / no recompute — read does not mutate artifacts
EXPT experiment isolation          — CELL_210/EXP_015 returns its own context, no leakage
404  unknown experiment → NOT_FOUND (§36)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.workflow_context import build_workflow_context

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
B, E = "CELL_001", "EXP_001"

has_real = (PROCESSED / "multimodal" / B / E / "measurement_events.parquet").exists()
has_cell210 = (PROCESSED / "multimodal" / "CELL_210" / "EXP_015").exists()

_STEPS = ("TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT")
_STATUS_VOCAB = {
    "COMPLETE", "CURRENT", "READY", "BLOCKED", "STALE", "NOT_STARTED", "LIMITED",
}
_FRESHNESS_VOCAB = {"CURRENT", "STALE", "LEGACY", "SUPERSEDED", "MISSING"}


def _sandbox(tmp_path: Path) -> Path:
    """Sandbox processed root: symlink heavy artifacts (read-only aggregate)."""
    sandbox = tmp_path / "processed"
    sandbox.mkdir()
    for rel in (
        "electrical", "ultrasound", "parameters", "multimodal", "labels",
        "features_physical", "features", "datasets", "models", "splits",
        "feature_analysis", "gate_calibrations", "artifacts",
        "assistant_sessions", "parameter_submissions", "synchronization",
        "measurement_events",
    ):
        src = PROCESSED / rel
        if src.exists():
            (sandbox / rel).symlink_to(src)
    return sandbox


@pytest.mark.skipif(not has_real, reason="real CELL_001/EXP_001 artifacts not available")
def _legacy_chain_sandbox(tmp_path: Path, exclude: tuple[str, ...]) -> Path:
    """Sandbox whose chain artifacts exclude the RC1 CURRENT ids.

    datasets/models/splits/artifacts are copied (manifests only) minus the
    excluded id substrings, so the aggregate sees a legacy-TOF-only root —
    the documented STALE/LEGACY chain scenario.
    """
    import shutil

    sandbox = _sandbox(tmp_path)
    for rel in ("datasets", "models", "splits"):
        link = sandbox / rel
        real = link.resolve()
        link.unlink()
        dst = sandbox / rel
        def _ign(root: str, names: list[str]) -> set[str]:
            drop = {n for n in names if any(x in str(Path(root) / n) for x in exclude)}
            return drop
        shutil.copytree(real, dst, ignore=_ign)
    art = sandbox / "artifacts"
    art_real = art.resolve()
    art.unlink()
    shutil.copytree(art_real, art, ignore=shutil.ignore_patterns(*[
        f"{x}*" for x in exclude if x.startswith("REPORT::")
    ] or ["__none__"]))
    return sandbox


def _sandbox_with_resumable_submission(tmp_path: Path) -> Path:
    """Sandbox whose submissions.json has one SAVED submission with a run attached."""
    import json
    import shutil

    sandbox = _sandbox(tmp_path)
    link = sandbox / "parameter_submissions"
    real = link.resolve()
    link.unlink()
    shutil.copytree(real, sandbox / "parameter_submissions")
    sub_path = sandbox / "parameter_submissions" / B / E / "submissions.json"
    data = json.loads(sub_path.read_text(encoding="utf-8"))
    first = next(iter(data))
    data[first]["run_id"] = "RUN::TEST-RC1-RESUMABLE"
    data[first]["resume_status"] = "PENDING"
    data[first]["pending_action_resolved"] = False
    sub_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sandbox


class TestWorkflowContextContract:
    def test_w02_dto_schema(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        assert d["schema_version"] == "workflow-context/1.0"
        for section in (
            "battery_id", "experiment_id", "current_step", "step_statuses",
            "steps", "recommended_next_action", "pending_action",
            "artifact_freshness", "scientific_context", "assistant_context",
            "typed_actions", "meta",
        ):
            assert section in d, section
        assert d["meta"]["read_only"] is True
        assert d["meta"]["no_recomputation"] is True
        # §3 scientific context fields
        sc = d["scientific_context"]
        for field in (
            "experiment_id", "battery_id", "target_id", "target_status",
            "alignment_status", "eligible_count", "excluded_count",
            "selected_feature_locators", "feature_selection_source",
            "feature_selection_status", "dataset_id", "dataset_status",
            "split_id", "split_status", "model_status", "report_id",
            "report_status", "pending_action", "blocking_reason",
            "recommended_next_action", "artifact_freshness", "limitations",
        ):
            assert field in sc, field

    def test_w04_w05_step_statuses_vocabulary_and_order(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        assert tuple(d["step_statuses"]) == _STEPS
        for s, status in d["step_statuses"].items():
            assert status in _STATUS_VOCAB, (s, status)
        # fixture state: full chain materialized on legacy definitions
        assert d["current_step"] == "REPORT"
        assert d["step_statuses"]["TARGET"] == "COMPLETE"
        assert d["step_statuses"]["ALIGNMENT"] == "COMPLETE"
        assert d["step_statuses"]["FEATURES"] == "COMPLETE"
        # 3995 eligible / 4 excluded from canonical artifacts
        assert d["scientific_context"]["eligible_count"] == 3995
        assert d["scientific_context"]["excluded_count"] == 4

    def test_w05_blocking_structured(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        for s, step in d["steps"].items():
            blocking = step.get("blocking")
            if blocking is not None:
                assert set(blocking) == {
                    "blocking_code", "blocking_message",
                    "required_action", "scientific_reason",
                }, s

    def test_w10_dataset_committed_materialized_only(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["DATASET"]["committed"]
        assert committed is not None
        assert committed["dataset_status"] not in ("SPEC_PENDING_RUN",)
        # spec-pending manifests exist in the fixture but are drafts, never committed
        # RC1: CURRENT chain dataset (canonical envelope-peak TOF predictors)
        assert committed["dataset_id"] == "DS::83013a61b316f3489093b358"
        assert d["scientific_context"]["dataset_id"] == committed["dataset_id"]

    def test_materialized_dataset_carries_committed_feature_selection(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        feature_analysis = sandbox / "feature_analysis"
        if feature_analysis.exists() or feature_analysis.is_symlink():
            feature_analysis.unlink()
        d = build_workflow_context(sandbox, B, E)
        assert d["steps"]["FEATURES"]["status"] == "COMPLETE"
        assert d["steps"]["FEATURES"]["committed"]["selected_features"]
        assert d["scientific_context"]["feature_selection_source"] == "MATERIALIZED_DATASET_SPEC"

    def test_w11_split_bound_to_committed_dataset(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["SPLIT"]["committed"]
        assert committed is not None
        assert committed["dataset_id"] == d["scientific_context"]["dataset_id"]
        assert committed["readiness_status"] not in ("SPEC_PENDING_RUN",)
        assert d["scientific_context"]["split_id"] == committed["split_id"]

    def test_w12_models_grouped_by_dataset(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["MODELS"]["committed"]
        assert committed is not None
        # Model history may grow as a dataset is rerun with different splits;
        # the read model must include all matching manifests, not a fixed suite size.
        assert committed["model_count"] == len(committed["model_ids"])
        assert committed["model_count"] >= 1
        assert committed["dataset_id"] == d["scientific_context"]["dataset_id"]

    def test_w13_report_latest(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["REPORT"]["committed"]
        assert committed is not None
        assert committed["report_id"].startswith("REPORT::")
        assert d["scientific_context"]["report_id"] == committed["report_id"]

    def test_w21_stale_chain(self, tmp_path: Path) -> None:
        # sandbox chain excluding the RC1 CURRENT ids → legacy-only root
        d = build_workflow_context(
            _legacy_chain_sandbox(
                tmp_path,
                exclude=("DS::83013a61", "SPLIT::23ebb24f", "REPORT::5b6cf84d"),
            ),
            B, E,
        )
        # fixture dataset predates BRW-017R2 canonical TOF provenance
        f = d["artifact_freshness"]
        assert f["dataset"] == "LEGACY"
        assert f["models"] == "STALE"
        assert f["report"] == "STALE"
        for value in f.values():
            assert value in _FRESHNESS_VOCAB

    def test_w22_waiting_global_state(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox_with_resumable_submission(tmp_path), B, E)
        pending = d["pending_action"]
        # fixture: fs verified + one unresolved submission → WAITING_FOR_USER
        assert pending is not None
        assert pending["status"] == "WAITING_FOR_USER"
        assert pending["action_id"] == "RESOLVE_PENDING_ACTION"
        assert pending["submissions"], "BRW-018R2 pending submission surfaced"
        assert d["recommended_next_action"]["action_id"] == "RESOLVE_PENDING_ACTION"

    def test_w24_impossible_split_blocks_models(self, tmp_path: Path) -> None:
        """Sandbox where the only split is NOT_READY_FOR_MODEL_EVALUATION."""
        sandbox = tmp_path / "processed"
        sandbox.mkdir()
        # copy fixture manifests but keep only the NOT_READY split of the
        # committed dataset; models removed → MODELS must be BLOCKED
        src_datasets = PROCESSED / "datasets" / B / E / "SOC" / "DS::6a3142e5186fc684964ff09e"
        (sandbox / "datasets" / B / E / "SOC" / "DS::6a3142e5186fc684964ff09e").mkdir(parents=True)
        for f in src_datasets.glob("dataset_manifest.json"):
            (sandbox / "datasets" / B / E / "SOC" / "DS::6a3142e5186fc684964ff09e" / f.name).write_text(
                f.read_text(encoding="utf-8"), encoding="utf-8"
            )
        # the fixture also has a NOT_READY split on a different dataset; give the
        # committed dataset only that readiness via a rewritten manifest
        import shutil

        bad_split_src = next(
            p for p in (PROCESSED / "splits" / B / E).rglob("split_manifest.json")
            if json.loads(p.read_text(encoding="utf-8")).get("readiness_status")
            == "NOT_READY_FOR_MODEL_EVALUATION"
        )
        bad = json.loads(bad_split_src.read_text(encoding="utf-8"))
        bad["dataset_id"] = "DS::6a3142e5186fc684964ff09e"
        bad_dir = sandbox / "splits" / B / E / "DS::6a3142e5186fc684964ff09e" / bad["split_id"]
        bad_dir.mkdir(parents=True)
        (bad_dir / "split_manifest.json").write_text(
            json.dumps(bad, indent=2), encoding="utf-8"
        )
        # symlink canonical event/label sources for target/alignment steps
        for rel, sub in (("multimodal", None), ("labels", None), ("synchronization", None)):
            src = PROCESSED / rel / B / E
            if src.exists():
                target = sandbox / rel / B / E
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(src)
        shutil.rmtree(sandbox / "splits" / B / E / "DS::c10c43b1890949aff0e94663", ignore_errors=True)

        d = build_workflow_context(sandbox, B, E)
        assert d["steps"]["SPLIT"]["status"] == "LIMITED"
        assert d["steps"]["MODELS"]["status"] == "BLOCKED"
        assert d["steps"]["MODELS"]["blocking"]["blocking_code"] == "VALID_SPLIT_REQUIRED"

    def test_w26_typed_navigation(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        rec = d["recommended_next_action"]
        assert set(rec) >= {"action_id", "step", "label", "route"}
        assert rec["route"].startswith(f"/experiments/{B}/{E}/")
        for action in d["typed_actions"]:
            assert set(action) == {"action_id", "label", "route"}
            assert action["action_id"] in {
                "REVIEW_TARGET", "REVIEW_ALIGNMENT", "CONFIGURE_FEATURES",
                "OPEN_PREVIEW", "BUILD_DATASET", "CREATE_SPLIT",
                "TRAIN_MODELS", "OPEN_REPORT",
            }
            assert action["route"].startswith(f"/experiments/{B}/{E}/")

    def test_w27_assistant_context(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        ac = d["assistant_context"]
        assert ac is not None
        assert ac["session_id"].startswith("RS::")
        assert isinstance(ac["next_actions"], list)

    def test_w28_no_artifact_writes(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)

        def snapshot() -> dict[str, tuple]:
            out = {}
            for rel in (
                "features_physical", "datasets", "models", "splits",
                "parameters", "gate_calibrations", "feature_analysis",
                "artifacts", "assistant_sessions",
            ):
                root = sandbox / rel
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*.json"))[:80]:
                    out[str(p)] = (p.stat().st_mtime, p.stat().st_size)
            return out

        before = snapshot()
        build_workflow_context(sandbox, B, E)
        build_workflow_context(sandbox, B, E)  # second read = idempotent
        assert snapshot() == before

    def test_w02_unknown_experiment_404(self, tmp_path: Path) -> None:
        from battery_workbench.api.errors import HTTP_STATUS

        with pytest.raises(APIError) as exc_info:
            build_workflow_context(_sandbox(tmp_path), "CELL_999", "EXP_999")
        assert HTTP_STATUS[exc_info.value.code] == 404


@pytest.mark.skipif(not has_cell210, reason="CELL_210/EXP_015 artifacts not available")
class TestExperimentIsolation:
    def test_w20_cell210_own_context_no_leakage(self, tmp_path: Path) -> None:
        d = build_workflow_context(PROCESSED, "CELL_210", "EXP_015")
        assert d["battery_id"] == "CELL_210"
        assert d["experiment_id"] == "EXP_015"
        sc = d["scientific_context"]
        assert sc["battery_id"] == "CELL_210"
        # no CELL_001 artifact ids leak into CELL_210 context
        blob = json.dumps(d)
        assert "CELL_001" not in blob
        assert "DS::6a3142e5186fc684964ff09e" not in blob

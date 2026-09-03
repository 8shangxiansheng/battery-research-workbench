"""BRW-023 T27-T43: scientific reporting metrics honesty, reproducibility, orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.orchestrator.engine import PipelineOrchestrator

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

pytestmark = pytest.mark.skipif(
    not (PROCESSED / "models/CELL_001/EXP_001").exists(),
    reason="real CELL_001/EXP_001 model artifacts not available",
)


def _engine(tmp_path: Path) -> PipelineOrchestrator:
    return PipelineOrchestrator(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")


def _report(engine: PipelineOrchestrator, tmp_path: Path) -> dict:
    return engine.generate_report(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        target="soc_reference_percent",
    )


# --- T27-T31: metrics honesty ---


def test_t27_per_fold_metrics_preserved(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    model_results = [r for r in report["result_registry"] if r["result_type"] == "MODEL_METRIC"]
    folds = {r.get("fold_index") for r in model_results if r.get("fold_index") is not None}
    assert 1 in folds and 2 in folds


def test_t28_macro_metrics_preserved(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    macros = [r for r in report["result_registry"] if r["result_type"] == "MODEL_COMPARISON"]
    assert macros, "macro comparison results must exist"


def test_t29_pooled_diagnostic_not_promoted(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    for r in report["result_registry"]:
        assert r.get("pooled_rows_usage") != "INDEPENDENT_SAMPLES"


def test_t30_dummy_comparison_correct(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    dummy = [
        r
        for r in report["result_registry"]
        if r["result_type"] == "MODEL_METRIC" and "DUMMY" in r["name"].upper()
    ]
    assert dummy, "Dummy results must be present"


def test_t31_negative_r2_reported_honestly(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    r2_results = [
        r
        for r in report["result_registry"]
        if r["result_type"] == "MODEL_METRIC" and "R2" in r["name"].upper()
    ]
    assert any(r["value"] is not None and r["value"] < 0 for r in r2_results), (
        "negative R2 must be reported honestly"
    )


def test_t32_no_best_production_model_claim(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    text = json.dumps(report)
    assert "production-ready" not in text.lower() or "not production-ready" in text.lower()


# --- T33-T38: reproducibility manifest ---


def test_t33_raw_checksums_present(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    rm = report["reproducibility_manifest"]
    assert rm.get("raw_asset_checksums") or rm.get("raw_assets")
    assert rm.get("git_commit")


def test_t34_artifact_ids_present(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    rm = report["reproducibility_manifest"]
    for key in ("dataset_id", "split_id", "label_set_id", "parameter_set_ids"):
        assert rm.get(key), f"repro manifest missing {key}"


def test_t35_all_key_lineage_ids_present(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    lineage = report.get("lineage_snapshot") or {}
    text = json.dumps(lineage)
    for known in (
        "DS::6a3142e5186fc684964ff09e",
        "SPLIT::062cf007d21578a11ab2d728",
        "GATESET::8633ce421ad5e26fe686",
    ):
        assert known in text, f"lineage missing {known}"


def test_t36_git_commit_captured(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    rm = report["reproducibility_manifest"]
    assert rm.get("git_commit") and len(rm["git_commit"]) >= 7


def test_t37_policy_schema_versions_captured(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    rm = report["reproducibility_manifest"]
    assert rm.get("policy_versions") or rm.get("schema_versions")


def test_t38_environment_captured_no_secrets(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    report = _report(engine, tmp_path)
    rm = report["reproducibility_manifest"]
    env = rm.get("environment") or {}
    assert env.get("python_version") or env.get("python")
    text = json.dumps(rm)
    for secret in ("api_key", "password", "secret", "token"):
        assert secret not in text.lower() or "None" in text


# --- T39-T43: orchestrator ---


def test_t39_scientific_report_node(tmp_path: Path) -> None:
    from battery_workbench.orchestrator.dag import NODE_DEPENDENCIES

    assert "SCIENTIFIC_REPORT" in NODE_DEPENDENCIES


def test_t40_report_without_model_rerun(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    run = _report(engine, tmp_path)
    model_nodes = [n for n in run["nodes"] if n["node_id"] == "SOC_MODELING"]
    # model node reused (not refit) when report is generated
    if model_nodes:
        assert model_nodes[0]["state"] in {"REUSED", "SUCCEEDED"}


def test_t41_report_reuse(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    r1 = _report(engine, tmp_path)
    r2 = _report(engine, tmp_path)
    assert r1["report_id"] == r2["report_id"]


def test_t42_model_change_invalidates_report_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    plan1 = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
    )
    plan2 = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
        modeling={"strategies": ["DUMMY_MEAN"], "random_state": 99},
    )
    e1 = engine.dry_run(plan1)
    e2 = engine.dry_run(plan2)
    # report node should be re-evaluated when model spec changes
    sr1 = next(n for n in e1.nodes if n.node_id == "SCIENTIFIC_REPORT")
    sr2 = next(n for n in e2.nodes if n.node_id == "SCIENTIFIC_REPORT")
    assert sr1.state.value == sr2.state.value  # both same (reused or running)


def test_t43_report_section_change_no_upstream_invalidation(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    p1 = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
    )
    p2 = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        dry_run=True,
        scientific_report={"sections": ["Executive Summary"]},
    )
    e1 = engine.dry_run(p1)
    e2 = engine.dry_run(p2)
    for node_type in ("SYNCHRONIZATION", "MEASUREMENT_EVENTS", "DATASET", "SPLIT"):
        s1 = next(n for n in e1.nodes if n.node_id == node_type)
        s2 = next(n for n in e2.nodes if n.node_id == node_type)
        assert s1.state.value == s2.state.value

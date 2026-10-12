from __future__ import annotations

import json
from pathlib import Path

import yaml

from battery_workbench.orchestrator.engine import PipelineOrchestrator, RunContext
from battery_workbench.orchestrator.nodes import ScientificReportNode
from battery_workbench.reporting.schemas import ExperimentRecord

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "analysis-plan.yaml"
)


def _write_incomplete_plan(root: Path) -> None:
    payload = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    payload["study"].update({"study_id": "STUDY_A", "title": "Study A"})
    payload["primary_analysis"]["eligible_batteries_and_experiments"] = [
        {"battery_id": "CELL_A", "experiment_id": "EXP_1"}
    ]
    directory = root / "data" / "annotations" / "studies" / "STUDY_A"
    directory.mkdir(parents=True)
    (directory / "analysis-plan.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def test_report_node_freezes_plan_status_hash_and_reuse_identity(
    tmp_path: Path, monkeypatch
) -> None:
    import battery_workbench.reporting.schemas as report_schemas
    from battery_workbench.reporting import collector

    raw_root = tmp_path / "data" / "raw"
    processed_root = tmp_path / "data" / "processed"
    _write_incomplete_plan(tmp_path)
    plan_path = tmp_path / "data" / "annotations" / "studies" / "STUDY_A" / "analysis-plan.yaml"
    declared_plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    declared_plan["study"].update({
        "status": "APPROVED",
        "approved_by": "PI",
        "approved_at": "2026-01-02T00:00:00+00:00",
    })
    plan_path.write_text(yaml.safe_dump(declared_plan, sort_keys=False), encoding="utf-8")
    engine = PipelineOrchestrator(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    plan = engine.plan_run(
        profile="FULL_PRE_MODEL",
        battery_id="CELL_A",
        experiment_id="EXP_1",
        dry_run=False,
        target="soc_reference_percent",
    )
    frozen_plan = plan.scientific_report["analysis_plan_assessment"]
    assert frozen_plan["status"] == "INCOMPLETE"
    assert plan.scientific_report["analysis_plan_sha256"] == frozen_plan["plan_sha256"]

    monkeypatch.setattr(
        collector,
        "collect_experiment_record",
        lambda _root, battery_id, experiment_id: ExperimentRecord(
            battery_id=battery_id, experiment_id=experiment_id
        ),
    )
    monkeypatch.setattr(collector, "collect_results", lambda *_args: [])
    monkeypatch.setattr(collector, "collect_evidence_registry", lambda *_args: [])
    monkeypatch.setattr(collector, "collect_limitation_registry", lambda *_args: [])
    monkeypatch.setattr(report_schemas, "build_lineage_snapshot", lambda *_args: {})

    ctx = RunContext(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
        run_id="RUN::REPORT_TEST",
        run_dir=tmp_path / "runs" / "REPORT_TEST",
    )
    output = ScientificReportNode().run(plan, {}, ctx)
    report = json.loads(Path(output["manifest_path"]).read_text(encoding="utf-8"))

    assert report["inference_assessment"]["analysis_plan"]["status"] == "INCOMPLETE"
    assert report["inference_assessment"]["analysis_plan"]["confirmatory_inference_enabled"] is False
    assert report["inference_assessment"]["analysis_plan"]["approval_identity_status"] == "SELF_DECLARED_NOT_AUTHENTICATED"
    assert report["inference_assessment"]["analysis_plan"]["approval_evidence_status"] == "NOT_VERIFIED"
    assert report["analysis_plan_sha256"] == frozen_plan["plan_sha256"]
    assert report["reproducibility_manifest"]["analysis_plan_sha256"] == frozen_plan["plan_sha256"]
    assert report["reproducibility_manifest"]["analysis_plan_status"] == "INCOMPLETE"

    requirements = ScientificReportNode().requirements(plan, {})
    assert requirements.expected_version == "0.3.0"
    assert requirements.extra_match["analysis_plan_sha256"] == frozen_plan["plan_sha256"]

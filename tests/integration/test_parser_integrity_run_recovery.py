from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.agent_assistant.session import AgentResearchSession, SessionStore
from battery_workbench.api.app import create_app
from battery_workbench.orchestrator.engine import PipelineOrchestrator
from battery_workbench.reporting.collector import invalid_parser_manifest_modalities

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"


@pytest.mark.parametrize(
    ("modality", "parser_stage"),
    [
        ("electrical", "ELECTRICAL_CANONICAL"),
        ("ultrasound", "ULTRASOUND_CANONICAL"),
    ],
)
def test_invalid_parser_source_blocks_analysis_but_allows_parser_only_recovery(
    tmp_path: Path, modality: str, parser_stage: str
) -> None:
    battery_id, experiment_id = "CELL_001", "EXP_001"
    processed = tmp_path / "processed"
    parser_manifest = processed / modality / battery_id / experiment_id / "parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    other_modality = "ultrasound" if modality == "electrical" else "electrical"
    other_manifest = processed / other_modality / battery_id / experiment_id / "parser_manifest.json"
    other_manifest.parent.mkdir(parents=True)
    other_manifest.write_bytes(
        (REPO / "data" / "processed" / other_modality / battery_id / experiment_id / "parser_manifest.json").read_bytes()
    )
    other_source_dir = REPO / "data" / "processed" / other_modality / battery_id / experiment_id
    for source_output in other_source_dir.iterdir():
        if source_output.name == "parser_manifest.json":
            continue
        destination = other_manifest.parent / source_output.name
        if source_output.is_dir():
            shutil.copytree(source_output, destination)
        else:
            shutil.copy2(source_output, destination)
    runs = tmp_path / "runs"
    client = TestClient(
        create_app(raw_root=RAW, processed_root=processed, runs_root=runs)
    )

    analysis_response = client.post(
        "/api/v1/runs",
        json={"profile": "SCIENTIFIC_ANALYSIS", "battery_id": battery_id, "experiment_id": experiment_id},
    )
    assert analysis_response.status_code == 409
    assert analysis_response.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"
    assert analysis_response.json()["error"]["details"]["recovery_action"] == (
        "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
    )
    assert not runs.exists()

    recovery_payload = {
        "profile": "INGEST_TO_MEASUREMENT_EVENTS",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "stages": [parser_stage],
    }
    planned = client.post("/api/v1/runs/plan", json=recovery_payload)
    assert planned.status_code == 200, planned.text
    plan = planned.json()["data"]
    assert plan["stages"] == [parser_stage]
    assert plan["execution"]["force_recompute"] == [parser_stage]

    recovered = client.post("/api/v1/runs", json=recovery_payload)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["status"] == "SUCCEEDED"
    assert invalid_parser_manifest_modalities(processed, battery_id, experiment_id) == []
    parsed_manifest = json.loads(parser_manifest.read_text(encoding="utf-8"))
    assert isinstance(parsed_manifest, dict)
    assert parsed_manifest["source_sha256"]


def test_first_parse_with_registered_raw_assets_is_not_stale_source(tmp_path: Path) -> None:
    from battery_workbench.provenance.parser_manifest import invalid_parser_source_modalities

    assert invalid_parser_source_modalities(
        tmp_path / "empty-processed", RAW, "CELL_001", "EXP_001"
    ) == []


def test_parser_output_checksum_mismatch_blocks_analysis_and_forces_reparse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.provenance import parser_manifest

    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    processed = tmp_path / "processed"
    directory = processed / "electrical" / battery_id / experiment_id
    directory.mkdir(parents=True)
    outputs = {name: f"{name}.parquet" for name in ("records", "cycles", "steps")}
    for filename in outputs.values():
        (directory / filename).write_bytes(b"tampered parser output")
    (directory / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "output_files": outputs,
            "output_checksums": {name: "0" * 64 for name in outputs},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(parser_manifest, "invalid_parser_source_modalities", lambda *_: [])
    orchestrator = PipelineOrchestrator(raw_root=tmp_path / "raw", processed_root=processed)

    analysis_plan = orchestrator.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    _, reason = orchestrator._preflight_parser_sources(analysis_plan)
    assert reason is not None
    assert "parser output integrity is invalid for electrical" in reason

    recovery_plan = orchestrator.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id=battery_id,
        experiment_id=experiment_id,
        stages=["ELECTRICAL_CANONICAL"],
    )
    recovered_plan, recovery_reason = orchestrator._preflight_parser_sources(recovery_plan)
    assert recovery_reason is None
    assert recovered_plan.execution.force_recompute == ["ELECTRICAL_CANONICAL"]


def test_direct_engine_run_blocks_stale_source_and_dry_run_forces_parser_recovery(
    tmp_path: Path,
) -> None:
    battery_id, experiment_id = "CELL_001", "EXP_001"
    processed = tmp_path / "processed"
    parser_manifest = processed / "electrical" / battery_id / experiment_id / "parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    orchestrator = PipelineOrchestrator(raw_root=RAW, processed_root=processed)

    scientific_plan = orchestrator.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    blocked = orchestrator.start_run(scientific_plan, runs_root=tmp_path / "blocked-runs")
    assert blocked["status"] == "PARTIAL"
    assert blocked["nodes"]
    assert all(node["state"] == "BLOCKED" for node in blocked["nodes"])
    assert all("parser source integrity is invalid" in node["reason"] for node in blocked["nodes"])

    recovery_plan = orchestrator.plan_run(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        battery_id=battery_id,
        experiment_id=experiment_id,
        stages=["ELECTRICAL_CANONICAL"],
    )
    preview = orchestrator.dry_run(recovery_plan)
    parser_node = next(node for node in preview.nodes if node.node_id == "ELECTRICAL_CANONICAL")
    assert parser_node.state == "RUNNING"
    assert parser_node.reason == "forced recompute"


def test_invalid_source_blocks_access_and_resume_of_historical_scientific_run(
    tmp_path: Path,
) -> None:
    battery_id, experiment_id = "CELL_001", "EXP_001"
    processed = tmp_path / "processed"
    parser_manifest = processed / "electrical" / battery_id / experiment_id / "parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    runs = tmp_path / "runs"
    run_dir = runs / "historical"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "RUN::historical",
                "analysis_plan_id": "PLAN::historical",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "status": "WAITING_FOR_USER",
                "user_actions": [],
                "nodes": [],
                "final_artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "analysis_plan.json").write_text(
        json.dumps(
            {
                "profile": "SCIENTIFIC_ANALYSIS",
                "project": {"battery_id": battery_id, "experiment_id": experiment_id},
                "stages": ["SYNCHRONIZATION"],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(raw_root=RAW, processed_root=processed, runs_root=runs))

    detail = client.get("/api/v1/runs/RUN::historical")
    events = client.get("/api/v1/runs/RUN::historical/events")
    actions = client.get("/api/v1/runs/RUN::historical/user-actions")
    resumed = client.post("/api/v1/runs/RUN::historical/resume", json={})
    retried = client.post(
        "/api/v1/runs/RUN::historical/retry", json={"node_id": "SYNCHRONIZATION"}
    )

    for response in (detail, events, actions, resumed, retried):
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
        assert response.json()["error"]["details"]["recovery_action"] == (
            "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        )


def test_raw_source_mismatch_blocks_scientific_run_and_requires_parser_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.provenance import parser_manifest

    monkeypatch.setattr(
        parser_manifest,
        "invalid_parser_source_modalities",
        lambda *_args: ["ultrasound"],
    )
    processed = tmp_path / "processed"
    runs = tmp_path / "runs"
    client = TestClient(create_app(raw_root=RAW, processed_root=processed, runs_root=runs))

    blocked = client.post(
        "/api/v1/runs",
        json={
            "profile": "SCIENTIFIC_ANALYSIS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"]["invalid_modalities"] == ["ultrasound"]
    assert not runs.exists()

    recovery = client.post(
        "/api/v1/runs/plan",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "stages": ["ULTRASOUND_CANONICAL"],
        },
    )
    assert recovery.status_code == 200, recovery.text
    assert recovery.json()["data"]["execution"]["force_recompute"] == [
        "ULTRASOUND_CANONICAL"
    ]


def test_assistant_session_is_restarted_without_stale_conversation_on_source_change(
    tmp_path: Path,
) -> None:
    battery_id, experiment_id = "CELL_001", "EXP_001"
    processed = tmp_path / "processed"
    parser_manifest = processed / "electrical" / battery_id / experiment_id / "parser_manifest.json"
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    store = SessionStore(processed)
    historical = AgentResearchSession(
        session_id="RS::historical", battery_id=battery_id, experiment_id=experiment_id
    )
    historical.add_turn("assistant", "旧科学结论：不应在来源损坏时继续展示。")
    store.save(historical)
    client = TestClient(create_app(raw_root=RAW, processed_root=processed, runs_root=tmp_path / "runs"))

    opened = client.post(f"/api/v1/experiments/{battery_id}/{experiment_id}/assistant/session")
    assert opened.status_code == 200, opened.text
    fresh = opened.json()["data"]
    assert fresh["session_id"] != historical.session_id
    assert fresh["conversation"] == []
    assert fresh["ui_context"]["source_integrity_status"] == "INTEGRITY_BLOCKED"
    assert opened.json()["meta"]["invalid_modalities"] == ["electrical"]

    old_read = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/assistant/session/{historical.session_id}"
    )
    old_message = client.post(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/assistant/session/{historical.session_id}/message",
        json={"message": "继续分析"},
    )
    assert old_read.status_code == 409
    assert old_message.status_code == 409
    assert "旧科学结论" not in old_read.text + old_message.text

    parser_manifest.write_text("{}", encoding="utf-8")
    changed_source = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/assistant/session/{fresh['session_id']}"
    )
    assert changed_source.status_code == 409

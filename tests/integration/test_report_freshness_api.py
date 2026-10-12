"""Frozen scientific reports are labeled with live freshness on API reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.errors import APIError
from battery_workbench.api.service import WorkbenchService
from battery_workbench.api.workflow_context import build_workflow_context

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
BATTERY_ID, EXPERIMENT_ID = "CELL_001", "EXP_001"
REPORT_ROOT = (
    PROCESSED / "artifacts" / BATTERY_ID / EXPERIMENT_ID / "reports"
)

report_files = list(REPORT_ROOT.rglob("scientific_report.json"))


@pytest.mark.skipif(not report_files, reason="real report artifacts unavailable")
def test_list_and_get_report_include_live_freshness_without_rewriting_artifact(
    tmp_path: Path,
) -> None:
    latest_path = max(report_files, key=lambda path: path.stat().st_mtime)
    frozen_bytes = latest_path.read_bytes()
    latest_id = json.loads(frozen_bytes)["report_id"]
    context = build_workflow_context(PROCESSED, BATTERY_ID, EXPERIMENT_ID)
    expected_latest_status = context["artifact_freshness"]["report"]
    client = TestClient(
        create_app(
            raw_root=REPO / "data" / "raw",
            processed_root=PROCESSED,
            runs_root=tmp_path / "runs",
        )
    )

    listed = client.get(
        "/api/v1/reports",
        params={"battery_id": BATTERY_ID, "experiment_id": EXPERIMENT_ID},
    )
    assert listed.status_code == 200
    reports = listed.json()["data"]
    current = next(report for report in reports if report["report_id"] == latest_id)
    assert current["report_freshness"]["status"] == expected_latest_status
    assert current["report_freshness"]["status"] in {
        "CURRENT", "STALE", "LEGACY", "SUPERSEDED", "MISSING"
    }

    fetched = client.get(f"/api/v1/reports/{latest_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["report_freshness"] == current["report_freshness"]
    assert latest_path.read_bytes() == frozen_bytes


def test_create_report_response_includes_freshness_annotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    monkeypatch.setattr(service, "_require_experiment", lambda *_args: None)
    monkeypatch.setattr(
        service._runs,
        "generate_report",
        lambda **_kwargs: {"report_id": "REPORT::fixture", "result_registry": []},
    )
    monkeypatch.setattr(
        service,
        "_report_workflow_context",
        lambda *_args: {
            "artifact_freshness": {"dataset": "STALE", "models": "STALE", "report": "STALE"}
        },
    )

    result = service.generate_report(
        {"battery_id": "CELL_FIXTURE", "experiment_id": "EXP_FIXTURE"}
    )
    assert result["report_freshness"] == {
        "status": "STALE",
        "reasons": ["DATASET_SOURCE_STALE", "MODEL_EVALUATION_NOT_CURRENT"],
    }


def test_duplicate_report_id_is_not_resolved_by_newest_mtime(tmp_path: Path) -> None:
    processed_root = tmp_path / "processed"
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    for battery_id in ("CELL_A", "CELL_B"):
        report_path = (
            processed_root
            / "artifacts"
            / battery_id
            / "EXP_A"
            / "reports"
            / "REPORT::duplicate"
            / "scientific_report.json"
        )
        report_path.parent.mkdir(parents=True)
        report_path.write_text(
            json.dumps({"report_id": "REPORT::duplicate"}), encoding="utf-8"
        )

    with pytest.raises(APIError) as exc_info:
        service.get_report("REPORT::duplicate")

    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert exc_info.value.details["match_count"] == 2


def test_invalid_parser_provenance_redacts_frozen_report_claims(tmp_path: Path) -> None:
    processed_root = tmp_path / "processed"
    parser_manifest = (
        processed_root / "electrical/CELL_TEST/EXP_TEST/parser_manifest.json"
    )
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text("[]", encoding="utf-8")
    (processed_root / "datasets/CELL_TEST/EXP_TEST").mkdir(parents=True)
    report_path = (
        processed_root
        / "artifacts/CELL_TEST/EXP_TEST/reports/REPORT::frozen/scientific_report.json"
    )
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "report_id": "REPORT::frozen",
                "generated_at": "2026-01-01T00:00:00Z",
                "scientific_findings": ["untrusted frozen claim"],
                "result_registry": [{"value": 12.3}],
                "experiment_record": {"latest_canonical_artifacts": {"dataset_id": "DS::old"}},
            }
        ),
        encoding="utf-8",
    )
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )

    listed = service.list_reports("CELL_TEST", "EXP_TEST")
    fetched = service.get_report("REPORT::frozen")

    for report in [*listed, fetched]:
        assert report["report_freshness"] == {
            "status": "INTEGRITY_BLOCKED",
            "reasons": ["SOURCE_PROVENANCE_INVALID"],
        }
        assert report["scientific_status"] == "INTEGRITY_BLOCKED"
        assert "scientific_findings" not in report
        assert "result_registry" not in report
        assert "untrusted frozen claim" not in json.dumps(report)


def test_report_generation_is_blocked_before_writing_on_invalid_source_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed_root = tmp_path / "processed"
    manifest = processed_root / "electrical/CELL_TEST/EXP_TEST/parser_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("[]", encoding="utf-8")
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    monkeypatch.setattr(service, "_require_experiment", lambda *_args: None)
    generate_called = False

    def fail_if_called(**_kwargs):
        nonlocal generate_called
        generate_called = True
        raise AssertionError("report generator must not run for invalid source lineage")

    monkeypatch.setattr(service._runs, "generate_report", fail_if_called)

    with pytest.raises(APIError) as exc_info:
        service.generate_report({"battery_id": "CELL_TEST", "experiment_id": "EXP_TEST"})

    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert exc_info.value.details["invalid_modalities"] == ["electrical"]
    assert not generate_called
    assert not (processed_root / "artifacts").exists()


def test_report_reads_and_generation_block_after_raw_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    relative_path = "batteries/CELL_TEST/EXP_TEST/electrical/source.xlsx"
    source = raw_root / relative_path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original workbook")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assets_manifest = raw_root / "manifests" / "data_assets.csv"
    assets_manifest.parent.mkdir(parents=True)
    assets_manifest.write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path\n"
        f"E_TEST,{battery_id},{experiment_id},electrical,{relative_path}\n",
        encoding="utf-8",
    )
    parser_manifest = (
        processed_root / "electrical/CELL_TEST/EXP_TEST/parser_manifest.json"
    )
    parser_manifest.parent.mkdir(parents=True)
    parser_manifest.write_text(
        json.dumps(
            {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "source_sha256": {"E_TEST": digest},
                "source_asset_details": [
                    {"asset_id": "E_TEST", "relative_path": relative_path}
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = (
        processed_root
        / "artifacts/CELL_TEST/EXP_TEST/reports/REPORT::frozen/scientific_report.json"
    )
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "report_id": "REPORT::frozen",
                "generated_at": "2026-01-01T00:00:00Z",
                "scientific_findings": ["frozen claim"],
                "result_registry": [{"value": 12.3}],
            }
        ),
        encoding="utf-8",
    )
    source.write_bytes(b"replaced workbook")
    service = WorkbenchService(
        raw_root=raw_root,
        processed_root=processed_root,
        runs_root=tmp_path / "runs",
    )
    monkeypatch.setattr(service._runs, "generate_report", lambda **_kwargs: pytest.fail("must block"))

    for report in [
        *service.list_reports(battery_id, experiment_id),
        service.get_report("REPORT::frozen"),
    ]:
        assert report["report_freshness"]["status"] == "INTEGRITY_BLOCKED"
        assert "scientific_findings" not in report
        assert "result_registry" not in report
    with pytest.raises(APIError) as exc_info:
        service.generate_report({"battery_id": battery_id, "experiment_id": experiment_id})
    assert exc_info.value.code.value == "INTEGRITY_ERROR"
    assert exc_info.value.details["invalid_modalities"] == ["electrical"]

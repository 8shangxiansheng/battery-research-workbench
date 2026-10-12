from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.service import WorkbenchService
from battery_workbench.api.workflow_context import build_workflow_context
from battery_workbench.orchestrator.nodes import ScientificReportNode
from battery_workbench.reporting.report import generate_report_files, verify_report_outputs

BATTERY_ID = "CELL_TEST"
EXPERIMENT_ID = "EXP_TEST"
REPORT_ID = "REPORT::fixture"


def _write_report(root: Path) -> Path:
    paths = generate_report_files(
        report={
            "report_id": REPORT_ID,
            "scientific_findings": ["synthetic test fixture"],
            "sections": {},
        },
        battery_id=BATTERY_ID,
        experiment_id=EXPERIMENT_ID,
        report_id=REPORT_ID,
        output_root=root,
    )
    return Path(paths["report_json"])


def test_report_writer_creates_verifiable_sidecar_manifest(tmp_path: Path) -> None:
    report_path = _write_report(tmp_path)

    status, reasons = verify_report_outputs(
        report_path,
        battery_id=BATTERY_ID,
        experiment_id=EXPERIMENT_ID,
        reports_root=(
            tmp_path / "artifacts" / BATTERY_ID / EXPERIMENT_ID / "reports"
        ),
    )

    assert status == "CURRENT"
    assert reasons == []
    manifest = json.loads(
        (report_path.parent / "scientific_report_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(manifest["output_checksums"]) == {
        "scientific_report.json",
        "scientific_report.md",
        "scientific_report.html",
    }


def test_workbench_parser_gate_blocks_tampered_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battery_workbench.provenance import parser_manifest

    processed = tmp_path / "processed"
    directory = processed / "electrical" / BATTERY_ID / EXPERIMENT_ID
    directory.mkdir(parents=True)
    outputs = {name: f"{name}.parquet" for name in ("records", "cycles", "steps")}
    for filename in outputs.values():
        (directory / filename).write_bytes(b"parser output")
    (directory / "parser_manifest.json").write_text(
        json.dumps({
            "battery_id": BATTERY_ID,
            "experiment_id": EXPERIMENT_ID,
            "output_files": outputs,
            "output_checksums": {name: "0" * 64 for name in outputs},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(parser_manifest, "invalid_parser_source_modalities", lambda *_: [])
    service = WorkbenchService(
        raw_root=tmp_path / "raw", processed_root=processed, runs_root=tmp_path / "runs"
    )

    with pytest.raises(APIError) as exc_info:
        service._assert_parser_provenance(BATTERY_ID, EXPERIMENT_ID)

    assert exc_info.value.code == "INTEGRITY_ERROR"
    assert "OUTPUT_CHECKSUM_MISMATCH:records" in str(exc_info.value.details)


@pytest.mark.parametrize(
    "filename",
    ["scientific_report.json", "scientific_report.md", "scientific_report.html"],
)
def test_report_output_tampering_is_blocked(tmp_path: Path, filename: str) -> None:
    report_path = _write_report(tmp_path)
    (report_path.parent / filename).write_text("tampered", encoding="utf-8")

    status, reasons = verify_report_outputs(report_path)

    assert status == "INTEGRITY_BLOCKED"
    assert f"REPORT_OUTPUT_CHECKSUM_MISMATCH:{filename}" in reasons


def test_legacy_report_without_sidecar_is_not_current(tmp_path: Path) -> None:
    report_path = _write_report(tmp_path)
    (report_path.parent / "scientific_report_manifest.json").unlink()

    assert verify_report_outputs(report_path) == (
        "LEGACY",
        ["REPORT_OUTPUT_MANIFEST_MISSING"],
    )


def test_report_sidecar_identity_and_root_confinement_fail_closed(
    tmp_path: Path,
) -> None:
    report_path = _write_report(tmp_path)
    status, reasons = verify_report_outputs(
        report_path,
        battery_id="CELL_OTHER",
        experiment_id=EXPERIMENT_ID,
    )
    assert status == "INTEGRITY_BLOCKED"
    assert reasons == ["REPORT_OUTPUT_IDENTITY_MISMATCH"]

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_report = _write_report(outside)
    constrained_root = (
        tmp_path / "artifacts" / BATTERY_ID / EXPERIMENT_ID / "reports"
    )
    status, reasons = verify_report_outputs(outside_report, reports_root=constrained_root)
    assert status == "INTEGRITY_BLOCKED"
    assert reasons == ["REPORT_OUTPUT_OUTSIDE_ROOT"]


def test_report_api_redacts_tampered_frozen_report(tmp_path: Path, monkeypatch) -> None:
    processed = tmp_path / "processed"
    (processed / "datasets" / BATTERY_ID / EXPERIMENT_ID).mkdir(parents=True)
    report_path = _write_report(processed)
    report_path.write_text("{broken", encoding="utf-8")
    service = WorkbenchService(
        raw_root=tmp_path / "raw",
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )
    monkeypatch.setattr(
        service,
        "_report_workflow_context",
        lambda *_args: {
            "artifact_freshness": {
                "dataset": "CURRENT",
                "models": "CURRENT",
                "report": "CURRENT",
            }
        },
    )

    listed = service.list_reports(BATTERY_ID, EXPERIMENT_ID)
    fetched = service.get_report(REPORT_ID)

    for report in [*listed, fetched]:
        assert report["scientific_status"] == "INTEGRITY_BLOCKED"
        assert report["report_freshness"]["status"] == "INTEGRITY_BLOCKED"
        assert "scientific_findings" not in report
        assert "result_registry" not in report


def test_workflow_context_blocks_tampered_report(tmp_path: Path) -> None:
    report_path = _write_report(tmp_path / "processed")
    (report_path.parent / "scientific_report.html").write_text("modified", encoding="utf-8")

    context = build_workflow_context(tmp_path / "processed", BATTERY_ID, EXPERIMENT_ID)

    assert context["artifact_freshness"]["report"] == "INTEGRITY_BLOCKED"
    assert context["artifact_freshness"]["report_output"] == "INTEGRITY_BLOCKED"
    assert context["steps"]["REPORT"]["status"] == "BLOCKED"
    assert context["steps"]["REPORT"]["committed"] is None


def test_report_node_reuses_only_current_integrity_verified_outputs(tmp_path: Path) -> None:
    plan = SimpleNamespace(
        project=SimpleNamespace(battery_id=BATTERY_ID, experiment_id=EXPERIMENT_ID),
        scientific_report={"analysis_plan_sha256": None},
    )
    report_path = generate_report_files(
        report={
            "report_id": REPORT_ID,
            "producer_version": "0.3.0",
            "analysis_plan_sha256": None,
            "sections": {},
        },
        battery_id=BATTERY_ID,
        experiment_id=EXPERIMENT_ID,
        report_id=REPORT_ID,
        output_root=tmp_path,
    )["report_json"]
    node = ScientificReportNode()

    ref, _reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert ref is not None

    (Path(report_path).parent / "scientific_report.html").write_text(
        "tampered", encoding="utf-8"
    )
    ref, reason = node.resolve_existing_output(plan, {}, tmp_path)
    assert ref is None
    assert "CHECKSUM" in reason

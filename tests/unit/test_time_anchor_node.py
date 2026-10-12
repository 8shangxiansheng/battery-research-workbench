from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from battery_workbench.api.future_contracts import (
    TimebaseAnchor,
    TimebaseReviewRequest,
    TimebaseValidationRequest,
)
from battery_workbench.orchestrator.nodes import TimeAnchorNode
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject
from battery_workbench.synchronization.timebase_registry import (
    TimebaseRegistryError,
    list_timebase_validations,
    review_timebase_validation,
    submit_timebase_validation,
)


def test_time_anchor_node_uses_battery_and_experiment_composite_identity(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
        "EXP_001,CELL_A,2024-01-01T00:00:00,,,\n"
        "EXP_001,CELL_B,2024-02-01T00:00:00,,,\n",
        encoding="utf-8",
    )
    (manifest_root / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id="CELL_B", experiment_id="EXP_001"),
    )

    TimeAnchorNode().run(
        plan,
        {},
        SimpleNamespace(raw_root=raw_root, processed_root=processed_root),
    )

    state_path = processed_root / "synchronization/CELL_B/EXP_001/time_anchors.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["experiment_reference"]["experiment_start_time"] == "2024-02-01T00:00:00"


def test_time_anchor_cache_checks_sources_and_canonical_output(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
        "EXP_001,CELL_A,2024-01-01T00:00:00,,,\n",
        encoding="utf-8",
    )
    asset_manifest = manifest_root / "data_assets.csv"
    metadata_path = raw_root / "batteries/CELL_A/EXP_001/anchor.csv"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text("capture_start,2024-01-01T00:00:00\n", encoding="utf-8")
    asset_manifest.write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n"
        "U001,CELL_A,EXP_001,ultrasound,batteries/CELL_A/EXP_001/u001.txt,,,,,"
        "batteries/CELL_A/EXP_001/anchor.csv\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id="CELL_A", experiment_id="EXP_001"),
    )
    node = TimeAnchorNode()
    node.raw_root = raw_root
    node.run(plan, {}, SimpleNamespace(raw_root=raw_root, processed_root=processed_root))

    existing, reason = node.resolve_existing_output(plan, {}, processed_root)
    assert existing is not None
    assert "checksums verified" in reason
    assert Path(existing.manifest_path).name == "time_anchor_manifest.json"

    metadata_path.write_text("capture_start,2024-01-01T00:00:01\n", encoding="utf-8")
    existing, reason = node.resolve_existing_output(plan, {}, processed_root)
    assert existing is None
    assert "source inputs changed" in reason

    metadata_path.write_text("capture_start,2024-01-01T00:00:00\n", encoding="utf-8")
    canonical_path = processed_root / "synchronization/CELL_A/EXP_001/time_anchors.json"
    canonical_path.write_text("{}\n", encoding="utf-8")
    existing, reason = node.resolve_existing_output(plan, {}, processed_root)
    assert existing is None
    assert "OUTPUT_CHECKSUM_MISMATCH:time_anchors" in reason


def test_time_anchor_node_applies_only_the_pinned_accepted_validation(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\nEXP_001,CELL_B,,,,\n",
        encoding="utf-8",
    )
    (manifest_root / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n"
        "U001,CELL_B,EXP_001,ultrasound,batteries/CELL_B/EXP_001/u001.txt,,,,,\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    evidence_dir = raw_root / "batteries/CELL_B/EXP_001/timebase_evidence"
    evidence_dir.mkdir(parents=True)
    clock_log = evidence_dir / "clock-log.csv"
    review_log = evidence_dir / "pulse.csv"
    clock_log.write_bytes(b"clock evidence")
    review_log.write_bytes(b"independent pulse review")
    clock_ref = clock_log.relative_to(raw_root).as_posix()
    review_ref = review_log.relative_to(raw_root).as_posix()
    clock_sha = hashlib.sha256(clock_log.read_bytes()).hexdigest()
    review_sha = hashlib.sha256(review_log.read_bytes()).hexdigest()
    submitted = submit_timebase_validation(
        TimebaseValidationRequest(
            battery_id="CELL_B",
            experiment_id="EXP_001",
            timezone="Asia/Shanghai",
            anchors=[
                TimebaseAnchor(
                    asset_id="U001",
                    absolute_start_time="2024-02-01T09:00:00+08:00",
                    source_reference=clock_ref,
                    source_sha256=clock_sha,
                )
            ],
            evidence_refs=[clock_ref],
            maximum_allowed_error_s=0.5,
        ),
        processed_root=processed_root,
        verified_evidence={
            clock_ref: {"sha256": clock_sha, "size_bytes": clock_log.stat().st_size}
        },
    )
    validation_id = submitted["validation_id"]
    review_timebase_validation(
        "CELL_B",
        "EXP_001",
        validation_id,
        TimebaseReviewRequest(
            decision="ACCEPT",
            operator_identity="operator",
            rationale="verified from clock log",
            evidence_refs=[review_ref],
            error_by_asset_s={"U001": 0.1},
            ambiguity_free_assets=["U001"],
        ),
        processed_root=processed_root,
        verified_evidence={
            review_ref: {"sha256": review_sha, "size_bytes": review_log.stat().st_size}
        },
    )
    plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id="CELL_B", experiment_id="EXP_001"),
        parameters={"timebase_validation_id": validation_id},
    )
    requirements = TimeAnchorNode().requirements(plan, {})
    assert requirements.extra_match["timebase_validation_id"] == validation_id

    TimeAnchorNode().run(
        plan, {}, SimpleNamespace(raw_root=raw_root, processed_root=processed_root)
    )

    state = json.loads(
        (processed_root / "synchronization/CELL_B/EXP_001/time_anchors.json").read_text()
    )
    u001 = state["assets"][0]
    assert state["timebase_validation_id"] == validation_id
    assert state["validated_sync"] is False
    assert u001["anchor_status"] == "MANUALLY_ACCEPTED"
    assert u001["candidates"][0]["timezone_name"] == "Asia/Shanghai"
    assert (
        u001["evidence"][0]["source_ref"]
        == "batteries/CELL_B/EXP_001/timebase_evidence/clock-log.csv"
    )
    assert u001["evidence"][0]["source_sha256"] == clock_sha
    existing, reason = TimeAnchorNode().resolve_existing_output(plan, {}, processed_root)
    assert existing is None
    assert "evidence must be rechecked" in reason
    clock_log.write_bytes(b"changed after timebase review")
    with pytest.raises(TimebaseRegistryError, match="changed or is no longer available"):
        TimeAnchorNode().run(
            plan,
            {},
            SimpleNamespace(raw_root=raw_root, processed_root=processed_root),
        )
    clock_log.write_bytes(b"clock evidence")
    assert (
        list_timebase_validations(
            processed_root=processed_root, battery_id="CELL_B", experiment_id="EXP_001"
        )[0]["status"]
        == "RECOMPUTED_PROVISIONAL"
    )

    review_timebase_validation(
        "CELL_B",
        "EXP_001",
        validation_id,
        TimebaseReviewRequest(
            decision="REVOKE",
            operator_identity="operator",
            rationale="clock source withdrawn",
        ),
        processed_root=processed_root,
    )
    baseline_plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id="CELL_B", experiment_id="EXP_001"),
    )
    assert (
        TimeAnchorNode().requirements(baseline_plan, {}).extra_match["timebase_validation_id"]
        is None
    )
    TimeAnchorNode().run(
        baseline_plan,
        {},
        SimpleNamespace(raw_root=raw_root, processed_root=processed_root),
    )
    restored = json.loads(
        (processed_root / "synchronization/CELL_B/EXP_001/time_anchors.json").read_text()
    )
    assert restored["timebase_validation_id"] is None
    assert (
        list_timebase_validations(
            processed_root=processed_root, battery_id="CELL_B", experiment_id="EXP_001"
        )[0]["status"]
        == "REVOKED_PROVISIONAL"
    )

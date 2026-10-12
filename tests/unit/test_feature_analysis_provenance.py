from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.service import _feature_selection_status
from battery_workbench.api.workflow_context import build_workflow_context
from battery_workbench.feature_analysis.output import (
    verify_analysis_input_checksums,
    verify_analysis_output_checksums,
    write_analysis_payload,
)
from battery_workbench.feature_analysis.schemas import FeatureAnalysisSpec
from battery_workbench.orchestrator.nodes import (
    FeatureAnalysisNode,
    _assert_feature_selection_confirmation_matches,
)
from battery_workbench.orchestrator.schemas import ArtifactRef


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialize_analysis(root: Path) -> tuple[Path, dict[str, object], Path]:
    source = root / "features" / "CELL_TEST" / "EXP_TEST" / "features.parquet"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture source")
    spec = FeatureAnalysisSpec(
        analysis_mode="EXPLORATORY_FULL_DATA",
        target="soc_reference_percent",
        candidate_features=["amplitude_a_u"],
    )
    result = write_analysis_payload(
        spec=spec,
        analysis={
            "availability": ["amplitude_a_u"],
            "descriptive": [{"feature_name": "amplitude_a_u", "mean": 1.0}],
        },
        selection={
            "selection_id": "SEL::fixture",
            "analysis_mode": spec.analysis_mode.value,
            "selection_requested": False,
            "selected_features": ["amplitude_a_u"],
            "rejected_features": [],
            "selection_basis": "EXPLORATORY_ONLY",
            "selection_mode": "USER_EXPLICIT",
            "ml_safe_selection": False,
            "split_id": None,
            "fold_index": None,
            "policy": {},
            "policy_version": "test",
            "auto_removed_features": [],
            "commit_status": "NOT_REQUESTED",
        },
        battery_id="CELL_TEST",
        experiment_id="EXP_TEST",
        dataset_id="",
        output_root=root,
        input_files={"feature_table": source},
    )
    analysis_dir = Path(result["analysis_manifest"]).parent
    manifest = json.loads(Path(result["analysis_manifest"]).read_text(encoding="utf-8"))
    return analysis_dir, manifest, source


def test_analysis_writer_persists_and_verifies_input_and_output_provenance(
    tmp_path: Path,
) -> None:
    analysis_dir, manifest, source = _materialize_analysis(tmp_path)

    assert {"feature_selection.json", "analysis_schema.json"}.issubset(
        manifest["output_checksums"]
    )
    assert manifest["input_checksums"]["feature_table"] == _sha256(source)
    assert verify_analysis_output_checksums(analysis_dir, manifest) == ("CURRENT", [])
    assert verify_analysis_input_checksums(tmp_path, manifest) == ("CURRENT", [])


def test_analysis_output_tampering_is_integrity_blocked(tmp_path: Path) -> None:
    analysis_dir, manifest, _ = _materialize_analysis(tmp_path)
    (analysis_dir / "feature_selection.json").write_text("{}", encoding="utf-8")

    status, reasons = verify_analysis_output_checksums(analysis_dir, manifest)

    assert status == "INTEGRITY_BLOCKED"
    assert any("CHECKSUM_MISMATCH:feature_selection.json" in reason for reason in reasons)


def test_analysis_source_change_is_stale_and_missing_provenance_is_legacy(
    tmp_path: Path,
) -> None:
    _, manifest, source = _materialize_analysis(tmp_path)
    source.write_bytes(b"changed source")

    status, reasons = verify_analysis_input_checksums(tmp_path, manifest)
    assert status == "STALE_SOURCE"
    assert any("CHECKSUM_MISMATCH" in reason for reason in reasons)
    assert verify_analysis_input_checksums(tmp_path, {}) == (
        "LEGACY_UNVERIFIED",
        ["ANALYSIS_INPUT_PROVENANCE_MISSING"],
    )


def test_analysis_rejects_input_path_traversal(tmp_path: Path) -> None:
    status, reasons = verify_analysis_input_checksums(
        tmp_path,
        {"input_paths": {"source": "../outside.parquet"}, "input_checksums": {"source": "0" * 64}},
    )

    assert status == "INTEGRITY_BLOCKED"
    assert reasons == ["ANALYSIS_INPUT_PATH_INVALID:source"]


def test_ml_safe_reuse_is_bound_to_dataset_and_split_identity(tmp_path: Path) -> None:
    node = FeatureAnalysisNode()
    plan = SimpleNamespace(
        feature_analysis={
            "analysis_mode": "TRAIN_ONLY_ML_SAFE",
            "target": "soc_reference_percent",
            "candidate_features": ["amplitude_a_u"],
            "split_id": "SPLIT::new",
            "fold_index": 1,
        },
        split_id="SPLIT::new",
        fold_index=1,
        project=SimpleNamespace(battery_id="CELL_TEST", experiment_id="EXP_TEST"),
    )
    inputs = {
        "DATASET": ArtifactRef(
            artifact_type="DATASET",
            artifact_id="DS::new",
            battery_id="CELL_TEST",
            experiment_id="EXP_TEST",
            path=str(tmp_path),
            manifest_path=str(tmp_path / "dataset_manifest.json"),
        ),
    }

    requirements = node.requirements(plan, inputs)

    assert requirements.extra_match["dataset_id"] == "DS::new"
    assert requirements.extra_match["split_id"] == "SPLIT::new"
    assert requirements.extra_match["fold_index"] == 1


def test_exploratory_reuse_is_not_tied_to_an_unconsumed_dataset(tmp_path: Path) -> None:
    node = FeatureAnalysisNode()
    plan = SimpleNamespace(
        feature_analysis={
            "analysis_mode": "EXPLORATORY_FULL_DATA",
            "target": "soc_reference_percent",
            "candidate_features": ["amplitude_a_u"],
        },
        split_id=None,
        fold_index=None,
        project=SimpleNamespace(battery_id="CELL_TEST", experiment_id="EXP_TEST"),
    )
    requirements = node.requirements(
        plan,
        {
            "DATASET": ArtifactRef(
                artifact_type="DATASET",
                artifact_id="DS::unrelated",
                battery_id="CELL_TEST",
                experiment_id="EXP_TEST",
                path=str(tmp_path),
                manifest_path=str(tmp_path / "dataset_manifest.json"),
            ),
        },
    )

    assert "dataset_id" not in requirements.extra_match
    assert "split_id" not in requirements.extra_match


def _write_workflow_analysis(processed: Path, *, legacy: bool = False) -> Path:
    analysis_dir = (
        processed
        / "feature_analysis"
        / "CELL_TEST"
        / "EXP_TEST"
        / "EXPLORATORY"
        / "AN::workflow"
    )
    analysis_dir.mkdir(parents=True)
    selection = {"selected_features": ["amplitude_a_u"], "selection_basis": "EXPLICIT"}
    selection_path = analysis_dir / "feature_selection.json"
    schema_path = analysis_dir / "analysis_schema.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    schema_path.write_text("[]", encoding="utf-8")
    source = processed / "features" / "CELL_TEST" / "EXP_TEST" / "feature.parquet"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"workflow source")
    manifest: dict[str, object] = {
        "analysis_id": "AN::workflow",
        "analysis_mode": "EXPLORATORY_FULL_DATA",
        "target": "soc_reference_percent",
        "candidate_features": ["amplitude_a_u"],
        "selection": selection,
    }
    if not legacy:
        manifest.update(
            {
                "output_checksums": {
                    selection_path.name: _sha256(selection_path),
                    schema_path.name: _sha256(schema_path),
                },
                "input_paths": {"feature": source.relative_to(processed).as_posix()},
                "input_checksums": {"feature": _sha256(source)},
            }
        )
    (analysis_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return source


def test_workflow_context_hides_feature_selection_when_source_is_stale(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    source = _write_workflow_analysis(processed)
    source.write_bytes(b"replaced workflow source")

    context = build_workflow_context(processed, "CELL_TEST", "EXP_TEST")

    assert context["artifact_freshness"]["feature_analysis"] == "STALE"
    assert context["steps"]["FEATURES"]["status"] == "STALE"
    assert context["steps"]["FEATURES"]["committed"]["selected_features"] == []
    assert context["steps"]["FEATURES"]["blocking"]["required_action"] == (
        "CONFIGURE_FEATURES"
    )
    assert context["steps"]["PREVIEW"]["status"] == "BLOCKED"


def test_workflow_context_marks_legacy_feature_analysis_unverified(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    _write_workflow_analysis(processed, legacy=True)

    context = build_workflow_context(processed, "CELL_TEST", "EXP_TEST")

    assert context["artifact_freshness"]["feature_analysis"] == "LEGACY"
    assert context["steps"]["FEATURES"]["status"] == "STALE"
    assert context["steps"]["FEATURES"]["committed"]["selected_features"] == []


def test_workflow_context_integrity_blocks_tampered_analysis_output(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    _write_workflow_analysis(processed)
    selection_path = next(processed.rglob("feature_selection.json"))
    selection_path.write_text("{}", encoding="utf-8")

    context = build_workflow_context(processed, "CELL_TEST", "EXP_TEST")

    assert context["artifact_freshness"]["feature_analysis"] == "INTEGRITY_BLOCKED"
    assert context["steps"]["FEATURES"]["status"] == "BLOCKED"
    assert context["steps"]["FEATURES"]["committed"] is None


def test_feature_analysis_detail_and_list_do_not_claim_legacy_output_is_available(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    analysis_dir = (
        processed
        / "feature_analysis"
        / "CELL_TEST"
        / "EXP_TEST"
        / "EXPLORATORY"
        / "AN::legacy"
    )
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "analysis_id": "AN::legacy",
                "analysis_mode": "EXPLORATORY_FULL_DATA",
                "target": "soc_reference_percent",
                "candidate_features": ["amplitude_a_u"],
                "selection": {"selected_features": ["amplitude_a_u"]},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=processed,
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)

    detail = client.get("/api/v1/feature-analyses/AN::legacy")
    listing = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/feature-analyses")

    assert detail.status_code == 200, detail.text
    detail_data = detail.json()["data"]
    assert detail_data["status"] == "LEGACY_UNVERIFIED"
    assert "selected_features" not in detail_data
    assert listing.status_code == 200, listing.text
    item = listing.json()["data"]["analyses"][0]
    assert item["status"] == "LEGACY_UNVERIFIED"
    assert item["availability"] == "STALE"
    assert item["selected_features"] == []
    assert item["selection_status"] == "NOT_ASSESSED"


def test_current_feature_analysis_exposes_selection_spec_for_fold_status(tmp_path: Path) -> None:
    analysis_dir, manifest, _source = _materialize_analysis(tmp_path / "processed")
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)

    detail = client.get(f"/api/v1/feature-analyses/{manifest['analysis_id']}")
    listing = client.get("/api/v1/experiments/CELL_TEST/EXP_TEST/feature-analyses")

    assert detail.status_code == 200, detail.text
    detail_data = detail.json()["data"]
    assert detail_data["methods"] == manifest["methods"]
    assert detail_data["selection_policy"] == manifest["selection"]["policy"]
    assert detail_data["selection_policy_version"] == manifest["selection"]["policy_version"]
    assert listing.status_code == 200, listing.text
    listed = next(
        item for item in listing.json()["data"]["analyses"]
        if item["analysis_id"] == analysis_dir.name
    )
    assert listed["methods"] == manifest["methods"]
    assert listed["selection_policy"] == manifest["selection"]["policy"]
    assert listed["selection_status"] == "NOT_REQUESTED"


def test_selection_status_uses_commit_state_not_selected_feature_presence() -> None:
    assert _feature_selection_status({
        "commit_status": "NOT_REQUESTED",
        "selected_features": ["amplitude_a_u"],
    }) == "NOT_REQUESTED"
    assert _feature_selection_status({"commit_status": "WAITING_FOR_USER"}) == "AWAITING_CONFIRMATION"
    assert _feature_selection_status({"commit_status": "NO_SELECTION"}) == "NO_SELECTION"
    assert _feature_selection_status({"commit_status": "CONFIRMED"}) == "CONFIRMED"
    assert _feature_selection_status({"selected_features": ["amplitude_a_u"]}) == "NOT_ASSESSED"


def test_feature_analysis_confirmation_must_match_recomputed_proposal() -> None:
    with pytest.raises(ValueError, match="does not match the recomputed feature selection"):
        _assert_feature_selection_confirmation_matches(
            {"confirmed": True, "selection_id": "SEL::stale"},
            {"selection_id": "SEL::computed"},
        )

    _assert_feature_selection_confirmation_matches(
        {"confirmed": True, "selection_id": "SEL::computed"},
        {"selection_id": "SEL::computed"},
    )

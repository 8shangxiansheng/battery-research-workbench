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

import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.workflow_context import (
    _alignment_step,
    _split_output_integrity_reasons,
    build_workflow_context,
)

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
B, E = "CELL_001", "EXP_001"


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()

has_real = (PROCESSED / "multimodal" / B / E / "measurement_events.parquet").exists()
has_cell210 = (PROCESSED / "multimodal" / "CELL_210" / "EXP_015").exists()

_STEPS = ("TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT")
_STATUS_VOCAB = {
    "COMPLETE",
    "CURRENT",
    "READY",
    "BLOCKED",
    "STALE",
    "NOT_STARTED",
    "LIMITED",
}
_FRESHNESS_VOCAB = {
    "CURRENT", "STALE", "LEGACY", "SUPERSEDED", "MISSING", "INTEGRITY_BLOCKED"
}


def test_alignment_step_blocks_legacy_time_anchor_without_current_provenance(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    sync_dir = processed / "synchronization/CELL_A/EXP_A"
    sync_dir.mkdir(parents=True)
    (sync_dir / "time_anchors.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "anchor_version": "0.1.0",
                "timebase_validation_id": None,
                "assets": [],
            }
        ),
        encoding="utf-8",
    )
    events_path = processed / "multimodal/CELL_A/EXP_A/measurement_events.parquet"
    events_path.parent.mkdir(parents=True)
    events_path.write_bytes(b"placeholder")

    result = _alignment_step(processed, "CELL_A", "EXP_A", raw)

    assert result["status"] == "BLOCKED"
    assert result["blocking"]["blocking_code"] == "ALIGNMENT_ARTIFACT_INTEGRITY_INVALID"
    assert result["blocking"]["required_action"] == "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT"
    assert "需要重建时间基准与下游同步链" in result["blocking"]["blocking_message"]
    assert "TIME_ANCHOR_MANIFEST_MISSING" in result["blocking"]["scientific_reason"]


def test_split_output_integrity_detects_changed_assignment_bytes(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    split_dir = processed / "splits/CELL_A/EXP_A/DS::1/SPLIT::1"
    split_dir.mkdir(parents=True)
    outputs = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    checksums = {}
    for key, filename in outputs.items():
        path = split_dir / filename
        path.write_bytes(f"original {key}".encode())
        checksums[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = split_dir / "split_manifest.json"
    manifest = {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "dataset_id": "DS::1",
        "split_id": "SPLIT::1",
        "output_checksums": checksums,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert _split_output_integrity_reasons(
        processed, manifest, manifest_path, "CELL_A", "EXP_A"
    ) == []

    (split_dir / "split_assignments.parquet").write_bytes(b"tampered roles")
    assert _split_output_integrity_reasons(
        processed, manifest, manifest_path, "CELL_A", "EXP_A"
    ) == ["SPLIT_OUTPUT_CHECKSUM_MISMATCH:split_assignments"]


@pytest.mark.parametrize("tampered_artifact", ["split", "dataset", "model"])
def test_workflow_context_blocks_when_split_or_model_output_is_tampered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_artifact: str,
) -> None:
    from battery_workbench.api import workflow_context

    processed = tmp_path / "processed"
    dataset_id, split_id = "DS::current", "SPLIT::current"
    dataset_path = processed / "datasets/CELL_A/EXP_A/SOC" / dataset_id / "dataset_manifest.json"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("{}", encoding="utf-8")
    current_dataset_path = dataset_path.parent / "dataset.parquet"
    import pandas as pd

    pd.DataFrame(
        {
            "measurement_event_id": ["ME::1"],
            "cycle_group_id": ["CG::1"],
        }
    ).to_parquet(current_dataset_path, index=False)
    split_dir = processed / "splits/CELL_A/EXP_A" / dataset_id / split_id
    split_dir.mkdir(parents=True)
    output_names = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    checksums = {}
    for key, filename in output_names.items():
        output = split_dir / filename
        if key == "split_assignments":
            pd.DataFrame(
                {
                    "measurement_event_id": ["ME::1"],
                    "cycle_group_id": ["CG::1"],
                    "fold": ["fold1"],
                    "role": ["TRAIN"],
                    "strategy": ["TRAIN_ONLY"],
                    "dataset_id": [dataset_id],
                    "split_id": [split_id],
                }
            ).to_parquet(output, index=False)
        else:
            output.write_bytes(f"{key} contents".encode())
        checksums[key] = hashlib.sha256(output.read_bytes()).hexdigest()
    split_manifest = {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "dataset_id": dataset_id,
        "split_id": split_id,
        "readiness_status": "READY_FOR_LIMITED_EVALUATION",
        "strategy": "TRAIN_ONLY",
        "split_unit": "CYCLE",
        "group_column": "cycle_group_id",
        "group_counts": {"CG::1": 1},
        "group_count": 1,
        "role_semantics": {
            "held_out_role": "",
            "independent_validation_groups": None,
            "independent_test_groups": None,
            "three_way_structure_present": False,
            "held_out_target_usage": "NOT_APPLICABLE",
            "note": "",
        },
        "row_count": 1,
        "fold_count": 1,
        "source_checksums": {
            "dataset_parquet": hashlib.sha256(current_dataset_path.read_bytes()).hexdigest(),
            "dataset_manifest": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        },
        "output_checksums": checksums,
    }
    manifest_path = split_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")
    if tampered_artifact == "split":
        (split_dir / "split_assignments.parquet").write_bytes(b"changed roles")
    elif tampered_artifact == "dataset":
        current_dataset_path.write_bytes(b"new Dataset bytes under unchanged ID")
    else:
        model_id = "MODEL::current"
        model_dir = (
            processed
            / "models/CELL_A/EXP_A"
            / dataset_id
            / split_id
            / model_id
        )
        model_dir.mkdir(parents=True)
        model_outputs = {
            "model": ("model.joblib", b"serialized estimator"),
            "held_out_predictions": (
                "held_out_predictions.parquet",
                b"held-out predictions",
            ),
        }
        model_checksums = {}
        for key, (filename, content) in model_outputs.items():
            output = model_dir / filename
            output.write_bytes(content)
            model_checksums[key] = hashlib.sha256(content).hexdigest()
        (model_dir / "model_manifest.json").write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "dataset_id": dataset_id,
                    "split_id": split_id,
                    "output_checksums": model_checksums,
                }
            ),
            encoding="utf-8",
        )
        (model_dir / "held_out_predictions.parquet").write_bytes(b"changed predictions")

    monkeypatch.setattr(
        workflow_context,
        "_fs_state",
        lambda *_args: {"sampling_rate_verified": True, "sampling_rate_hz": 1.0},
    )
    monkeypatch.setattr(workflow_context, "_pending_submissions", lambda *_args: [])
    monkeypatch.setattr(
        workflow_context,
        "_target_step",
        lambda *_args: {"status": "COMPLETE", "committed": {"target_id": "soc"}},
    )
    monkeypatch.setattr(
        workflow_context,
        "_alignment_step",
        lambda *_args: {"status": "COMPLETE", "committed": {"total_frames": 1}},
    )
    dataset = {
        "dataset_id": dataset_id,
        "dataset_status": "READY_FOR_SPLIT",
        "target_name": "reference_soc_percent",
        "selected_features": ["amplitude_a_u"],
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
    }
    monkeypatch.setattr(
        workflow_context, "_dataset_latest", lambda *_args: (dataset, dataset_path)
    )
    monkeypatch.setattr(
        workflow_context,
        "_freshness_of_dataset",
        lambda *_args, **_kwargs: {"status": "CURRENT", "reasons": []},
    )
    monkeypatch.setattr(
        workflow_context,
        "_feature_analysis_latest",
        lambda *_args: (None, None),
    )

    result = build_workflow_context(processed, "CELL_A", "EXP_A")

    if tampered_artifact == "split":
        assert result["steps"]["SPLIT"]["status"] == "BLOCKED"
        assert result["steps"]["SPLIT"]["committed"] is None
        assert result["steps"]["SPLIT"]["blocking"]["blocking_code"] == (
            "SPLIT_ARTIFACT_INTEGRITY_INVALID"
        )
        assert result["steps"]["MODELS"]["blocking"]["blocking_code"] == (
            "SPLIT_ARTIFACT_INTEGRITY_INVALID"
        )
        assert result["artifact_freshness"]["split"] == "INTEGRITY_BLOCKED"
    elif tampered_artifact == "dataset":
        assert result["steps"]["SPLIT"]["status"] == "STALE"
        assert result["steps"]["SPLIT"]["blocking"]["blocking_code"] == (
            "SPLIT_DATASET_SOURCE_CHANGED"
        )
        assert result["steps"]["MODELS"]["blocking"]["blocking_code"] == (
            "SPLIT_DATASET_SOURCE_CHANGED"
        )
        assert result["artifact_freshness"]["split"] == "STALE"
    else:
        assert result["steps"]["SPLIT"]["status"] == "COMPLETE"
        assert result["steps"]["MODELS"]["status"] == "BLOCKED"
        assert result["steps"]["MODELS"]["blocking"]["blocking_code"] == (
            "MODEL_ARTIFACT_INTEGRITY_INVALID"
        )
        assert result["steps"]["REPORT"]["blocking"]["blocking_code"] == (
            "MODEL_ARTIFACT_INTEGRITY_INVALID"
        )
        assert result["artifact_freshness"]["models"] == "INTEGRITY_BLOCKED"


def _sandbox(tmp_path: Path) -> Path:
    """Sandbox processed root: copy compact provenance inputs; symlink heavy artifacts."""
    import shutil

    sandbox = tmp_path / "processed"
    sandbox.mkdir()
    for rel in (
        "electrical",
        "ultrasound",
        "parameters",
        "multimodal",
        "labels",
        "features_physical",
        "features",
        "datasets",
        "models",
        "splits",
        "feature_analysis",
        "gate_calibrations",
        "artifacts",
        "assistant_sessions",
        "parameter_submissions",
        "synchronization",
        "measurement_events",
    ):
        src = PROCESSED / rel
        if src.exists():
            if rel in {"features", "labels"}:
                shutil.copytree(src, sandbox / rel)
            elif rel in {"electrical", "ultrasound"}:
                # Parser manifests must be regular files inside this sandbox
                # because production validates their processed-root confinement.
                destination = sandbox / rel
                destination.mkdir()
                for battery_dir in src.iterdir():
                    if not battery_dir.is_dir():
                        continue
                    battery_destination = destination / battery_dir.name
                    battery_destination.mkdir()
                    for experiment_dir in battery_dir.iterdir():
                        if not experiment_dir.is_dir():
                            continue
                        experiment_destination = battery_destination / experiment_dir.name
                        experiment_destination.mkdir()
                        for artifact in experiment_dir.iterdir():
                            target = experiment_destination / artifact.name
                            if artifact.name == "parser_manifest.json" or artifact.suffix == ".parquet":
                                shutil.copy2(artifact, target)
                            elif artifact.is_dir():
                                shutil.copytree(artifact, target)
                            else:
                                target.symlink_to(artifact.resolve())
            elif rel in {"multimodal", "synchronization"}:
                # Integrity checks require derived dependencies to resolve
                # within this sandbox root, not through links to real data.
                destination = sandbox / rel
                destination.mkdir()
                for battery_dir in src.iterdir():
                    if battery_dir.name != B or not battery_dir.is_dir():
                        (destination / battery_dir.name).symlink_to(
                            battery_dir, target_is_directory=True
                        )
                        continue
                    battery_destination = destination / B
                    battery_destination.mkdir()
                    for experiment_dir in battery_dir.iterdir():
                        if experiment_dir.name != E or not experiment_dir.is_dir():
                            (battery_destination / experiment_dir.name).symlink_to(
                                experiment_dir, target_is_directory=True
                            )
                            continue
                        experiment_destination = battery_destination / E
                        experiment_destination.mkdir()
                        for artifact in experiment_dir.iterdir():
                            if artifact.is_file() and artifact.suffix in {".parquet", ".json"}:
                                shutil.copy2(artifact, experiment_destination / artifact.name)
            elif rel == "datasets":
                # Keep the workflow-context contract tests deterministic even
                # after interactive acceptance creates newer local datasets.
                # These are the stable RC1 materialized fixture identities.
                dst = sandbox / rel / B / E / "SOC"
                for dataset_id in ("DS::83013a61b316f3489093b358", "DS::6a3142e5186fc684964ff09e"):
                    fixture = src / B / E / "SOC" / dataset_id
                    if fixture.is_dir():
                        (dst / dataset_id).parent.mkdir(parents=True, exist_ok=True)
                        import shutil

                        shutil.copytree(fixture, dst / dataset_id)
            elif rel == "splits":
                # Split integrity is verified against files confined to this
                # processed root; do not let the test read through a symlink.
                shutil.copytree(src, sandbox / rel)
            else:
                (sandbox / rel).symlink_to(src)
    return sandbox


def test_workflow_blocks_when_registered_raw_asset_changed(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    battery_id, experiment_id = "CELL_X", "EXP_X"
    relative_path = "batteries/CELL_X/EXP_X/electrical/source.xlsx"
    source_path = raw / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"original xlsx")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assets_manifest = raw / "manifests" / "data_assets.csv"
    assets_manifest.parent.mkdir(parents=True)
    assets_manifest.write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path\n"
        f"E_X,{battery_id},{experiment_id},electrical,{relative_path}\n",
        encoding="utf-8",
    )
    parser_dir = processed / "electrical" / battery_id / experiment_id
    parser_dir.mkdir(parents=True)
    (parser_dir / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "source_sha256": {"E_X": digest},
                "source_asset_details": [
                    {"asset_id": "E_X", "relative_path": relative_path}
                ],
            }
        ),
        encoding="utf-8",
    )
    source_path.write_bytes(b"replaced xlsx")

    context = build_workflow_context(
        processed,
        battery_id,
        experiment_id,
        raw_root=raw,
    )

    assert context["current_step"] == "TARGET"
    assert set(context["step_statuses"].values()) == {"BLOCKED"}
    assert (
        context["steps"]["TARGET"]["blocking"]["blocking_code"]
        == "SOURCE_PROVENANCE_INVALID"
    )


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
        real = link.resolve() if link.is_symlink() else link

        def _ign(root: str, names: list[str]) -> set[str]:
            drop = {n for n in names if any(x in str(Path(root) / n) for x in exclude)}
            return drop

        filtered = sandbox / f"{rel}-filtered"
        shutil.copytree(real, filtered, ignore=_ign)
        if link.is_symlink():
            link.unlink()
        else:
            shutil.rmtree(link)
        filtered.rename(link)
    art = sandbox / "artifacts"
    art_real = art.resolve()
    art.unlink()
    shutil.copytree(
        art_real,
        art,
        ignore=shutil.ignore_patterns(
            *[f"{x}*" for x in exclude if x.startswith("REPORT::")] or ["__none__"]
        ),
    )
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
    def test_invalid_parser_provenance_blocks_workflow_context(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "processed"
        manifest = sandbox / "electrical" / B / E / "parser_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{", encoding="utf-8")

        d = build_workflow_context(sandbox, B, E)

        assert set(d["step_statuses"].values()) == {"BLOCKED"}
        assert d["steps"]["TARGET"]["blocking"]["blocking_code"] == (
            "SOURCE_PROVENANCE_INVALID"
        )
        assert d["recommended_next_action"]["action_id"] == (
            "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        )
        assert d["recommended_next_action"]["route"].endswith("/runs")
        assert d["artifact_freshness"] == {
            "feature_analysis": "INTEGRITY_BLOCKED",
            "dataset": "INTEGRITY_BLOCKED",
            "split": "INTEGRITY_BLOCKED",
            "models": "INTEGRITY_BLOCKED",
            "report": "INTEGRITY_BLOCKED",
        }
        assert "dataset_id" not in str(d["steps"])
        assert d["meta"]["source_integrity_status"] == "INTEGRITY_BLOCKED"

    def test_w02_dto_schema(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        assert d["schema_version"] == "workflow-context/1.0"
        for section in (
            "battery_id",
            "experiment_id",
            "current_step",
            "step_statuses",
            "steps",
            "recommended_next_action",
            "pending_action",
            "artifact_freshness",
            "scientific_context",
            "assistant_context",
            "typed_actions",
            "meta",
        ):
            assert section in d, section
        assert d["meta"]["read_only"] is True
        assert d["meta"]["no_recomputation"] is True
        # §3 scientific context fields
        sc = d["scientific_context"]
        for field in (
            "experiment_id",
            "battery_id",
            "target_id",
            "target_status",
            "alignment_status",
            "eligible_count",
            "excluded_count",
            "selected_feature_locators",
            "feature_selection_source",
            "feature_selection_status",
            "dataset_id",
            "dataset_status",
            "split_id",
            "split_status",
            "model_status",
            "report_id",
            "report_status",
            "pending_action",
            "blocking_reason",
            "recommended_next_action",
            "artifact_freshness",
            "limitations",
        ):
            assert field in sc, field

    def test_w04_w05_step_statuses_vocabulary_and_order(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        assert tuple(d["step_statuses"]) == _STEPS
        for s, status in d["step_statuses"].items():
            assert status in _STATUS_VOCAB, (s, status)
        # Real fixture datasets point at superseded label checksums; historical
        # split/model/report artifacts must not satisfy the current workflow.
        assert d["current_step"] == "ALIGNMENT"
        assert d["step_statuses"]["TARGET"] == "COMPLETE"
        assert d["step_statuses"]["ALIGNMENT"] == "COMPLETE"
        # The latest persisted analysis manifest in this environment is an
        # integrity fixture with no committed feature selection. Do not let
        # stale Dataset selections make the Features step look complete.
        assert d["step_statuses"]["FEATURES"] == "BLOCKED"
        assert d["step_statuses"]["DATASET"] == "STALE"
        assert d["step_statuses"]["SPLIT"] == "STALE"
        assert d["artifact_freshness"]["dataset"] == "STALE"
        assert d["recommended_next_action"]["action_id"] == "CONFIGURE_FEATURES"
        # 3995 eligible / 4 excluded from canonical artifacts
        assert d["scientific_context"]["eligible_count"] == 3995
        assert d["scientific_context"]["excluded_count"] == 4

    def test_target_and_alignment_block_when_measurement_event_output_is_tampered(
        self, tmp_path: Path
    ) -> None:
        sandbox = _sandbox(tmp_path)
        events = sandbox / "multimodal" / B / E / "measurement_events.parquet"
        events.write_bytes(b"tampered")

        context = build_workflow_context(sandbox, B, E)

        assert context["steps"]["TARGET"]["status"] == "BLOCKED"
        assert context["steps"]["ALIGNMENT"]["status"] == "BLOCKED"
        assert context["steps"]["TARGET"]["blocking"]["blocking_code"] == (
            "TARGET_ARTIFACT_INTEGRITY_INVALID"
        )
        assert context["step_statuses"]["TARGET"] == "BLOCKED"

    def test_target_blocks_when_reference_soc_label_output_is_tampered(
        self, tmp_path: Path
    ) -> None:
        sandbox = _sandbox(tmp_path)
        labels = sandbox / "labels" / B / E / "event_labels.parquet"
        labels.write_bytes(b"tampered")

        context = build_workflow_context(sandbox, B, E)

        assert context["steps"]["TARGET"]["status"] == "BLOCKED"
        assert context["steps"]["TARGET"]["blocking"]["blocking_code"] == (
            "TARGET_ARTIFACT_INTEGRITY_INVALID"
        )
        assert context["step_statuses"]["TARGET"] == "BLOCKED"

    def test_w05_blocking_structured(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        for s, step in d["steps"].items():
            blocking = step.get("blocking")
            if blocking is not None:
                assert set(blocking) == {
                    "blocking_code",
                    "blocking_message",
                    "required_action",
                    "scientific_reason",
                }, s

    def test_w10_dataset_committed_materialized_only(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["DATASET"]["committed"]
        assert committed is not None
        assert committed["dataset_status"] not in ("SPEC_PENDING_RUN",)
        # spec-pending manifests exist in the fixture but are drafts, never committed
        # RC1: CURRENT chain dataset (canonical envelope-peak TOF predictors)
        assert committed["dataset_id"] == "DS::83013a61b316f3489093b358"
        assert committed["dataset_status"] == "STALE_SOURCE"
        assert committed["freshness_reasons"] == [
            "FEATURE_SET_MANIFEST_PROVENANCE_MISSING",
            "FEATURE_SET_MANIFEST_IDENTITY_MISMATCH",
            "FEATURE_SET_MANIFEST_OUTPUT_MISMATCH",
            "FEATURE_SET_ANALYSIS_SLICE_MISSING",
            "FEATURE_SET_WAVEFORM_STORE_CHECKSUM_MISSING_OR_INVALID",
            "LABEL_SOURCE_CHECKSUM_MISMATCH",
            "LABEL_SET_MANIFEST_PROVENANCE_MISSING",
            "LABEL_SET_MANIFEST_IDENTITY_MISMATCH",
            "CANONICAL_TOF_PROVENANCE_MISSING",
        ]
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
        assert d["steps"]["SPLIT"]["status"] == "STALE"

    def test_w12_models_grouped_by_dataset(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["MODELS"]["committed"]
        assert committed is None
        assert d["steps"]["MODELS"]["status"] == "BLOCKED"
        assert d["steps"]["MODELS"]["blocking"]["blocking_code"] == "DATASET_STALE_SOURCE"
        assert d["artifact_freshness"]["models"] == "STALE"

    def test_w13_report_latest(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        committed = d["steps"]["REPORT"]["committed"]
        assert committed is None
        assert d["steps"]["REPORT"]["status"] == "BLOCKED"
        assert d["steps"]["REPORT"]["blocking"]["blocking_code"] == "DATASET_STALE_SOURCE"
        assert d["artifact_freshness"]["report"] == "STALE"

    def test_w21_stale_chain(self, tmp_path: Path) -> None:
        # sandbox chain excluding the RC1 CURRENT ids → legacy-only root
        d = build_workflow_context(
            _legacy_chain_sandbox(
                tmp_path,
                exclude=("DS::83013a61", "SPLIT::23ebb24f", "REPORT::5b6cf84d"),
            ),
            B,
            E,
        )
        f = d["artifact_freshness"]
        assert f["dataset"] == "STALE"
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
        import hashlib

        import pandas as pd

        sandbox = tmp_path / "processed"
        sandbox.mkdir()
        # Build one internally consistent current dataset so this test reaches
        # the split readiness gate rather than the source-staleness gate.
        dataset_id = "DS::6a3142e5186fc684964ff09e"
        dataset_dir = sandbox / "datasets" / B / E / "SOC" / dataset_id
        dataset_dir.mkdir(parents=True)
        dataset_path = dataset_dir / "dataset.parquet"
        pd.DataFrame(
            {
                "measurement_event_id": ["ME::1"],
                "battery_id": [B],
                "experiment_id": [E],
                "cycle_group_id": ["CG::1"],
                "soc_reference_percent": [50.0],
                "amplitude_a_u": [1.0],
            }
        ).to_parquet(dataset_path, index=False)
        feature_dir = sandbox / "features" / B / E / "FS::workflow-test"
        feature_dir.mkdir(parents=True)
        feature_path = feature_dir / "ultrasound_features.parquet"
        pd.DataFrame({"measurement_event_id": ["ME::1"], "amplitude_a_u": [1.0]}).to_parquet(
            feature_path, index=False
        )
        definitions_path = feature_dir / "feature_definitions.json"
        definitions_path.write_text('{"features":["amplitude_a_u"]}', encoding="utf-8")
        label_dir = sandbox / "labels" / B / E
        label_dir.mkdir(parents=True)
        label_path = label_dir / "event_labels.parquet"
        pd.DataFrame(
            {"measurement_event_id": ["ME::1"], "soc_reference_percent": [50.0]}
        ).to_parquet(label_path, index=False)
        cycle_label_path = label_dir / "cycle_labels.parquet"
        pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [100.0]}).to_parquet(
            cycle_label_path, index=False
        )

        def sha256(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        analysis_slice_path = sandbox / "analysis_slices" / B / E / "AS::workflow-test.parquet"
        analysis_slice_path.parent.mkdir(parents=True)
        analysis_slice_path.write_bytes(b"analysis slice")
        waveform_store_path = sandbox / "waveform_inputs" / B / E / "waveforms.zarr"
        waveform_store_path.mkdir(parents=True)
        (waveform_store_path / "chunk.bin").write_bytes(b"waveform")
        feature_manifest_path = feature_dir / "feature_set_manifest.json"
        feature_manifest_path.write_text(
            json.dumps(
                {
                    "feature_set_id": "FS::workflow-test",
                    "battery_id": B,
                    "experiment_id": E,
                    "analysis_slice_id": "AS::workflow-test",
                    "analysis_slice_path": str(analysis_slice_path.relative_to(sandbox)),
                    "analysis_slice_checksum": sha256(analysis_slice_path),
                    "waveform_store_path": str(waveform_store_path.relative_to(sandbox)),
                    "waveform_store_checksum": tree_sha256(waveform_store_path),
                    "output_paths": {
                        "features": str(feature_path.relative_to(sandbox)),
                        "definitions": str(definitions_path.relative_to(sandbox)),
                    },
                    "output_checksums": {
                        "features": sha256(feature_path),
                        "definitions": sha256(definitions_path),
                    },
                }
            ),
            encoding="utf-8",
        )
        label_manifest_path = label_dir / "label_manifest.json"
        label_manifest_path.write_text(
            json.dumps(
                {
                    "label_set_id": "LB::workflow-test",
                    "battery_id": B,
                    "experiment_id": E,
                    "output_paths": {
                        "event_labels": str(label_path.relative_to(sandbox)),
                        "cycle_labels": str(cycle_label_path.relative_to(sandbox)),
                    },
                    "output_checksums": {
                        "event_labels": sha256(label_path),
                        "cycle_labels": sha256(cycle_label_path),
                    },
                }
            ),
            encoding="utf-8",
        )

        (dataset_dir / "dataset_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_id": dataset_id,
                    "dataset_family": "SOC",
                    "dataset_status": "READY_WITH_LIMITATIONS",
                    "battery_id": B,
                    "experiment_id": E,
                    "target_name": "soc_reference_percent",
                    "target_column": "soc_reference_percent",
                    "predictor_columns": ["amplitude_a_u"],
                    "selected_features": ["amplitude_a_u"],
                    "feature_set_id": "FS::workflow-test",
                    "feature_set_path": str(feature_path.relative_to(sandbox)),
                    "feature_set_checksum": sha256(feature_path),
                    "feature_set_manifest_path": str(
                        feature_manifest_path.relative_to(sandbox)
                    ),
                    "feature_set_manifest_checksum": sha256(feature_manifest_path),
                    "label_set_id": "LB::workflow-test",
                    "label_set_path": str(label_path.relative_to(sandbox)),
                    "label_set_checksum": sha256(label_path),
                    "label_set_manifest_path": str(label_manifest_path.relative_to(sandbox)),
                    "label_set_manifest_checksum": sha256(label_manifest_path),
                    "output_checksum": sha256(dataset_path),
                }
            ),
            encoding="utf-8",
        )
        import shutil

        bad_split_src = next(
            p
            for p in (PROCESSED / "splits" / B / E).rglob("split_manifest.json")
            if json.loads(p.read_text(encoding="utf-8")).get("readiness_status")
            == "NOT_READY_FOR_MODEL_EVALUATION"
        )
        bad = json.loads(bad_split_src.read_text(encoding="utf-8"))
        bad["dataset_id"] = "DS::6a3142e5186fc684964ff09e"
        bad["source_checksums"] = {
            "dataset_parquet": sha256(dataset_path),
            "dataset_manifest": sha256(dataset_dir / "dataset_manifest.json"),
        }
        bad["group_column"] = "cycle_group_id"
        bad["split_unit"] = "CYCLE"
        bad["strategy"] = "TRAIN_ONLY"
        bad["group_counts"] = {"CG::1": 1}
        bad["group_count"] = 1
        bad["role_semantics"] = {
            "held_out_role": "",
            "independent_validation_groups": None,
            "independent_test_groups": None,
            "three_way_structure_present": False,
            "held_out_target_usage": "NOT_APPLICABLE",
            "note": "",
        }
        bad["row_count"] = 1
        bad["fold_count"] = 1
        bad_dir = sandbox / "splits" / B / E / "DS::6a3142e5186fc684964ff09e" / bad["split_id"]
        bad_dir.mkdir(parents=True)
        (bad_dir / "split_manifest.json").write_text(json.dumps(bad, indent=2), encoding="utf-8")
        for output_name in (
            "split_assignments.parquet",
            "leakage_audit.json",
            "evaluation_readiness.json",
        ):
            shutil.copy2(bad_split_src.parent / output_name, bad_dir / output_name)
        pd.DataFrame(
            {
                "measurement_event_id": ["ME::1"],
                "cycle_group_id": ["CG::1"],
                "fold": ["fold1"],
                "role": ["TRAIN"],
                "strategy": ["TRAIN_ONLY"],
                "dataset_id": [dataset_id],
                "split_id": [bad["split_id"]],
            }
        ).to_parquet(bad_dir / "split_assignments.parquet", index=False)
        bad["output_checksums"] = {
            key: sha256(bad_dir / filename)
            for key, filename in (
                ("split_assignments", "split_assignments.parquet"),
                ("leakage_audit", "leakage_audit.json"),
                ("evaluation_readiness", "evaluation_readiness.json"),
            )
        }
        (bad_dir / "split_manifest.json").write_text(
            json.dumps(bad, indent=2), encoding="utf-8"
        )
        # symlink canonical event/label sources for target/alignment steps
        for rel, sub in (("multimodal", None), ("synchronization", None)):
            src = PROCESSED / rel / B / E
            if src.exists():
                target = sandbox / rel / B / E
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(src)
        shutil.rmtree(
            sandbox / "splits" / B / E / "DS::c10c43b1890949aff0e94663", ignore_errors=True
        )

        d = build_workflow_context(sandbox, B, E)
        assert d["steps"]["SPLIT"]["status"] == "LIMITED"
        assert d["steps"]["MODELS"]["status"] == "BLOCKED"
        assert d["steps"]["MODELS"]["blocking"]["blocking_code"] == "VALID_SPLIT_REQUIRED"

    def test_historical_models_and_report_are_stale_for_new_dataset(self, tmp_path: Path) -> None:
        """Historical metrics must not satisfy the latest dataset's workflow gate."""
        import hashlib

        import pandas as pd

        sandbox = tmp_path / "processed"
        event_dir = sandbox / "multimodal" / B / E
        label_dir = sandbox / "labels" / B / E
        dataset_dir = sandbox / "datasets" / B / E / "SOC" / "DS::AUDIT-CURRENT"
        old_model_dir = sandbox / "models" / B / E / "DS::OLD" / "SPLIT::OLD" / "MODEL::OLD"
        report_dir = sandbox / "artifacts" / B / E / "reports" / "REPORT::OLD"
        for directory in (event_dir, label_dir, dataset_dir, old_model_dir, report_dir):
            directory.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "measurement_event_id": "ME::1",
                    "analysis_eligible": True,
                    "match_status": "MATCHED_UNIQUE",
                }
            ]
        ).to_parquet(event_dir / "measurement_events.parquet", index=False)
        pd.DataFrame([{"measurement_event_id": "ME::1", "soc_reference_percent": 50.0}]).to_parquet(
            label_dir / "event_labels.parquet", index=False
        )
        cycle_label_path = label_dir / "cycle_labels.parquet"
        pd.DataFrame({"cycle": [1], "soh_capacity_reference_percent": [100.0]}).to_parquet(
            cycle_label_path, index=False
        )
        feature_dir = sandbox / "features" / B / E / "FS::fresh-test"
        feature_dir.mkdir(parents=True)
        feature_path = feature_dir / "ultrasound_features.parquet"
        pd.DataFrame({"measurement_event_id": ["ME::1"], "amplitude_a_u": [1.0]}).to_parquet(
            feature_path, index=False
        )
        definitions_path = feature_dir / "feature_definitions.json"
        definitions_path.write_text('{"features":["amplitude_a_u"]}', encoding="utf-8")
        dataset_path = dataset_dir / "dataset.parquet"
        pd.DataFrame(
            {
                "measurement_event_id": ["ME::1"],
                "battery_id": [B],
                "experiment_id": [E],
                "soc_reference_percent": [50.0],
                "amplitude_a_u": [1.0],
            }
        ).to_parquet(dataset_path, index=False)

        def sha256(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        analysis_slice_path = sandbox / "analysis_slices" / B / E / "AS::fresh-test.parquet"
        analysis_slice_path.parent.mkdir(parents=True)
        analysis_slice_path.write_bytes(b"analysis slice")
        waveform_store_path = sandbox / "waveform_inputs" / B / E / "waveforms.zarr"
        waveform_store_path.mkdir(parents=True)
        (waveform_store_path / "chunk.bin").write_bytes(b"waveform")
        feature_manifest_path = feature_dir / "feature_set_manifest.json"
        feature_manifest_path.write_text(
            json.dumps(
                {
                    "feature_set_id": "FS::fresh-test",
                    "battery_id": B,
                    "experiment_id": E,
                    "analysis_slice_id": "AS::fresh-test",
                    "analysis_slice_path": str(analysis_slice_path.relative_to(sandbox)),
                    "analysis_slice_checksum": sha256(analysis_slice_path),
                    "waveform_store_path": str(waveform_store_path.relative_to(sandbox)),
                    "waveform_store_checksum": tree_sha256(waveform_store_path),
                    "output_paths": {
                        "features": str(feature_path.relative_to(sandbox)),
                        "definitions": str(definitions_path.relative_to(sandbox)),
                    },
                    "output_checksums": {
                        "features": sha256(feature_path),
                        "definitions": sha256(definitions_path),
                    },
                }
            ),
            encoding="utf-8",
        )
        label_manifest_path = label_dir / "label_manifest.json"
        label_manifest_path.write_text(
            json.dumps(
                {
                    "label_set_id": "LB::fresh-test",
                    "battery_id": B,
                    "experiment_id": E,
                    "output_paths": {
                        "event_labels": str(
                            (label_dir / "event_labels.parquet").relative_to(sandbox)
                        ),
                        "cycle_labels": str(cycle_label_path.relative_to(sandbox)),
                    },
                    "output_checksums": {
                        "event_labels": sha256(label_dir / "event_labels.parquet"),
                        "cycle_labels": sha256(cycle_label_path),
                    },
                }
            ),
            encoding="utf-8",
        )

        (dataset_dir / "dataset_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_id": "DS::AUDIT-CURRENT",
                    "dataset_family": "SOC",
                    "dataset_status": "READY_WITH_LIMITATIONS",
                    "battery_id": B,
                    "experiment_id": E,
                    "target_name": "soc_reference_percent",
                    "target_column": "soc_reference_percent",
                    "predictor_columns": ["amplitude_a_u"],
                    "selected_features": ["amplitude_a_u"],
                    "feature_set_id": "FS::fresh-test",
                    "feature_set_path": str(feature_path.relative_to(sandbox)),
                    "feature_set_checksum": sha256(feature_path),
                    "feature_set_manifest_path": str(
                        feature_manifest_path.relative_to(sandbox)
                    ),
                    "feature_set_manifest_checksum": sha256(feature_manifest_path),
                    "label_set_id": "LB::fresh-test",
                    "label_set_path": str(
                        (label_dir / "event_labels.parquet").relative_to(sandbox)
                    ),
                    "label_set_checksum": sha256(label_dir / "event_labels.parquet"),
                    "label_set_manifest_path": str(label_manifest_path.relative_to(sandbox)),
                    "label_set_manifest_checksum": sha256(label_manifest_path),
                    "output_checksum": sha256(dataset_path),
                }
            ),
            encoding="utf-8",
        )
        (old_model_dir / "model_manifest.json").write_text(
            json.dumps(
                {
                    "model_id": "MODEL::OLD",
                    "dataset_id": "DS::OLD",
                    "split_id": "SPLIT::OLD",
                }
            ),
            encoding="utf-8",
        )
        (report_dir / "scientific_report.json").write_text(
            json.dumps(
                {
                    "report_id": "REPORT::OLD",
                    "experiment_record": {"latest_canonical_artifacts": {"dataset_id": "DS::OLD"}},
                }
            ),
            encoding="utf-8",
        )

        d = build_workflow_context(sandbox, B, E)

        assert d["steps"]["DATASET"]["committed"]["dataset_id"] == "DS::AUDIT-CURRENT"
        assert d["steps"]["SPLIT"]["status"] == "NOT_STARTED"
        assert d["steps"]["MODELS"]["status"] == "BLOCKED"
        assert d["steps"]["MODELS"]["blocking"]["required_action"] == "CREATE_SPLIT"
        assert d["artifact_freshness"]["models"] == "STALE"
        assert d["artifact_freshness"]["report"] == "STALE"
        assert d["steps"]["REPORT"]["blocking"]["required_action"] == "CREATE_SPLIT"

    def test_w26_typed_navigation(self, tmp_path: Path) -> None:
        d = build_workflow_context(_sandbox(tmp_path), B, E)
        rec = d["recommended_next_action"]
        assert set(rec) >= {"action_id", "step", "label", "route"}
        assert rec["route"].startswith(f"/experiments/{B}/{E}/")
        for action in d["typed_actions"]:
            assert set(action) == {"action_id", "label", "route"}
            assert action["action_id"] in {
                "REVIEW_TARGET",
                "REVIEW_ALIGNMENT",
                "CONFIGURE_FEATURES",
                "OPEN_PREVIEW",
                "BUILD_DATASET",
                "CREATE_SPLIT",
                "TRAIN_MODELS",
                "OPEN_REPORT",
                "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
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
                "features_physical",
                "datasets",
                "models",
                "splits",
                "parameters",
                "gate_calibrations",
                "feature_analysis",
                "artifacts",
                "assistant_sessions",
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

"""Reuse-verification guard: a newly CONFIRMED fold selection must not be
silently covered by existing model artifacts (fingerprint must resolve the
real dataset/split from the model manifest, not from empty-input re-resolution),
AND the engine must re-validate a pass-1 REUSED decision once an upstream node
has actually executed in pass 2 (ordering hole: FA resets/re-confirms its
selection manifest DURING the run that reused SOC_MODELING).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

from battery_workbench.orchestrator.engine import PipelineOrchestrator
from battery_workbench.orchestrator.nodes import (
    Readiness,
    WorkflowNode,
    _confirmed_fold_fingerprint,
)
from battery_workbench.orchestrator.resolver import (
    ArtifactIdentity,
    ArtifactRequirements,
)
from battery_workbench.orchestrator.schemas import ArtifactRef

B, E = "CELL_001", "EXP_001"
PLAN = SimpleNamespace(project=SimpleNamespace(battery_id=B, experiment_id=E))


def _root(tmp_path: Path) -> Path:
    fa = tmp_path / "feature_analysis" / B / E / "DS::d1" / "AN::new"
    fa.mkdir(parents=True)
    (fa / "analysis_manifest.json").write_text(json.dumps({
        "analysis_mode": "TRAIN_ONLY_ML_SAFE", "fold_index": 1, "split_id": "SPLIT::s1",
        "selection": {"commit_status": "CONFIRMED", "selection_id": "SEL::new",
                      "selected_features": ["amplitude_a_u"]},
    }))
    return tmp_path


def test_new_confirmed_selection_is_in_fingerprint(tmp_path: Path) -> None:
    root = _root(tmp_path)
    current = _confirmed_fold_fingerprint(root, PLAN, "DS::d1", "SPLIT::s1")
    assert current == {"1:SEL::new"}
    # models only cover an older selection → NOT a subset → reuse must be refused
    assert not current.issubset({"1:SEL::old"})


def test_unresolvable_ids_yield_empty_fingerprint(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert _confirmed_fold_fingerprint(root, PLAN, "", "") == set()
    assert _confirmed_fold_fingerprint(root, PLAN, "DS::missing", "SPLIT::s1") == set()


def _ref(artifact_id: str, root: Path) -> ArtifactRef:
    return ArtifactRef(
        artifact_type="FEATURE_ANALYSIS",
        artifact_id=artifact_id,
        battery_id=B,
        experiment_id=E,
        path=str(root),
        manifest_path=str(root / "m.json"),
    )


class _FakeFa(WorkflowNode):
    node_type: ClassVar[str] = "FEATURE_ANALYSIS"

    def __init__(self, root: Path) -> None:
        self._root = root

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="FEATURE_ANALYSIS",
            manifest_name="analysis_manifest.json",
            identity=ArtifactIdentity(battery_id=B, experiment_id=E),
            output_rel_dir="feature_analysis",
            id_key="analysis_id",
            scan=False,
        )

    def validate_readiness(self, plan, inputs):
        return Readiness(ok=True, reason="fake ready")

    def run(self, plan, inputs, ctx):
        return {"artifact_id": "AN::fresh", "path": str(self._root), "metrics": {}}


class _FakeSoc(WorkflowNode):
    """Reuse is 'valid' only while FEATURE_ANALYSIS has not resolved — i.e. the
    stale pass-1 view. Once FA executed this run, the confirmed selection is
    new and no existing model covers it."""

    node_type: ClassVar[str] = "SOC_MODELING"

    def __init__(self, root: Path) -> None:
        self._root = root
        self.resolve_calls: list[tuple[str, ...]] = []

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="SOC_MODELING",
            manifest_name="model_manifest.json",
            identity=ArtifactIdentity(battery_id=B, experiment_id=E),
            output_rel_dir="models",
            id_key="model_id",
            scan=False,
        )

    def validate_readiness(self, plan, inputs):
        return Readiness(ok=True, reason="fake ready")

    def resolve_existing_output(self, plan, inputs, processed_root):
        self.resolve_calls.append(tuple(sorted(inputs)))
        if "FEATURE_ANALYSIS" in inputs:
            return None, "new confirmed fold selection not covered"
        return _ref("MODEL::stale", self._root), "stale pass-1 reuse"

    def run(self, plan, inputs, ctx):
        return {"artifact_id": "MODEL::fresh", "path": str(self._root), "metrics": {}}


class _FakeReused(WorkflowNode):
    """Stand-in upstream (DATASET/SPLIT): always resolves to an existing ref."""

    node_version: ClassVar[str] = "0.1.0"

    def __init__(self, node_type: str, artifact_id: str, root: Path) -> None:
        self.node_type = node_type
        self._artifact_id = artifact_id
        self._root = root

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type=self.node_type,
            manifest_name="manifest.json",
            identity=ArtifactIdentity(battery_id=B, experiment_id=E),
            output_rel_dir=self.node_type.lower(),
            id_key=f"{self.node_type.lower()}_id",
            scan=False,
        )

    def resolve_existing_output(self, plan, inputs, processed_root):
        return _ref(self._artifact_id, self._root), "fake reuse"

    def validate_readiness(self, plan, inputs):
        return Readiness(ok=True, reason="fake ready")


def test_pass2_reuse_revalidation_after_upstream_ran(tmp_path: Path) -> None:
    (tmp_path / "m.json").write_text("{}")
    orch = PipelineOrchestrator(
        raw_root=tmp_path, processed_root=tmp_path, runs_root=tmp_path / "runs"
    )
    soc = _FakeSoc(tmp_path)
    orch.nodes["DATASET"] = _FakeReused("DATASET", "DS::t", tmp_path)
    orch.nodes["SPLIT"] = _FakeReused("SPLIT", "SPLIT::t", tmp_path)
    orch.nodes["FEATURE_LABEL_ANALYSIS"] = _FakeReused(
        "FEATURE_LABEL_ANALYSIS", "FLA::t", tmp_path
    )
    orch.nodes["FEATURE_ANALYSIS"] = _FakeFa(tmp_path)
    orch.nodes["SOC_MODELING"] = soc
    plan = orch.plan_run(
        profile="SCIENTIFIC_ANALYSIS",
        battery_id=B,
        experiment_id=E,
        dry_run=False,
        target="soc_reference_percent",
        stages=["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING"],
    )
    run: dict[str, Any] = orch.start_run(plan, runs_root=tmp_path / "runs")
    states = {n["node_id"]: n["state"] for n in run["nodes"]}
    assert states["FEATURE_ANALYSIS"] == "SUCCEEDED"
    # without pass-2 revalidation SOC_MODELING would stay REUSED on the stale
    # pass-1 decision (the exact hole seen in live run …T071719524810Z)
    assert states["SOC_MODELING"] == "SUCCEEDED"
    assert run["status"] == "SUCCEEDED"
    events = (Path(run["run_dir"]) / "run_events.jsonl").read_text()
    assert "REUSE_REVALIDATED" in events
    assert "FEATURE_ANALYSIS" in soc.resolve_calls[-1]

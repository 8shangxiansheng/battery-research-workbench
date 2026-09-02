"""BRW-019 WorkflowNode adapters for BRW-003–018 modules.

Every adapter only resolves existing artifacts, validates scientific
readiness, and CALLS the existing deterministic module entrypoints. No
scientific formula lives here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from battery_workbench.orchestrator.resolver import (
    ArtifactIdentity,
    ArtifactRequirements,
    current_input_checksums,
    find_existing_artifact,
)
from battery_workbench.orchestrator.schemas import (
    AnalysisPlan,
    ArtifactRef,
    UserActionRequired,
)


def _action_id(node_id: str, action_type: str) -> str:
    import hashlib

    return "UA::" + hashlib.sha256(f"{node_id}:{action_type}".encode()).hexdigest()[:20]


class Readiness:
    """Result of validate_readiness."""

    def __init__(
        self,
        ok: bool,
        reason: str = "",
        user_action: UserActionRequired | None = None,
        limitations: list[str] | None = None,
    ) -> None:
        self.ok = ok
        self.reason = reason
        self.user_action = user_action
        self.limitations = limitations or []


class WorkflowNode:
    node_type: ClassVar[str] = ""
    node_version: ClassVar[str] = "0.1.0"
    deps: ClassVar[list[str]] = []
    optional_deps: ClassVar[list[str]] = []

    def required_inputs(self) -> list[str]:
        return list(self.deps)

    def validate_readiness(self, plan: AnalysisPlan, inputs: dict[str, ArtifactRef]) -> Readiness:
        """Default: ready when upstream inputs resolve (overridden per node)."""
        return Readiness(ok=True, reason="default readiness (no scientific gate)")

    # -- hooks each node implements ------------------------------------

    def requirements(
        self, plan: AnalysisPlan, inputs: dict[str, ArtifactRef]
    ) -> ArtifactRequirements:
        raise NotImplementedError

    def output_rel_dir(self, plan: AnalysisPlan) -> str:
        raise NotImplementedError

    def pinned_artifact_id(self, plan: AnalysisPlan) -> str | None:
        return None

    def run(self, plan: AnalysisPlan, inputs: dict[str, ArtifactRef], ctx: Any) -> dict[str, Any]:
        """Execute via the existing module; returns outputs + notes."""
        raise NotImplementedError

    # -- shared resolution ---------------------------------------------

    def resolve_existing_output(
        self,
        plan: AnalysisPlan,
        inputs: dict[str, ArtifactRef],
        processed_root: Path,
    ) -> tuple[ArtifactRef | None, str]:
        req = self.requirements(plan, inputs)
        provenance = {}
        for dep_ref in inputs.values():
            manifest = _load_json(Path(dep_ref.manifest_path))
            if manifest and manifest.get("input_checksums"):
                manifest_path = Path(dep_ref.manifest_path)
                current = current_input_checksums(
                    manifest, manifest_path, processed_root=processed_root
                )
                if current:
                    provenance[f"upstream:{dep_ref.artifact_type}"] = {
                        "input_checksums": _downshift(current)
                    }
        ref = find_existing_artifact(
            processed_root,
            requirements=req,
            artifact_id=self.pinned_artifact_id(plan),
            provenance=provenance or None,
        )
        if ref is not None:
            from battery_workbench.orchestrator.resolver import verify_manifest_provenance

            manifest = _load_json(Path(ref.manifest_path)) or {}
            ok, prov_reason = verify_manifest_provenance(
                manifest, Path(ref.manifest_path), processed_root=processed_root
            )
            if not ok:
                return None, prov_reason
        reason = ref.reuse_reason if ref is not None else "no reusable artifact found"
        return ref, reason

    def _load_effective_parameters(self, inputs: dict[str, ArtifactRef]) -> dict[str, Any]:
        ref = inputs.get("PARAMETER_SET")
        if ref is None:
            return {}
        manifest = _load_json(Path(ref.manifest_path)) or {}
        eff = manifest.get("effective_parameters") or {}
        if not eff:
            eff_path = Path(ref.path) / "effective_parameters.json"
            if eff_path.exists():
                eff = _load_json(eff_path) or {}
        return eff


def _downshift(d: dict[str, str]) -> dict[str, str]:
    """Flatten dict-of-dicts checksum values to strings for comparison."""
    out: dict[str, str] = {}
    for k, v in d.items():
        out[k] = v if isinstance(v, str) else json.dumps(v, sort_keys=True)
    return out


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------
# Concrete nodes
# --------------------------------------------------------------------------


class ElectricalCanonicalNode(WorkflowNode):
    node_type = "ELECTRICAL_CANONICAL"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="ELECTRICAL_CANONICAL",
            manifest_name="parser_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"electrical/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="parser_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"electrical/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.io.electrical.service import (
            parse_electrical_experiment,
            write_electrical_experiment,
        )
        from battery_workbench.io.experiment.manifest_loader import (
            load_data_assets,
            load_experiments,
        )

        experiment = next(
            e
            for e in load_experiments(Path(ctx.raw_root) / "manifests" / "experiments.csv")
            if e.experiment_id == plan.project.experiment_id
        )
        assets = [
            a
            for a in load_data_assets(Path(ctx.raw_root) / "manifests" / "data_assets.csv")
            if a.modality == "electrical"
            and a.experiment_id == plan.project.experiment_id
            and (Path(ctx.raw_root) / a.relative_path).exists()
        ]
        result = parse_electrical_experiment(experiment, assets, ctx.raw_root)
        manifest = write_electrical_experiment(result, Path(ctx.processed_root) / "electrical")
        out_dir = (
            Path(ctx.processed_root)
            / "electrical"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        return {
            "artifact_id": "",
            "path": str(out_dir),
            "manifest_path": str(out_dir / "parser_manifest.json"),
            "producer_version": manifest.parser_version,
            "metrics": {"records": len(result.records)},
        }


class UltrasoundCanonicalNode(WorkflowNode):
    node_type = "ULTRASOUND_CANONICAL"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="ULTRASOUND_CANONICAL",
            manifest_name="parser_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"ultrasound/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="parser_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"ultrasound/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.io.experiment.manifest_loader import (
            load_data_assets,
            load_experiments,
        )
        from battery_workbench.io.ultrasound.service import (
            parse_ultrasound_experiment,
            write_ultrasound_experiment,
        )

        experiment = next(
            e
            for e in load_experiments(Path(ctx.raw_root) / "manifests" / "experiments.csv")
            if e.experiment_id == plan.project.experiment_id
        )
        assets = [
            a
            for a in load_data_assets(Path(ctx.raw_root) / "manifests" / "data_assets.csv")
            if a.modality == "ultrasound"
            and a.experiment_id == plan.project.experiment_id
            and (Path(ctx.raw_root) / a.relative_path).exists()
        ]
        result = parse_ultrasound_experiment(experiment, assets, ctx.raw_root)
        manifest = write_ultrasound_experiment(result, Path(ctx.processed_root) / "ultrasound")
        out_dir = (
            Path(ctx.processed_root)
            / "ultrasound"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        return {
            "artifact_id": "",
            "path": str(out_dir),
            "manifest_path": str(out_dir / "parser_manifest.json"),
            "producer_version": manifest.parser_version,
            "metrics": {
                "frames": manifest.frame_count if hasattr(manifest, "frame_count") else None
            },
        }


class TimeAnchorNode(WorkflowNode):
    node_type = "TIME_ANCHOR"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="TIME_ANCHORS",
            manifest_name="time_anchors.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="anchor_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.synchronization.persistence import write_time_anchor_state
        from battery_workbench.synchronization.schemas import TimeAnchorConfig
        from battery_workbench.synchronization.service import assess_experiment_time_anchors

        config = TimeAnchorConfig.from_yaml(
            Path(ctx.raw_root).parent.parent / "configs" / "time_anchor.yaml"
        )
        report = assess_experiment_time_anchors(
            plan.project.experiment_id,
            processed_root=Path(ctx.processed_root),
            manifest_root=Path(ctx.raw_root) / "manifests",
            config=config,
        )
        from battery_workbench.io.experiment.manifest_loader import load_experiments
        from battery_workbench.synchronization.schemas import AssetAnchorAssessment, TimeAnchorState

        experiment = next(
            e
            for e in load_experiments(Path(ctx.raw_root) / "manifests" / "experiments.csv")
            if e.experiment_id == plan.project.experiment_id
        )
        state = TimeAnchorState(
            battery_id=plan.project.battery_id,
            experiment_id=plan.project.experiment_id,
            anchor_version=report.anchor_version,
            experiment_reference={
                "battery_id": plan.project.battery_id,
                "experiment_id": plan.project.experiment_id,
                "experiment_start_time": experiment.start_time.isoformat()
                if experiment.start_time
                else None,
                "experiment_end_time": experiment.end_time.isoformat()
                if experiment.end_time
                else None,
            },
            assets=[AssetAnchorAssessment.model_validate(a) for a in report.assets],
            warnings=report.warnings,
            limitations=report.limitations,
            validated_sync=False,
        )
        written = write_time_anchor_state(
            state,
            processed_root=Path(ctx.processed_root),
            artifacts_root=Path(ctx.processed_root) / "artifacts",
        )
        out_dir = (
            Path(ctx.processed_root)
            / "synchronization"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        return {
            "artifact_id": "",
            "path": str(out_dir),
            "manifest_path": str(written["time_anchors"]),
            "producer_version": self.node_version,
            "limitations": ["PROVISIONAL time anchors (BRW-008 semantics)"],
            "metrics": {"assets": len(report.assets)},
        }


class UltrasoundTimestampsNode(WorkflowNode):
    node_type = "ULTRASOUND_TIMESTAMPS"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="ULTRASOUND_TIMESTAMPS",
            manifest_name="timestamp_engine_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="engine_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.synchronization.timestamp_engine import (
            TimestampEngineConfig,
            build_ultrasound_timestamps,
        )

        exp_dir = (
            Path(ctx.processed_root)
            / "synchronization"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        report = build_ultrasound_timestamps(
            frames_path=Path(ctx.processed_root)
            / "ultrasound"
            / plan.project.battery_id
            / plan.project.experiment_id
            / "frames.parquet",
            time_anchor_state_path=exp_dir / "time_anchors.json",
            output_dir=exp_dir,
            config=TimestampEngineConfig(),
        )
        return {
            "artifact_id": "",
            "path": str(exp_dir),
            "manifest_path": str(exp_dir / "timestamp_engine_manifest.json"),
            "producer_version": report.engine_version,
            "limitations": ["PROVISIONAL per-frame timestamps"],
        }


class SynchronizationNode(WorkflowNode):
    node_type = "SYNCHRONIZATION"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="SYNCHRONIZATION",
            manifest_name="synchronization_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="sync_engine_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"synchronization/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.synchronization.sync_service import (
            SynchronizationConfig,
            synchronize_ultrasound_to_electrical,
        )

        exp_dir = (
            Path(ctx.processed_root)
            / "synchronization"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        report = synchronize_ultrasound_to_electrical(
            timestamped_frames_path=exp_dir / "timestamped_ultrasound_frames.parquet",
            electrical_records_path=Path(ctx.processed_root)
            / "electrical"
            / plan.project.battery_id
            / plan.project.experiment_id
            / "records.parquet",
            output_dir=exp_dir,
            config=SynchronizationConfig(),
        )
        return {
            "artifact_id": "",
            "path": str(exp_dir),
            "manifest_path": str(exp_dir / "synchronization_manifest.json"),
            "producer_version": report.sync_engine_version,
            "metrics": {"matched_frames": report.matches_frames},
        }


class MeasurementEventsNode(WorkflowNode):
    node_type = "MEASUREMENT_EVENTS"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="MEASUREMENT_EVENTS",
            manifest_name="measurement_event_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"multimodal/{plan.project.battery_id}/{plan.project.experiment_id}",
            version_key="builder_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"multimodal/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.multimodal.service import build_events_for_experiment

        report = build_events_for_experiment(
            plan.project.battery_id,
            plan.project.experiment_id,
            processed_root=Path(ctx.processed_root),
        )
        out_dir = (
            Path(ctx.processed_root)
            / "multimodal"
            / plan.project.battery_id
            / plan.project.experiment_id
        )
        return {
            "artifact_id": "",
            "path": str(out_dir),
            "manifest_path": str(out_dir / "measurement_event_manifest.json"),
            "producer_version": report.builder_version,
            "metrics": {
                "events": report.output_row_count if hasattr(report, "output_row_count") else None
            },
        }


class AnalysisSliceNode(WorkflowNode):
    node_type = "ANALYSIS_SLICE"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="ANALYSIS_SLICE",
            manifest_name="analysis_slice_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"analysis_slices/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="analysis_slice_id",
            version_key="slice_engine_version",
            expected_version=self.node_version,
        )

    def output_rel_dir(self, plan):
        return f"analysis_slices/{plan.project.battery_id}/{plan.project.experiment_id}"

    def pinned_artifact_id(self, plan):
        return plan.analysis_slice.get("analysis_slice_id")

    def run(self, plan, inputs, ctx):
        from battery_workbench.analysis.schemas import AnalysisSliceConfig, ConditionSliceSpec
        from battery_workbench.analysis.slice_engine import create_analysis_slice

        spec_dict = plan.analysis_slice.get("spec") or {}
        spec = ConditionSliceSpec(**spec_dict)
        report = create_analysis_slice(
            measurement_events_path=Path(ctx.processed_root)
            / "multimodal"
            / plan.project.battery_id
            / plan.project.experiment_id
            / "measurement_events.parquet",
            spec=spec,
            output_root=Path(ctx.processed_root) / "analysis_slices",
            config=AnalysisSliceConfig(),
        )
        out_dir = (
            Path(ctx.processed_root)
            / "analysis_slices"
            / plan.project.battery_id
            / plan.project.experiment_id
            / report.analysis_slice_id
        )
        return {
            "artifact_id": report.analysis_slice_id,
            "path": str(out_dir),
            "manifest_path": str(out_dir / "analysis_slice_manifest.json"),
            "producer_version": report.slice_engine_version,
            "metrics": {"rows": report.output_row_count},
        }


class UltrasoundFeaturesNode(WorkflowNode):
    node_type = "ULTRASOUND_FEATURES"

    def requirements(self, plan, inputs):
        extra: dict[str, Any] = {}
        pinned_slice = plan.analysis_slice.get("analysis_slice_id")
        if pinned_slice:
            extra["analysis_slice_id"] = pinned_slice
        return ArtifactRequirements(
            artifact_type="ULTRASOUND_FEATURE_SET",
            manifest_name="feature_set_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"features/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="feature_set_id",
            version_key="feature_engine_version",
            expected_version=self.node_version,
            extra_match=extra,
        )

    def output_rel_dir(self, plan):
        return f"features/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.features.ultrasound_engine import (
            UltrasoundFeatureConfig,
            extract_ultrasound_features,
        )

        slice_ref = inputs["ANALYSIS_SLICE"]
        report = extract_ultrasound_features(
            analysis_slice_path=Path(slice_ref.path) / "analysis_slice.parquet",
            waveform_store_path=Path(ctx.processed_root)
            / "ultrasound"
            / plan.project.battery_id
            / plan.project.experiment_id
            / "waveforms.zarr",
            output_root=Path(ctx.processed_root)
            / "features"
            / plan.project.battery_id
            / plan.project.experiment_id,
            config=UltrasoundFeatureConfig(),
        )
        fs_dir = Path(report.artifacts["features"]).parent
        return {
            "artifact_id": report.feature_set_id,
            "path": str(fs_dir),
            "manifest_path": str(fs_dir / "feature_set_manifest.json"),
            "producer_version": report.engine_version,
            "metrics": {"rows": report.output_row_count},
        }


class ReferenceLabelsNode(WorkflowNode):
    node_type = "REFERENCE_LABELS"

    def requirements(self, plan, inputs):
        req = ArtifactRequirements(
            artifact_type="LABEL_SET",
            manifest_name="label_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"labels/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="label_set_id",
            version_key="label_engine_version",
            expected_version=self.node_version,
        )
        if plan.label_producer_version:
            req.expected_version = plan.label_producer_version
        return req

    def output_rel_dir(self, plan):
        return f"labels/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        from battery_workbench.labels.builder import build_reference_labels

        b, e = plan.project.battery_id, plan.project.experiment_id
        report = build_reference_labels(
            measurement_events_path=Path(ctx.processed_root)
            / "multimodal"
            / b
            / e
            / "measurement_events.parquet",
            records_path=Path(ctx.processed_root) / "electrical" / b / e / "records.parquet",
            cycles_path=Path(ctx.processed_root) / "electrical" / b / e / "cycles.parquet",
            steps_path=Path(ctx.processed_root) / "electrical" / b / e / "steps.parquet",
            ultrasound_manifest_path=Path(ctx.processed_root)
            / "ultrasound"
            / b
            / e
            / "parser_manifest.json",
            output_root=Path(ctx.processed_root) / "labels",
        )
        out_dir = Path(ctx.processed_root) / "labels" / b / e
        limitations = list(report.limitations) if hasattr(report, "limitations") else []
        limitations.append("SOC method: RETROSPECTIVE/PROTOCOL_ANCHORED (preserved)")
        return {
            "artifact_id": report.label_set_id,
            "path": str(out_dir),
            "manifest_path": str(out_dir / "label_manifest.json"),
            "producer_version": report.label_engine_version,
            "limitations": limitations,
        }


class ParameterSetNode(WorkflowNode):
    node_type = "PARAMETER_SET"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="PARAMETER_SET",
            manifest_name="parameter_set_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"parameters/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="parameter_set_id",
            version_key="registry_version",
        )

    def output_rel_dir(self, plan):
        return f"parameters/{plan.project.battery_id}/{plan.project.experiment_id}"

    def pinned_artifact_id(self, plan):
        return plan.parameters.get("parameter_set_id")

    def _user_overrides(self, plan) -> dict[str, Any]:
        overrides = plan.parameters.get("user_overrides") or {}
        return dict(overrides)

    def resolve_existing_output(self, plan, inputs, processed_root):
        # user_overrides define a NEW artifact: existing sets (built without
        # those overrides) must not be silently reused.
        if self._user_overrides(plan) and not self.pinned_artifact_id(plan):
            return None, "user_overrides present — new parameter set required"
        ref, reason = super().resolve_existing_output(plan, inputs, processed_root)
        if ref is not None and plan.parameters.get("require_sampling_rate"):
            # reuse only a parameter set that actually resolves the demanded input
            manifest = _load_json(Path(ref.manifest_path)) or {}
            eff = manifest.get("effective_parameters") or {}
            if not eff:
                eff = _load_json(Path(ref.path) / "effective_parameters.json") or {}
            fs_entry = eff.get("ultrasound.sampling_rate_hz") or {}
            if not (fs_entry.get("status") == "RESOLVED" and fs_entry.get("value") is not None):
                return None, "pinned/reused parameter set does not resolve sampling_rate_hz"
        return ref, reason

    def validate_readiness(self, plan, inputs):
        require_fs = bool(plan.parameters.get("require_sampling_rate"))
        if not require_fs:
            return Readiness(ok=True, reason="no physical-time requirement in plan")
        pinned = plan.parameters.get("parameter_set_id")
        if pinned:
            return Readiness(ok=True, reason="parameter set pinned by plan")
        if self._user_overrides(plan):
            return Readiness(ok=True, reason="user overrides present")
        eff = self._load_effective_parameters(inputs)
        fs_entry = eff.get("ultrasound.sampling_rate_hz") or {}
        if fs_entry.get("status") == "RESOLVED" and fs_entry.get("value") is not None:
            return Readiness(ok=True, reason="sampling rate already resolved")
        return Readiness(
            ok=False,
            reason="sampling_rate_hz UNKNOWN and required for physical-time analysis",
            user_action=UserActionRequired(
                action_id=_action_id(self.node_type, "MISSING_SAMPLING_RATE"),
                node_id=self.node_type,
                action_type="MISSING_SAMPLING_RATE",
                message="请输入采样频率 (MHz)",
                required_fields=[
                    {
                        "field": "ultrasound.sampling_rate_hz",
                        "unit": "MHz",
                        "example": 50.0,
                    }
                ],
                scientific_reason=(
                    "Absolute TOF / physical-time features require the waveform "
                    "sampling rate. Frame cadence (10 s) and sample count (1250) "
                    "cannot provide it. The orchestrator never guesses."
                ),
                blocking=True,
            ),
        )

    def run(self, plan, inputs, ctx):
        from battery_workbench.parameters.service import build_parameter_set

        b, e = plan.project.battery_id, plan.project.experiment_id
        base = Path(ctx.processed_root)
        overrides = self._user_overrides(plan)
        report = build_parameter_set(
            output_root=base,
            measurement_events_path=base / "multimodal" / b / e / "measurement_events.parquet",
            cycles_path=base / "electrical" / b / e / "cycles.parquet",
            waveform_store_path=base / "ultrasound" / b / e / "waveforms.zarr",
            label_manifest_path=base / "labels" / b / e / "label_manifest.json",
            user_overrides=overrides or None,
        )
        out_dir = base / "parameters" / b / e / report.parameter_set_id
        limitations: list[str] = []
        eff = json.loads((out_dir / "effective_parameters.json").read_text())
        fs_entry = eff.get("ultrasound.sampling_rate_hz") or {}
        if fs_entry.get("status") != "RESOLVED":
            limitations.append("sampling_rate_hz UNKNOWN (never forged)")
        return {
            "artifact_id": report.parameter_set_id,
            "path": str(out_dir),
            "manifest_path": str(out_dir / "parameter_set_manifest.json"),
            "producer_version": report.registry_version,
            "limitations": limitations,
            "metrics": {"fs_status": fs_entry.get("status")},
        }


class TofActivationNode(WorkflowNode):
    node_type = "TOF_ACTIVATION"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="TOF_ACTIVATION",
            manifest_name="tof_activation_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"features_physical/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="",
            version_key="",
        )

    def output_rel_dir(self, plan):
        return f"features_physical/{plan.project.battery_id}/{plan.project.experiment_id}"

    def run(self, plan, inputs, ctx):
        import numpy as np
        import pandas as pd
        import zarr

        from battery_workbench.features_physical.arrival_detector import (
            DETECTOR_VERSION,
            detect_arrival_sample,
            validate_arrival_detector,
        )
        from battery_workbench.features_physical.engine import (
            TOF_STATUS_BLOCKED,
            compute_relative_delay_us,
            tof_status,
        )

        b, e = plan.project.battery_id, plan.project.experiment_id
        validation = validate_arrival_detector()
        if not validation["validated"]:
            raise RuntimeError("arrival detector failed synthetic validation")
        features_path = Path(ctx.processed_root) / "features" / b / e
        feature_sets = sorted(p for p in features_path.glob("FS::*") if p.is_dir())
        if not feature_sets:
            raise FileNotFoundError("no ULTRASOUND_FEATURE_SET available for TOF activation")
        features = pd.read_parquet(feature_sets[-1] / "ultrasound_features.parquet")
        zg = zarr.open_group(
            str(Path(ctx.processed_root) / "ultrasound" / b / e / "waveforms.zarr"), mode="r"
        )
        arrivals = [
            detect_arrival_sample(np.asarray(zg[str(g)][int(i)]))
            for g, i in zip(features["waveform_group"], features["waveform_row_index"], strict=True)
        ]
        eff = self._load_effective_parameters(inputs)
        fs_entry = eff.get("ultrasound.sampling_rate_hz") or {}
        fs = fs_entry.get("value") if fs_entry.get("status") == "RESOLVED" else None
        trigger = (eff.get("ultrasound.trigger_sample_index") or {}).get("value")
        detector_ok = True
        tof_vals: list[float | None] = []
        if fs and trigger is not None:
            tof_vals = [(a - int(trigger)) / fs * 1e6 if a is not None else None for a in arrivals]
            tof_vals = [v if (v is not None and v > 0) else None for v in tof_vals]
        status = (
            tof_status(
                sampling_rate_hz=fs,
                trigger_sample_index=trigger,
                arrival_sample_index=arrivals[0] if arrivals else None,
                arrival_detector_validated=detector_ok,
            )
            if tof_vals
            else TOF_STATUS_BLOCKED
        )
        out = pd.DataFrame(
            {
                "measurement_event_id": features["measurement_event_id"],
                "arrival_sample_index": pd.array(arrivals, dtype="Int64"),
                "detector_version": DETECTOR_VERSION,
                "tof_us": pd.array(
                    tof_vals if tof_vals else [None] * len(arrivals), dtype="Float64"
                ),
                "tof_status": status,
                "tof_block_reason": "" if status == "READY" else "NONPHYSICAL_OR_BLOCKED",
                "relative_tof_shift_us": pd.array(
                    [
                        compute_relative_delay_us(xcorr_shift_samples=int(s), sampling_rate_hz=fs)
                        for s in features["xcorr_shift_samples"]
                    ],
                    dtype="Float64",
                ),
                "parameter_set_id": (
                    inputs.get("PARAMETER_SET").artifact_id if inputs.get("PARAMETER_SET") else ""
                ),
            }
        )
        out_dir = Path(ctx.processed_root) / "features_physical" / b / e
        out_dir.mkdir(parents=True, exist_ok=True)
        out.to_parquet(out_dir / "ultrasound_tof.parquet", index=False)
        manifest = {
            "detector_version": DETECTOR_VERSION,
            "detector_validation": validation,
            "tof_status": status,
            "row_count": len(out),
        }
        (out_dir / "tof_activation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return {
            "artifact_id": "",
            "path": str(out_dir),
            "manifest_path": str(out_dir / "tof_activation_manifest.json"),
            "producer_version": DETECTOR_VERSION,
            "limitations": ["tof_us remains BLOCKED unless the full chain resolves"],
        }


class GatedFeaturesNode(WorkflowNode):
    node_type = "GATED_FEATURES"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="GATED_FEATURE_SET",
            manifest_name="gated_feature_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"gated_features/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="gate_set_id",
            version_key="",
        )

    def output_rel_dir(self, plan):
        return f"gated_features/{plan.project.battery_id}/{plan.project.experiment_id}"

    def pinned_artifact_id(self, plan):
        gate_set_id = plan.gates.get("gate_set_id")
        if gate_set_id:
            return gate_set_id
        specs = plan.gates.get("gate_specs")
        if specs:
            # gate specs ARE the identity: changed bounds → changed gate_set_id
            from battery_workbench.gates.persistence import build_gate_set_id
            from battery_workbench.gates.schemas import GateSpec

            gates = [
                GateSpec(waveform_length=plan.gates.get("waveform_length", 1250), **g)
                for g in specs
            ]
            return build_gate_set_id(gates)
        return None

    def resolve_existing_output(self, plan, inputs, processed_root):
        # gate specs change the artifact identity — reuse only an exact match
        if plan.gates.get("gate_specs") and not plan.gates.get("gate_set_id"):
            expected_id = self.pinned_artifact_id(plan)
            ref = find_existing_artifact(
                processed_root,
                requirements=self.requirements(plan, inputs),
                artifact_id=expected_id,
            )
            if ref is None:
                return None, "gate specs changed — new gate set required"
            return ref, "gate specs match existing gate set"
        return super().resolve_existing_output(plan, inputs, processed_root)

    def run(self, plan, inputs, ctx):
        import numpy as np
        import pandas as pd
        import zarr

        from battery_workbench.gates.engine import extract_gated_features
        from battery_workbench.gates.persistence import write_gated_feature_payload
        from battery_workbench.gates.schemas import GateSpec

        b, e = plan.project.battery_id, plan.project.experiment_id
        gate_dicts = plan.gates.get("gate_specs") or []
        if not gate_dicts:
            raise ValueError("no gate specs in plan")
        gates = [
            GateSpec(waveform_length=plan.gates.get("waveform_length", 1250), **g)
            for g in gate_dicts
        ]
        slice_ref = inputs["ANALYSIS_SLICE"]
        slice_df = pd.read_parquet(Path(slice_ref.path) / "analysis_slice.parquet")
        zg = zarr.open_group(
            str(Path(ctx.processed_root) / "ultrasound" / b / e / "waveforms.zarr"), mode="r"
        )
        rows = []
        for group, idx, event_id in zip(
            slice_df["waveform_group"],
            slice_df["waveform_row_index"],
            slice_df["measurement_event_id"],
            strict=True,
        ):
            wave = np.asarray(zg[str(group)][int(idx)])
            for gate in gates:
                feats = extract_gated_features(wave, gate)
                feats["measurement_event_id"] = event_id
                rows.append(feats)
        gated = pd.DataFrame(rows)
        eff = self._load_effective_parameters(inputs)
        fs_entry = eff.get("ultrasound.sampling_rate_hz") or {}
        fs = fs_entry.get("value") if fs_entry.get("status") == "RESOLVED" else None
        # diagnostic between-gate delay (first pair) — never named tof_us
        delay_values: list[float | None] = []
        if len(gates) >= 2:
            for event_id in slice_df["measurement_event_id"]:
                sub = gated[gated["measurement_event_id"] == event_id]
                pa = sub[sub["gate_id"] == gates[0].gate_id]["waveform_abs_peak_sample_index"]
                pb = sub[sub["gate_id"] == gates[1].gate_id]["waveform_abs_peak_sample_index"]
                if len(pa) and len(pb) and pd.notna(pa.iloc[0]) and pd.notna(pb.iloc[0]):
                    delay_values.append(
                        (int(pb.iloc[0]) - int(pa.iloc[0])) / fs * 1e6 if fs else None
                    )
                else:
                    delay_values.append(None)
        paths = write_gated_feature_payload(
            gated_features=gated,
            gate_specs=gates,
            tof_definitions=[],
            gate_selection_basis=str(plan.gates.get("gate_selection_basis", "SIGNAL_ONLY")),
            battery_id=b,
            experiment_id=e,
            output_root=Path(ctx.processed_root),
            waveform_store_path=str(
                Path(ctx.processed_root) / "ultrasound" / b / e / "waveforms.zarr"
            ),
        )
        # delay column persisted next to the payload (analysis-layer quantity)
        if len(gates) >= 2:
            delay_df = pd.DataFrame(
                {
                    "measurement_event_id": slice_df["measurement_event_id"],
                    "delay_samples": [
                        int(pb) - int(pa)
                        for pa, pb in zip(
                            gated[gated["gate_id"] == gates[0].gate_id][
                                "waveform_abs_peak_sample_index"
                            ],
                            gated[gated["gate_id"] == gates[1].gate_id][
                                "waveform_abs_peak_sample_index"
                            ],
                            strict=True,
                        )
                    ],
                    "delay_us": delay_values,
                }
            )
            delay_df.to_parquet(
                Path(paths["gated_features"]).parent / "gate_delay.parquet", index=False
            )
        return {
            "artifact_id": paths["gate_set_id"],
            "path": str(Path(paths["gated_features"]).parent),
            "manifest_path": paths["gated_feature_manifest"],
            "producer_version": self.node_version,
            "metrics": {"rows": len(gated)},
            "limitations": ["between-gate delay is diagnostic; NOT tof_us (unconfirmed)"],
        }


class FeatureLabelAnalysisNode(WorkflowNode):
    node_type = "FEATURE_LABEL_ANALYSIS"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="FEATURE_LABEL_ANALYSIS",
            manifest_name="gated_analysis_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"feature_analysis/{plan.project.battery_id}/{plan.project.experiment_id}",
            id_key="gate_set_id",
            version_key="",
        )

    def output_rel_dir(self, plan):
        return f"feature_analysis/{plan.project.battery_id}/{plan.project.experiment_id}"

    def pinned_artifact_id(self, plan):
        return plan.gates.get("gate_set_id")

    def run(self, plan, inputs, ctx):
        import pandas as pd

        from battery_workbench.gates.analysis import (
            build_gated_feature_label_analysis,
            delay_locator,
        )
        from battery_workbench.gates.persistence import write_gated_analysis_payload

        b, e = plan.project.battery_id, plan.project.experiment_id
        gate_ref = inputs["GATED_FEATURES"]
        gated = pd.read_parquet(Path(gate_ref.path) / "gated_features.parquet")
        labels = pd.read_parquet(
            Path(ctx.processed_root) / "labels" / b / e / "event_labels.parquet"
        )
        cycles = pd.read_parquet(
            Path(ctx.processed_root) / "labels" / b / e / "cycle_labels.parquet"
        )
        analysis = gated.pivot_table(
            index="measurement_event_id",
            columns="gate_id",
            values=["amplitude_a_u", "waveform_rms_a_u", "waveform_p2p_a_u"],
            aggfunc="first",
        )
        analysis.columns = [f"{feat}@{gid}" for feat, gid in analysis.columns]
        analysis = analysis.reset_index()
        delay_path = Path(gate_ref.path) / "gate_delay.parquet"
        if delay_path.exists():
            d = pd.read_parquet(delay_path)
            gate_ids = json.loads((Path(gate_ref.manifest_path)).read_text())["gates"]
            if len(gate_ids) >= 2:
                loc = delay_locator(gate_ids[0]["gate_id"], gate_ids[1]["gate_id"])
                analysis[loc] = (
                    d.set_index("measurement_event_id")["delay_us"]
                    .reindex(analysis["measurement_event_id"])
                    .to_numpy()
                )
        analysis_full = build_gated_feature_label_analysis(
            gated_features=analysis,
            event_labels=labels,
            cycle_labels=cycles,
            event_grain=True,
        )
        paths = write_gated_analysis_payload(
            analysis_df=analysis_full,
            manifest={
                "gate_set_id": gate_ref.artifact_id,
                "row_count": len(analysis_full),
                "columns": list(analysis_full.columns),
                "join": "measurement_event_id exact join",
            },
            report={"note": "between-gate delay is diagnostic (NOT tof_us)"},
            battery_id=b,
            experiment_id=e,
            gate_set_id=gate_ref.artifact_id,
            output_root=Path(ctx.processed_root),
        )
        return {
            "artifact_id": gate_ref.artifact_id,
            "path": str(Path(ctx.processed_root) / paths["analysis_parquet"]).rsplit("/", 1)[0],
            "manifest_path": str(Path(ctx.processed_root) / paths["analysis_manifest"]),
            "producer_version": self.node_version,
            "metrics": {"rows": len(analysis_full)},
        }


class DatasetNode(WorkflowNode):
    node_type = "DATASET"

    def requirements(self, plan, inputs):
        return ArtifactRequirements(
            artifact_type="DATASET",
            manifest_name="dataset_manifest.json",
            identity=ArtifactIdentity(
                battery_id=plan.project.battery_id, experiment_id=plan.project.experiment_id
            ),
            output_rel_dir=f"datasets/{plan.project.battery_id}/{plan.project.experiment_id}/{'SOC' if (plan.target or 'soc').startswith('soc') else 'SOH_CAPACITY'}",
            id_key="dataset_id",
            version_key="dataset_builder_version",
            expected_version=self.node_version,
            status_key="dataset_status",
            extra_match={
                k: v
                for k, v in {
                    # SOH legacy builder ignores selected_features — only pin when selection applies
                    "selected_features": (
                        plan.features.get("selected_features")
                        if (plan.target or "soc").startswith("soc")
                        else None
                    ),
                    "target_name": plan.target,
                }.items()
                if v is not None
            },
        )

    def output_rel_dir(self, plan):
        family = "SOC" if (plan.target or "soc").startswith("soc") else "SOH_CAPACITY"
        return f"datasets/{plan.project.battery_id}/{plan.project.experiment_id}/{family}"

    def run(self, plan, inputs, ctx):
        b, e = plan.project.battery_id, plan.project.experiment_id
        from battery_workbench.datasets.builder import build_soc_dataset, build_soh_dataset
        from battery_workbench.datasets.persistence import write_dataset_payload
        from battery_workbench.datasets.schemas import DatasetConfig

        features_ref = inputs["ULTRASOUND_FEATURES"]
        feature_frame = pd.read_parquet(Path(features_ref.path) / "ultrasound_features.parquet")
        selected = list(plan.features.get("selected_features") or [])
        # BRW-017 core alias, when explicitly selected
        if "amplitude_a_u" in selected and "amplitude_a_u" not in feature_frame.columns:
            feature_frame["amplitude_a_u"] = feature_frame["waveform_abs_peak_a_u"]
        labels_dir = Path(ctx.processed_root) / "labels" / b / e
        event_labels = pd.read_parquet(labels_dir / "event_labels.parquet")
        cycle_labels = pd.read_parquet(labels_dir / "cycle_labels.parquet")
        slice_ref = inputs.get("ANALYSIS_SLICE")
        config = DatasetConfig()
        target = plan.target or "soc_reference_percent"
        if target.startswith("soc"):
            report, df = build_soc_dataset(
                features=feature_frame,
                event_labels=event_labels,
                cycle_labels=cycle_labels,
                config=config,
                analysis_slice_id=slice_ref.artifact_id if slice_ref else "",
                feature_set_id=features_ref.artifact_id,
                label_set_id=inputs["REFERENCE_LABELS"].artifact_id,
                parameter_set_id=inputs["PARAMETER_SET"].artifact_id,
                feature_set_path=Path(features_ref.path) / "ultrasound_features.parquet",
                label_set_path=labels_dir / "event_labels.parquet",
                selected_features=selected or None,
            )
        else:
            report, df = build_soh_dataset(
                features=feature_frame,
                event_labels=event_labels,
                cycle_labels=cycle_labels,
                config=config,
                analysis_slice_id=slice_ref.artifact_id if slice_ref else "",
                feature_set_id=features_ref.artifact_id,
                label_set_id=inputs["REFERENCE_LABELS"].artifact_id,
                parameter_set_id=inputs["PARAMETER_SET"].artifact_id,
                feature_set_path=Path(features_ref.path) / "ultrasound_features.parquet",
                label_set_path=labels_dir / "event_labels.parquet",
                selected_features=selected or None,
            )
        payload = write_dataset_payload(
            report=report,
            df=df,
            config=config,
            battery_id=b,
            experiment_id=e,
            dataset_family="SOC" if target.startswith("soc") else "SOH_CAPACITY",
            feature_set_path=Path(features_ref.path) / "ultrasound_features.parquet",
            label_set_path=labels_dir / "event_labels.parquet",
            output_root=Path(ctx.processed_root) / "datasets",
        )
        return {
            "artifact_id": report.dataset_id,
            "path": str(Path(payload["dataset"]).parent),
            "manifest_path": payload["dataset_manifest"],
            "producer_version": "0.1.0",
            "limitations": list(report.limitations),
            "metrics": {
                "status": report.dataset_status,
                "eligible_rows": report.eligible_rows,
                "predictors": len(report.predictor_columns),
            },
        }


def default_nodes() -> list[WorkflowNode]:
    return [
        ElectricalCanonicalNode(),
        UltrasoundCanonicalNode(),
        TimeAnchorNode(),
        UltrasoundTimestampsNode(),
        SynchronizationNode(),
        MeasurementEventsNode(),
        AnalysisSliceNode(),
        UltrasoundFeaturesNode(),
        ReferenceLabelsNode(),
        ParameterSetNode(),
        TofActivationNode(),
        GatedFeaturesNode(),
        FeatureLabelAnalysisNode(),
        DatasetNode(),
    ]

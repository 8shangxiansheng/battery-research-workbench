"""BRW-024 WorkbenchService — application facade shared by UI / Agent / API.

Wraps BRW-015 parameter registry, BRW-018 gates, BRW-019 orchestrator,
BRW-020 splits, BRW-021 feature analysis, BRW-022 modeling, BRW-023
reporting. No scientific algorithms live here — this layer only
orchestrates, serializes, and maps errors. Deterministic creates reuse
canonical artifacts via their semantic IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, ClassVar

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.orchestrator.engine import OrchestratorError
from battery_workbench.orchestrator.service import ScientificRunService
from battery_workbench.reporting.collector import (
    collect_evidence_registry,
    collect_experiment_record,
    collect_limitation_registry,
    collect_results,
)

SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@-]+$")


def validate_id(value: str, field: str = "id") -> str:
    if not SAFE_ID.match(value) or ".." in value:
        raise APIError(ErrorCode.VALIDATION_ERROR, f"invalid {field}", {"value": value})
    return value


_DATASET_ID = "DS::6a3142e5186fc684964ff09e"
_SPLIT_ID = "SPLIT::062cf007d21578a11ab2d728"

_TOF_REASON = "sampling rate/time-zero and arrival detector are not validated"
_SOC_REASON = "retrospective protocol-anchored reference, not true SOC"


class WorkbenchService:
    """Application service — the only public seam HTTP routes call into."""

    def __init__(
        self,
        *,
        raw_root: Path | None = None,
        processed_root: Path | None = None,
        runs_root: Path | None = None,
    ) -> None:
        self.raw_root = Path(raw_root) if raw_root else Path("data/raw")
        self.processed_root = Path(processed_root) if processed_root else Path("data/processed")
        self.runs_root = (
            Path(runs_root) if runs_root else self.processed_root.parent / "artifacts" / "runs"
        )
        self._runs = ScientificRunService(
            raw_root=self.raw_root, processed_root=self.processed_root
        )
        self._idempotency: dict[str, dict[str, Any]] = {}
        from battery_workbench.intake.engine import IntakeEngine

        self.intake = IntakeEngine(
            raw_root=self.raw_root,
            work_root=self.processed_root.parent / "artifacts",
        )

    # ---------- system ----------
    def version(self) -> dict[str, Any]:
        return {"version": "0.1.0", "api_version": "v1"}

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def capabilities(self) -> dict[str, Any]:
        return {
            "software_capabilities": {
                "sync_schema": "0.2.0",
                "profiles": [
                    "INGEST_TO_MEASUREMENT_EVENTS",
                    "SCIENTIFIC_ANALYSIS",
                    "FULL_PRE_MODEL",
                ],
                "feature_analysis_policies": [
                    "EXPLORATORY_FULL_DATA",
                    "TRAIN_ONLY_ML_SAFE",
                ],
                "split_policies": ["LEAVE_ONE_GROUP_OUT"],
                "modeling_policy": "FIXED_BASELINE_PROTOCOL",
                "evidence_types": [
                    "DIRECT_CURRENT_ARTIFACT",
                    "PRIOR_AUDIT",
                    "SOURCE_INFERENCE",
                    "DERIVED_COMPUTATION",
                    "USER_PROVIDED_CONTEXT",
                    "BLOCKED",
                    "UNAVAILABLE",
                ],
            },
            "experiment_readiness": {
                "SOH": "NOT_READY_FOR_MODEL_EVALUATION",
                "TOF": "BLOCKED",
                "SOC": "LIMITED_CROSS_CYCLE_EVALUATION",
            },
        }

    # ---------- experiments ----------
    def list_experiments(self) -> list[dict[str, Any]]:
        if not self.raw_root.is_dir():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "raw data environment unavailable",
            )
        exp_root = self.processed_root / "datasets"
        items: list[dict[str, Any]] = []
        if not exp_root.is_dir():
            return items
        for b in sorted(exp_root.iterdir()):
            if not b.is_dir():
                continue
            for e in sorted(b.iterdir()):
                if e.is_dir():
                    try:
                        items.append(self._experiment_summary(b.name, e.name))
                    except APIError:
                        continue
        return items

    def get_experiment(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        return self._experiment_summary(battery_id, experiment_id)

    def _experiment_summary(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        self._require_experiment(battery_id, experiment_id)
        record = collect_experiment_record(self.processed_root, battery_id, experiment_id)
        return {
            "battery_id": record.battery_id,
            "experiment_id": record.experiment_id,
            "experiment_composite_id": f"{record.battery_id}/{record.experiment_id}",
            "scientific_status": record.scientific_status,
            "limitations": record.limitations,
            "run_ids": record.run_ids,
            "latest_canonical_artifacts": record.latest_canonical_artifacts,
        }

    def get_workspace_summary(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        summary = self._experiment_summary(battery_id, experiment_id)
        limitations = collect_limitation_registry()
        results = collect_results(self.processed_root, battery_id, experiment_id)
        readiness = {r.result_id: r.value for r in results if r.result_type == "READINESS"}
        return {
            **summary,
            "limitations_registry": limitations,
            "readiness": readiness,
            "next_actions": [
                "resolve pending user actions",
                "review feature selection",
                "generate report",
            ],
        }

    def get_status(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        """Canonical status: TOF/SOH/SOC/sync with null+reason, never fake values."""
        self._require_experiment(battery_id, experiment_id)
        return {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "synchronization": {"validated_sync": False, "timebase_status": "PROVISIONAL"},
            "soc": {
                "value": None,
                "status": "RETROSPECTIVE_SOC_REFERENCE",
                "reason": _SOC_REASON,
            },
            "soh": {
                "value": None,
                "status": "NOT_READY",
                "reason": "two independent states; no model evaluation",
            },
            "tof": {"value": None, "status": "BLOCKED", "reason": _TOF_REASON},
            "scientific_status": "READY_FOR_LIMITED_EVALUATION",
        }

    _EXPERIMENT_BASES = (
        "datasets",
        "labels",
        "synchronization",
        "parameters",
        "splits",
        "models",
        "gated_features",
        "feature_analysis",
        "features",
    )

    def _experiment_exists(self, battery_id: str, experiment_id: str) -> bool:
        if (self.raw_root / "batteries" / battery_id / experiment_id).is_dir():
            return True
        return any(
            (self.processed_root / base / battery_id / experiment_id).is_dir()
            for base in self._EXPERIMENT_BASES
        )

    def _require_experiment(self, battery_id: str, experiment_id: str) -> None:
        if not self._experiment_exists(battery_id, experiment_id):
            raise APIError(ErrorCode.NOT_FOUND, "experiment not found")

    def get_lineage(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        """Lineage from canonical artifact IDs only — never filesystem paths."""
        self._require_experiment(battery_id, experiment_id)
        summary = self._experiment_summary(battery_id, experiment_id)
        canonical = summary.get("latest_canonical_artifacts") or {}
        chain: list[dict[str, Any]] = []
        type_map = {
            "dataset_id": "DATASET",
            "split_id": "SPLIT",
            "gate_set_id": "GATESET",
            "feature_set_id": "FEATURE_SET",
            "label_set_id": "LABEL_SET",
        }
        for key, artifact_type in type_map.items():
            artifact_id = canonical.get(key)
            if not artifact_id:
                chain.append(
                    {"artifact_type": artifact_type, "artifact_id": None, "status": "NOT_AVAILABLE"}
                )
                continue
            available = self._artifact_dir_exists(
                artifact_type, artifact_id, battery_id, experiment_id
            )
            chain.append(
                {
                    "artifact_type": artifact_type,
                    "artifact_id": artifact_id,
                    "status": "AVAILABLE" if available else "NOT_AVAILABLE",
                }
            )
        return {
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "lineage_chain": chain,
        }

    def _artifact_dir_exists(
        self, artifact_type: str, artifact_id: str, battery_id: str, experiment_id: str
    ) -> bool:
        roots = {
            "DATASET": self.processed_root / "datasets" / battery_id / experiment_id,
            "SPLIT": self.processed_root / "splits" / battery_id / experiment_id,
            "GATESET": self.processed_root / "gated_features" / battery_id / experiment_id,
        }
        root = roots.get(artifact_type)
        if root is None or not root.is_dir():
            return False
        return any(artifact_id in p.name for p in root.rglob("*") if p.is_dir())

    def get_results(
        self, battery_id: str, experiment_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        results = collect_results(self.processed_root, battery_id, experiment_id)
        items = [r.model_dump(mode="json") for r in results]
        items.sort(key=lambda r: r["result_id"])
        if cursor:
            items = [r for r in items if r["result_id"] > cursor]
        return items[:limit]

    def get_limitations(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        return list(collect_limitation_registry())

    def get_evidence(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        results = collect_results(self.processed_root, battery_id, experiment_id)
        ev = collect_evidence_registry(results)
        return [
            {
                "evidence_type": e["evidence_type"],
                "evidence_ref": e["evidence_ref"],
                "artifact_id": e.get("artifact_id"),
                "artifact_availability": (
                    "AVAILABLE"
                    if self._evidence_file_exists(e["evidence_ref"], battery_id, experiment_id)
                    else "NOT_AVAILABLE_CURRENT_ENVIRONMENT"
                ),
            }
            for e in ev
        ]

    def _evidence_file_exists(self, ref: str, battery_id: str, experiment_id: str) -> bool:
        if not ref:
            return False
        for base in self._EXPERIMENT_BASES:
            root = self.processed_root / base / battery_id / experiment_id
            if root.is_dir():
                for p in root.rglob(ref):
                    if p.is_file():
                        return True
        return False

    # ---------- runs ----------
    def plan_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._runs.plan_run(runs_root=self.runs_root, **payload)
        return plan.model_dump(mode="json")

    def dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._runs.plan_run(runs_root=self.runs_root, **payload)
        result = self._runs.dry_run(plan)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if isinstance(result, dict):
            return result
        return {"result": str(result)}

    def start_run(
        self, payload: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self._idempotency.get(idempotency_key)
            if existing is not None:
                if existing["payload"] == payload:
                    return existing["result"]
                raise APIError(ErrorCode.CONFLICT, "idempotency key reused with different payload")
        plan = self._runs.plan_run(runs_root=self.runs_root, **payload)
        result = self._runs.start_run(plan, runs_root=self.runs_root)
        if idempotency_key:
            self._idempotency[idempotency_key] = {"payload": payload, "result": result}
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        try:
            return self._runs.get_run(run_id, runs_root=self.runs_root)
        except (FileNotFoundError, OrchestratorError) as e:
            raise APIError(ErrorCode.NOT_FOUND, "run not found") from e

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        validate_id(run_id, "run_id")
        try:
            return self._runs.list_run_events(run_id, runs_root=self.runs_root)
        except (FileNotFoundError, OrchestratorError) as e:
            raise APIError(ErrorCode.NOT_FOUND, "run not found") from e

    def list_user_actions(self, run_id: str) -> list[dict[str, Any]]:
        validate_id(run_id, "run_id")
        try:
            return self._runs.list_user_actions(run_id, runs_root=self.runs_root)
        except (FileNotFoundError, OrchestratorError) as e:
            raise APIError(ErrorCode.NOT_FOUND, "run not found") from e

    _REQUIRED_ACTION_VALUES: ClassVar[dict[str, set[str]]] = {
        "MISSING_SAMPLING_RATE": {"ultrasound.sampling_rate_hz"},
    }

    def submit_user_action(
        self, run_id: str, action_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        validate_id(action_id, "action_id")
        actions = self.list_user_actions(run_id)
        action = next((a for a in actions if a.get("action_id") == action_id), None)
        if action is None:
            raise APIError(ErrorCode.NOT_FOUND, "user action not found")
        action_type = action.get("action_type") or action.get("action_kind") or ""
        required = self._REQUIRED_ACTION_VALUES.get(action_type, set())
        if required and not required.issubset(values.keys()):
            raise APIError(
                ErrorCode.SCIENTIFIC_ACTION_REQUIRED,
                "required values missing for this action",
                {"required": sorted(required), "provided": sorted(values.keys())},
            )
        return self._runs.submit_user_action(
            run_id, action_id, values=values, runs_root=self.runs_root
        )

    def resume_run(self, run_id: str) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        return self._runs.resume_run(run_id, runs_root=self.runs_root)

    def retry_node(self, run_id: str, node_id: str) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        validate_id(node_id, "node_id")
        return self._runs.retry_node(run_id, node_id, runs_root=self.runs_root)

    # ---------- parameters (BRW-015) ----------
    def create_parameter_set(
        self, battery_id: str, experiment_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        from battery_workbench.parameters.service import build_parameter_set

        values = payload.get("values") or {}
        overrides: dict[str, dict[str, Any]] = {}
        for name, entry in values.items():
            if not isinstance(entry, dict):
                raise APIError(
                    ErrorCode.VALIDATION_ERROR,
                    "parameter values must be {name: {value, unit}}",
                )
            overrides[name] = dict(entry)
            overrides[name]["source_reference"] = payload.get("source", "api:user-supplied")
            if payload.get("verified"):
                overrides[name]["verification_status"] = "VERIFIED"
        report = build_parameter_set(
            output_root=self.processed_root,
            user_overrides=overrides,
            battery_id=battery_id,
            experiment_id=experiment_id,
        )
        return {
            "parameter_set_id": report.parameter_set_id,
            "sampling_rate_status": (
                "VERIFIED" if report.sampling_rate_hz and payload.get("verified") else "UNVERIFIED"
            ),
            "status": report.status,
        }

    def list_parameters(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        params_dir = self.processed_root / "parameters" / battery_id / experiment_id
        if not params_dir.is_dir():
            raise APIError(ErrorCode.NOT_FOUND, "parameters not available")
        items: list[dict[str, Any]] = []
        for ps_dir in sorted(params_dir.iterdir()):
            manifest = ps_dir / "effective_parameters.json"
            if manifest.is_file():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                items.append({"parameter_set_id": ps_dir.name, "effective": data})
        return items

    # ---------- gates (BRW-018) ----------
    def create_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        from battery_workbench.gates.persistence import build_gate_set_id
        from battery_workbench.gates.schemas import GateSpec

        required = (
            "battery_id",
            "experiment_id",
            "gate_name",
            "start_sample",
            "end_sample",
            "waveform_length",
        )
        missing = [k for k in required if k not in payload]
        if missing:
            raise APIError(
                ErrorCode.VALIDATION_ERROR, "missing required fields", {"missing": missing}
            )
        try:
            gate = GateSpec(
                gate_name=payload["gate_name"],
                start_sample=int(payload["start_sample"]),
                end_sample=int(payload["end_sample"]),
                waveform_length=int(payload["waveform_length"]),
                source="api:workbench-service",
                created_by="brw024",
            )
        except ValueError as e:
            raise APIError(ErrorCode.VALIDATION_ERROR, str(e)) from e
        gate_set_id = build_gate_set_id([gate])
        # deterministic reuse: persist a small manifest keyed by gate_set_id
        out_dir = (
            self.processed_root
            / "gates"
            / payload["battery_id"]
            / payload["experiment_id"]
            / gate_set_id
        )
        reuse = out_dir.is_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "gate_manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(
                    {
                        "gate_set_id": gate_set_id,
                        "gates": [gate.model_dump(mode="json")],
                        "battery_id": payload["battery_id"],
                        "experiment_id": payload["experiment_id"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return {
            "gate_id": gate.gate_id,
            "gate_set_id": gate_set_id,
            "reuse_status": "REUSED" if reuse else "CREATED",
        }

    def get_gate(self, gate_id: str) -> dict[str, Any]:
        validate_id(gate_id, "gate_id")
        gates_root = self.processed_root / "gates"
        if gates_root.is_dir():
            for manifest in sorted(gates_root.rglob("gate_manifest.json")):
                data = json.loads(manifest.read_text(encoding="utf-8"))
                for g in data.get("gates", []):
                    if g.get("gate_id") == gate_id:
                        return {"gate_id": gate_id, **g}
            for gs_dir in sorted(gates_root.iterdir()):
                if gs_dir.name == gate_id:
                    return {"gate_set_id": gate_id}
        # also search gated_features manifests (BRW-018 canonical store)
        gf_root = self.processed_root / "gated_features"
        if gf_root.is_dir():
            for manifest in sorted(gf_root.rglob("gate_specs.json")):
                specs = json.loads(manifest.read_text(encoding="utf-8"))
                for g in specs:
                    if g.get("gate_id") == gate_id:
                        return {"gate_id": gate_id, **g}
            for gs_dir in sorted(gf_root.rglob("*")):
                if gs_dir.is_dir() and gs_dir.name == gate_id:
                    return {"gate_set_id": gate_id}
        raise APIError(ErrorCode.NOT_FOUND, "gate not found")

    def list_gates(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root_name in ("gates", "gated_features"):
            root = self.processed_root / root_name / battery_id / experiment_id
            if not root.is_dir():
                continue
            for d in sorted(root.iterdir()):
                if not d.is_dir():
                    continue
                # individual gate entries from manifests
                for mname in ("gate_manifest.json", "gate_specs.json"):
                    mpath = d / mname
                    if mpath.is_file():
                        try:
                            specs = json.loads(mpath.read_text(encoding="utf-8"))
                        except (json.JSONDecodeError, OSError):
                            continue
                        for g in specs.get("gates", specs) if isinstance(specs, dict) else specs:
                            if isinstance(g, dict) and g.get("gate_id"):
                                gid = g["gate_id"]
                                if gid not in seen:
                                    seen.add(gid)
                                    items.append(
                                        {
                                            "gate_id": gid,
                                            "gate_set_id": d.name,
                                            **{k: v for k, v in g.items() if k != "gate_id"},
                                        }
                                    )
                if d.name not in seen:
                    seen.add(d.name)
                    items.append({"gate_id": d.name, "gate_set_id": d.name})
        if not items:
            raise APIError(ErrorCode.NOT_FOUND, "gates not available")
        return items

    # ---------- features ----------
    def list_features(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        from battery_workbench.feature_registry.registry import ALL_REGISTRY_ENTRIES
        from battery_workbench.feature_registry.schemas import AvailabilityStatus

        self._require_experiment(battery_id, experiment_id)
        items: list[dict[str, Any]] = []
        for entry in ALL_REGISTRY_ENTRIES:
            status = entry.availability_status.value
            if status == AvailabilityStatus.AVAILABLE.value:
                availability = "AVAILABLE"
                missing_reason = None
            elif (
                status == AvailabilityStatus.UNAVAILABLE_MISSING_PARAMETER.value
                or status == AvailabilityStatus.UNAVAILABLE_CAPABILITY_BLOCKED.value
            ):
                availability = "NOT_AVAILABLE_CURRENT_ENVIRONMENT"
                missing_reason = entry.availability_reason
            else:
                availability = "NOT_AVAILABLE_CURRENT_ENVIRONMENT"
                missing_reason = entry.availability_reason
            items.append(
                {
                    "feature_name": entry.feature_name,
                    "role": entry.scientific_role,
                    "availability": availability,
                    "gate_id": None,
                    "tof_definition_id": None,
                    "missing_reason": missing_reason,
                }
            )
        return items

    # ---------- feature analysis (BRW-021) ----------
    def create_feature_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        from battery_workbench.feature_analysis.schemas import FeatureAnalysisSpec

        required = ("battery_id", "experiment_id", "analysis_mode", "target", "candidate_features")
        missing = [k for k in required if k not in payload]
        if missing:
            raise APIError(
                ErrorCode.VALIDATION_ERROR, "missing required fields", {"missing": missing}
            )
        try:
            spec = FeatureAnalysisSpec(
                analysis_mode=payload["analysis_mode"],
                target=payload["target"],
                candidate_features=list(payload["candidate_features"]),
            )
        except ValueError as e:
            raise APIError(ErrorCode.VALIDATION_ERROR, str(e)) from e
        return {
            "analysis_id": spec.analysis_id,
            "analysis_mode": spec.analysis_mode.value,
            "reuse_status": "REUSED",
        }

    def get_feature_analysis(self, analysis_id: str) -> dict[str, Any]:
        validate_id(analysis_id, "analysis_id")
        fa_root = self.processed_root / "feature_analysis"
        if fa_root.is_dir():
            for d in sorted(fa_root.rglob(analysis_id)):
                if d.is_dir():
                    return {"analysis_id": analysis_id, "status": "AVAILABLE"}
        raise APIError(ErrorCode.NOT_FOUND, "feature analysis not found")

    # ---------- datasets (deterministic, reuse-only) ----------
    def create_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "path" in payload:
            raise APIError(ErrorCode.VALIDATION_ERROR, "client path input is not accepted")
        validate_id(payload.get("battery_id", ""), "battery_id")
        validate_id(payload.get("experiment_id", ""), "experiment_id")
        battery_id = payload["battery_id"]
        experiment_id = payload["experiment_id"]
        family = payload.get("dataset_family", "SOC")
        explicit_spec = any(k in payload for k in ("dataset_family", "target", "selected_features"))
        family_dir = self.processed_root / "datasets" / battery_id / experiment_id / family
        # reuse canonical artifact when the request is a minimal resolve request
        if family_dir.is_dir() and (
            not explicit_spec or family == payload.get("dataset_family") and "target" not in payload
        ):
            for candidate in sorted(family_dir.iterdir()):
                if candidate.is_dir() and candidate.name.startswith("DS::"):
                    return {
                        "dataset_id": candidate.name,
                        "status": "REUSED",
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "selected_features": payload.get("selected_features", []),
                        "limitations": ["LIMITED_CROSS_CYCLE_GENERALIZATION"],
                    }
        if explicit_spec:
            canonical = json.dumps(
                {
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "dataset_family": family,
                    "target": payload.get("target"),
                    "selected_features": sorted(payload.get("selected_features", [])),
                    "spec_version": "0.1.0",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            dataset_id = "DS::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
            spec_dir = family_dir / dataset_id
            reuse = (spec_dir / "dataset_manifest.json").is_file()
            if not reuse:
                spec_dir.mkdir(parents=True, exist_ok=True)
                (spec_dir / "dataset_manifest.json").write_text(
                    json.dumps(
                        {
                            "dataset_id": dataset_id,
                            "dataset_family": family,
                            "target_name": payload.get("target", ""),
                            "dataset_status": "SPEC_PENDING_RUN",
                            "battery_id": battery_id,
                            "experiment_id": experiment_id,
                            "selected_features": sorted(payload.get("selected_features", [])),
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return {
                "dataset_id": dataset_id,
                "status": "REUSED" if reuse else "CREATED",
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "selected_features": payload.get("selected_features", []),
                "limitations": ["LIMITED_CROSS_CYCLE_GENERALIZATION"],
                "materialization_status": "SPEC_PENDING_RUN",
            }
        raise APIError(
            ErrorCode.SCIENTIFIC_ACTION_REQUIRED,
            "dataset creation requires a scientific run",
            {"suggested_endpoint": "POST /api/v1/runs"},
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        validate_id(artifact_id, "artifact_id")
        prefix = artifact_id.split("::")[0] if "::" in artifact_id else "UNKNOWN"
        # dataset manifest lookup
        if prefix == "DS":
            for manifest in sorted(
                (self.processed_root / "datasets").rglob("dataset_manifest.json")
            ):
                if manifest.parent.name == artifact_id:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    body = {
                        "artifact_id": artifact_id,
                        "artifact_type": "DATASET",
                        "availability": "AVAILABLE",
                        "status": data.get("dataset_status", ""),
                        "row_count": data.get("joined_rows"),
                        "preview": [],
                    }
                    sanitized = {k: v for k, v in data.items() if k != "output_path"}
                    body["fields"] = sanitized
                    return body
        if prefix == "SPLIT":
            for manifest in sorted((self.processed_root / "splits").rglob("split_manifest.json")):
                if manifest.parent.name == artifact_id:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "SPLIT",
                        "availability": "AVAILABLE",
                        "status": data.get("readiness_status", ""),
                        "row_count": None,
                        "preview": [],
                    }
        if prefix in ("GATE", "GATESET"):
            return self.get_gate(artifact_id)
        # generic semantic lookup
        return {
            "artifact_id": artifact_id,
            "artifact_type": prefix,
            "availability": "AVAILABLE",
            "status": "",
            "row_count": None,
            "preview": [],
        }

    # ---------- splits (deterministic, reuse-only) ----------
    def create_split(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = payload.get("dataset_id", "")
        validate_id(dataset_id, "dataset_id")
        battery_id = payload.get("battery_id", "CELL_001")
        experiment_id = payload.get("experiment_id", "EXP_001")
        split_root = self.processed_root / "splits" / battery_id / experiment_id / dataset_id
        if split_root.is_dir():
            for candidate in sorted(split_root.iterdir()):
                if candidate.is_dir() and candidate.name.startswith("SPLIT::"):
                    return {
                        "split_id": candidate.name,
                        "dataset_id": dataset_id,
                        "status": "REUSED",
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "group_column": "cycle_group_id",
                        "require_roles": ["TRAIN", "HELD_OUT"],
                    }
        # deterministic spec id (reuse across app restarts via spec_dir)
        canonical = json.dumps(
            {
                "strategy": payload.get("strategy", "LEAVE_ONE_GROUP_OUT"),
                "split_unit": "CYCLE",
                "group_column": "cycle_group_id",
                "dataset_id": dataset_id,
                "explicit_holdout_groups": [],
                "k": None,
                "require_roles": ["TRAIN", "HELD_OUT"],
                "split_version": "0.1.0",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        split_id = "SPLIT::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        spec_dir = split_root / split_id
        reuse = (spec_dir / "split_manifest.json").is_file()
        if not reuse:
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "split_manifest.json").write_text(
                json.dumps(
                    {
                        "split_id": split_id,
                        "dataset_id": dataset_id,
                        "strategy": payload.get("strategy", "LEAVE_ONE_GROUP_OUT"),
                        "group_column": "cycle_group_id",
                        "require_roles": ["TRAIN", "HELD_OUT"],
                        "readiness_status": "SPEC_PENDING_RUN",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return {
            "split_id": split_id,
            "dataset_id": dataset_id,
            "status": "REUSED" if reuse else "CREATED",
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "group_column": "cycle_group_id",
            "require_roles": ["TRAIN", "HELD_OUT"],
        }

    # ---------- modeling (fixed baseline, no tuning) ----------
    def create_baseline_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        from battery_workbench.modeling.schemas import ModelSpec

        required = (
            "battery_id",
            "experiment_id",
            "strategy",
            "dataset_id",
            "split_id",
            "fold_index",
            "selection_id",
            "selected_features",
        )
        missing = [k for k in required if k not in payload]
        if missing:
            raise APIError(
                ErrorCode.VALIDATION_ERROR, "missing required fields", {"missing": missing}
            )
        try:
            spec = ModelSpec(
                strategy=payload["strategy"],
                dataset_id=payload["dataset_id"],
                split_id=payload["split_id"],
                fold_index=int(payload["fold_index"]),
                selection_id=payload["selection_id"],
                selected_features=list(payload["selected_features"]),
            )
        except ValueError as e:
            raise APIError(ErrorCode.VALIDATION_ERROR, str(e)) from e
        return {"model_id": spec.model_id, "tuning": False, "reuse_status": "REUSED"}

    # ---------- reports (BRW-023) ----------
    def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        battery_id = payload.get("battery_id", "CELL_001")
        experiment_id = payload.get("experiment_id", "EXP_001")
        target = payload.get("target", "soc_reference_percent")
        self._require_experiment(battery_id, experiment_id)
        canonical = json.dumps(
            {
                "target": target,
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "source_artifact_ids": [],
                "reporting_policy_version": "0.1.0",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        report_id = "REPORT::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        report_dir = (
            self.processed_root / "artifacts" / battery_id / experiment_id / "reports" / report_id
        )
        reuse = (report_dir / "scientific_report.json").is_file()
        limitations = [l["code"] for l in collect_limitation_registry()]
        if not reuse:
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "scientific_report.json").write_text(
                json.dumps(
                    {
                        "report_id": report_id,
                        "target": target,
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "limitations": limitations,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return {
            "report_id": report_id,
            "target": target,
            "battery_id": battery_id,
            "experiment_id": experiment_id,
            "reuse_status": "REUSED" if reuse else "CREATED",
            "limitations": limitations,
        }

    def list_reports(
        self, battery_id: str, experiment_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        reports_root = self.processed_root / "artifacts" / battery_id / experiment_id / "reports"
        items: list[dict[str, Any]] = []
        if reports_root.is_dir():
            for report_file in sorted(reports_root.rglob("scientific_report.json")):
                data = json.loads(report_file.read_text(encoding="utf-8"))
                items.append(data)
        items.sort(key=lambda r: r.get("report_id", ""))
        if cursor:
            items = [r for r in items if r.get("report_id", "") > cursor]
        return items[:limit]

    def get_report(self, report_id: str) -> dict[str, Any]:
        validate_id(report_id, "report_id")
        reports_root = self.processed_root / "artifacts"
        if reports_root.is_dir():
            for report_file in sorted(reports_root.rglob("scientific_report.json")):
                data = json.loads(report_file.read_text(encoding="utf-8"))
                if data.get("report_id") == report_id:
                    return data
        raise APIError(ErrorCode.NOT_FOUND, "report not found")

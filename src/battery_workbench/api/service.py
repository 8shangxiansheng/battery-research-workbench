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
import math
import re
import uuid
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
TEMPERATURE_VARIATION_MIN_C = 2.0


def _feature_selection_status(selection: dict[str, Any]) -> str:
    """Serialize persisted selection commit state without inferring from rows."""
    status_map = {
        "CONFIRMED": "CONFIRMED",
        "WAITING_FOR_USER": "AWAITING_CONFIRMATION",
        "NO_SELECTION": "NO_SELECTION",
        "NOT_REQUESTED": "NOT_REQUESTED",
    }
    return status_map.get(str(selection.get("commit_status") or ""), "NOT_ASSESSED")


def temperature_target_gate(
    *, valid_count: int, temp_range_c: float | None, evidence_verified: bool = False
) -> tuple[bool, str]:
    """Temperature target gate (pure; no artifact access).

    A measured channel and sufficient observed range are necessary but not
    sufficient. The target stays blocked until sensor location/calibration
    evidence is verified. ``evidence_verified`` must come from a trusted
    evidence workflow; the current dataset service deliberately leaves it
    false because no such registry is available yet.
    """
    if valid_count <= 0 or temp_range_c is None:
        return False, "本实验无温度通道，无可用目标"
    if temp_range_c < TEMPERATURE_VARIATION_MIN_C:
        return (
            False,
            (
                f"温度极差 {temp_range_c:.2f}°C < {TEMPERATURE_VARIATION_MIN_C:.1f}°C，"
                "不足以支撑逐帧建模结论"
            ),
        )
    if not evidence_verified:
        return (
            False,
            (
                "sensor location/calibration evidence is not verified; "
                "temperature readings are not an eligible modeling target"
            ),
        )
    return True, ""


def _cohort_evaluation_artifacts_current(processed_root: Path, manifest: dict[str, Any]) -> bool:
    """Verify every declared cohort evaluation artifact against its checksum."""
    artifacts = manifest.get("artifacts")
    checksums = manifest.get("artifact_checksums")
    required_names = {
        "held_out_predictions",
        "split_assignments",
        "cohort_report_json",
        "cohort_report_html",
    }
    if (
        not isinstance(artifacts, dict)
        or not isinstance(checksums, dict)
        or set(artifacts) != required_names
        or set(checksums) != required_names
    ):
        return False
    root = Path(processed_root).resolve()
    for name, expected_checksum in checksums.items():
        relative_path = Path(str(artifacts.get(name, "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return False
        artifact_path = (root / relative_path).resolve()
        if root not in artifact_path.parents or not artifact_path.is_file():
            return False
        digest = hashlib.sha256()
        with artifact_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_checksum:
            return False
    return True


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

    def modeling_strategies(self) -> dict[str, Any]:
        """Canonical fixed-baseline registry snapshot for UI model selection.

        The UI renders checkboxes from this endpoint instead of a hardcoded
        list, so newly registered STRATEGIES appear without frontend changes.
        """
        from battery_workbench.modeling import engine as modeling_engine
        from battery_workbench.modeling.schemas import (
            FIXED_CONFIGS,
            STOCHASTIC_STRATEGIES,
            STRATEGIES,
        )

        return {
            "strategies": [
                {
                    "strategy": strategy,
                    "fixed_config": dict(FIXED_CONFIGS[strategy]),
                    "stochastic": strategy in STOCHASTIC_STRATEGIES,
                    "scaled": strategy in modeling_engine.SCALED_STRATEGIES,
                }
                for strategy in STRATEGIES
            ],
            "policy": "FIXED_BASELINE_PROTOCOL",
        }

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
        record = collect_experiment_record(
            self.processed_root, battery_id, experiment_id, raw_root=self.raw_root
        )
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
        limitations = collect_limitation_registry(
            self.processed_root, battery_id, experiment_id, raw_root=self.raw_root
        )
        results = collect_results(
            self.processed_root, battery_id, experiment_id, raw_root=self.raw_root
        )
        readiness = {r.result_id: r.value for r in results if r.result_type == "READINESS"}
        next_actions = (
            ["repair source parser provenance before interpreting results"]
            if summary["scientific_status"] == "INTEGRITY_BLOCKED"
            else [
                "resolve pending user actions",
                "review feature selection",
                "generate report",
            ]
        )
        return {
            **summary,
            "limitations_registry": limitations,
            "readiness": readiness,
            "next_actions": next_actions,
        }

    def get_status(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        """Canonical status: TOF/SOH/SOC/sync with null+reason, never fake values.

        BRW-018R2: TOF readiness is resolved live from the same ladder the
        canonical-TOF pipeline uses (VERIFIED fs from the Parameter Registry +
        gate-calibration priority). A saved fs must be reflected here without
        a restart — otherwise the overview shows 'no reaction' after saving.
        """
        self._require_experiment(battery_id, experiment_id)
        from battery_workbench.provenance.parser_manifest import invalid_parser_source_modalities

        invalid_modalities = invalid_parser_source_modalities(
            self.processed_root,
            self.raw_root,
            battery_id,
            experiment_id,
        )
        if invalid_modalities:
            reason = "Parser 来源完整性无效；修复来源并复核 lineage 前不报告科研状态。"
            return {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "synchronization": {
                    "validated_sync": False,
                    "timebase_status": "NOT_EVALUATED",
                    "status": "INTEGRITY_BLOCKED",
                },
                "soc": {"value": None, "status": "INTEGRITY_BLOCKED", "reason": reason},
                "soh": {"value": None, "status": "INTEGRITY_BLOCKED", "reason": reason},
                "tof": {"value": None, "status": "INTEGRITY_BLOCKED", "reason": reason},
                "scientific_status": "INTEGRITY_BLOCKED",
                "invalid_modalities": invalid_modalities,
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            }
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
            "tof": self._resolve_tof_status(battery_id, experiment_id),
            "scientific_status": "READY_FOR_LIMITED_EVALUATION",
        }

    def _resolve_tof_status(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        """Live TOF readiness: fs (verified) + gate calibration provenance.

        value stays None (a single number is not the experiment's TOF); the
        status reports what the canonical pipeline would resolve right now.
        """
        # fs from the newest resolved parameter set (registry is the only source)
        fs_hz, fs_verified = None, False
        ps_dir = self.processed_root / "parameters" / battery_id / experiment_id
        if ps_dir.is_dir():
            from battery_workbench.features_physical.canonical_tof import effective_fs

            for manifest in sorted(ps_dir.glob("PS::*/effective_parameters.json")):
                try:
                    eff = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                eff = eff.get("effective_parameters") or eff
                fs, verified = effective_fs(eff, require_verified=True)
                if verified:
                    fs_hz, fs_verified = fs, True
                    break
                if fs is not None and fs_hz is None:
                    fs_hz = fs
        if not fs_verified:
            return {
                "value": None,
                "status": "BLOCKED",
                "reason": (
                    "sampling_rate_hz not VERIFIED in the Parameter Registry "
                    "(save alone does not verify; never guessed)"
                ),
                "sampling_rate_hz": fs_hz,
                "sampling_rate_verified": False,
            }
        # gates: confirmed experiment calibration or the explicit source template
        from battery_workbench.features.gate_calibration import resolve_tof_gate_calibration

        cal = resolve_tof_gate_calibration(battery_id, experiment_id, self.processed_root)
        return {
            "value": None,
            "status": "READY",
            "reason": (
                f"fs VERIFIED ({fs_hz / 1e6:g} MHz) + gate calibration "
                f"{cal['gate_calibration_id']} ({cal['source']}) — canonical "
                "envelope-peak TOF active"
            ),
            "sampling_rate_hz": fs_hz,
            "sampling_rate_verified": True,
            "gate_calibration_id": cal["gate_calibration_id"],
            "gate_calibration_source": cal["source"],
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

    def _assert_parser_provenance(
        self,
        battery_id: str,
        experiment_id: str,
        *,
        modalities: tuple[str, ...] = ("electrical", "ultrasound"),
    ) -> None:
        from battery_workbench.provenance.parser_manifest import (
            invalid_parser_source_modalities,
            parser_output_integrity_reasons,
        )

        invalid = sorted(
            set(
                invalid_parser_source_modalities(
                    self.processed_root,
                    self.raw_root,
                    battery_id,
                    experiment_id,
                )
            )
            & set(modalities)
        )
        if invalid:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "parser source provenance is invalid; dependent artifacts are blocked",
                {
                    "invalid_modalities": invalid,
                    "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                },
            )
        output_reasons = parser_output_integrity_reasons(
            self.processed_root, battery_id, experiment_id
        )
        invalid_outputs = {
            modality: reasons
            for modality, reasons in output_reasons.items()
            if modality in modalities and reasons
        }
        if invalid_outputs:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "parser output integrity is invalid; dependent artifacts are blocked",
                {
                    "invalid_modalities": sorted(invalid_outputs),
                    "integrity_reasons": invalid_outputs,
                    "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                },
            )

    def _assert_ultrasound_parser_provenance(self, battery_id: str, experiment_id: str) -> None:
        self._assert_parser_provenance(
            battery_id, experiment_id, modalities=("ultrasound",)
        )

    def get_lineage(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        """Lineage from canonical artifact IDs only — never filesystem paths."""
        self._require_experiment(battery_id, experiment_id)
        summary = self._experiment_summary(battery_id, experiment_id)
        canonical = summary.get("latest_canonical_artifacts") or {}
        type_map = {
            "dataset_id": "DATASET",
            "split_id": "SPLIT",
            "gate_set_id": "GATESET",
            "feature_set_id": "FEATURE_SET",
            "label_set_id": "LABEL_SET",
        }
        if summary.get("scientific_status") == "INTEGRITY_BLOCKED":
            return {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "source_integrity_status": "INTEGRITY_BLOCKED",
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                "lineage_chain": [
                    {
                        "artifact_type": artifact_type,
                        "artifact_id": None,
                        "status": "INTEGRITY_BLOCKED",
                    }
                    for artifact_type in type_map.values()
                ],
            }
        chain: list[dict[str, Any]] = []
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
        results = collect_results(
            self.processed_root, battery_id, experiment_id, raw_root=self.raw_root
        )
        items = [r.model_dump(mode="json") for r in results]
        items.sort(key=lambda r: r["result_id"])
        if cursor:
            items = [r for r in items if r["result_id"] > cursor]
        return items[:limit]

    def get_limitations(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        return list(
            collect_limitation_registry(
                self.processed_root,
                battery_id,
                experiment_id,
                raw_root=self.raw_root,
            )
        )

    def get_evidence(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        results = collect_results(
            self.processed_root, battery_id, experiment_id, raw_root=self.raw_root
        )
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
    def _plan_run_with_source_integrity(self, payload: dict[str, Any]):
        plan = self._runs.plan_run(runs_root=self.runs_root, **payload)
        from battery_workbench.provenance.parser_manifest import invalid_parser_source_modalities

        invalid = invalid_parser_source_modalities(
            self.processed_root,
            self.raw_root,
            plan.project.battery_id,
            plan.project.experiment_id,
        )
        if not invalid:
            return plan
        parser_stages = {
            "electrical": "ELECTRICAL_CANONICAL",
            "ultrasound": "ULTRASOUND_CANONICAL",
        }
        required_stages = {parser_stages[modality] for modality in invalid}
        requested_stages = set(plan.stages)
        if requested_stages != required_stages or len(plan.stages) != len(required_stages):
            raise APIError(
                ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                "source parser provenance is invalid; only an explicit parser-only recovery run is allowed",
                {
                    "invalid_modalities": invalid,
                    "required_profile": "INGEST_TO_MEASUREMENT_EVENTS",
                    "required_stages": sorted(required_stages),
                    "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                },
            )
        forced = sorted(set(plan.execution.force_recompute) | required_stages)
        return plan.model_copy(
            update={
                "execution": plan.execution.model_copy(update={"force_recompute": forced})
            }
        )

    def plan_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan_run_with_source_integrity(payload)
        return plan.model_dump(mode="json")

    def dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan_run_with_source_integrity(payload)
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
                    run_id = existing.get("result", {}).get("run_id")
                    if run_id:
                        self.get_run(str(run_id))
                    return existing["result"]
                raise APIError(ErrorCode.CONFLICT, "idempotency key reused with different payload")
        plan = self._plan_run_with_source_integrity(payload)
        result = self._runs.start_run(plan, runs_root=self.runs_root)
        if idempotency_key:
            self._idempotency[idempotency_key] = {"payload": payload, "result": result}
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        try:
            run = self._runs.get_run(run_id, runs_root=self.runs_root)
            self._assert_run_source_integrity(run)
            return run
        except (FileNotFoundError, OrchestratorError) as e:
            raise APIError(ErrorCode.NOT_FOUND, "run not found") from e

    def _assert_run_source_integrity(self, run: dict[str, Any]) -> None:
        """Block stale scientific run access/resume while allowing exact parser repair runs."""
        from battery_workbench.provenance.parser_manifest import invalid_parser_source_modalities

        battery_id = run.get("battery_id")
        experiment_id = run.get("experiment_id")
        if not isinstance(battery_id, str) or not isinstance(experiment_id, str):
            return
        invalid = invalid_parser_source_modalities(
            self.processed_root, self.raw_root, battery_id, experiment_id
        )
        if not invalid:
            return
        run_dir = Path(str(run.get("run_dir", ""))).resolve()
        try:
            run_dir.relative_to(self.runs_root.resolve())
            plan_path = run_dir / "analysis_plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            plan = None
        parser_stages = {
            "electrical": "ELECTRICAL_CANONICAL",
            "ultrasound": "ULTRASOUND_CANONICAL",
        }
        required = [parser_stages[modality] for modality in invalid]
        stages = plan.get("stages") if isinstance(plan, dict) else None
        parser_only = (
            isinstance(plan, dict)
            and plan.get("profile") == "INGEST_TO_MEASUREMENT_EVENTS"
            and plan.get("project")
            == {"battery_id": battery_id, "experiment_id": experiment_id}
            and plan.get("plan_id") == run.get("analysis_plan_id")
            and isinstance(stages, list)
            and len(stages) == len(required)
            and set(stages) == set(required)
        )
        if parser_only:
            return
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "run depends on invalid parser provenance; its outputs and actions are blocked",
            {
                "run_id": run.get("run_id"),
                "invalid_modalities": invalid,
                "source_integrity_status": "INTEGRITY_BLOCKED",
                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
            },
        )

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        validate_id(run_id, "run_id")
        try:
            self.get_run(run_id)
            return self._runs.list_run_events(run_id, runs_root=self.runs_root)
        except (FileNotFoundError, OrchestratorError) as e:
            raise APIError(ErrorCode.NOT_FOUND, "run not found") from e

    def list_user_actions(self, run_id: str) -> list[dict[str, Any]]:
        validate_id(run_id, "run_id")
        try:
            self.get_run(run_id)
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
        self.get_run(run_id)
        return self._runs.resume_run(run_id, runs_root=self.runs_root)

    def retry_node(self, run_id: str, node_id: str) -> dict[str, Any]:
        validate_id(run_id, "run_id")
        validate_id(node_id, "node_id")
        self.get_run(run_id)
        return self._runs.retry_node(run_id, node_id, runs_root=self.runs_root)

    # ---------- parameters (BRW-015) ----------
    # ---------- BRW-018R2 sampling-parameter submission (shared service) ----------
    # One submission = parameter set persist + pending-action resolution +
    # same-run resume, with explicit partial-success when resume fails after a
    # successful save. Submissions are journaled for idempotent replay.

    def submit_sampling_parameter(
        self,
        battery_id: str,
        experiment_id: str,
        payload: dict[str, Any],
        *,
        submission_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a user-supplied sampling rate, then recover the WAITING run.

        payload: {values: {name: {value, unit}}, source, verified?, run_id?,
        action_id?}. The value is stored in canonical Hz by the parameter
        registry's unit normalization (Hz/kHz/MHz/GHz accepted; no guessing).
        Idempotent: a replayed submission_id returns the journaled result
        without re-writing parameters or re-resuming the run.
        """
        self._require_experiment(battery_id, experiment_id)
        sid = submission_id or f"SUB::{uuid.uuid4().hex[:16]}"
        journal = self._submission_journal(battery_id, experiment_id)
        if sid in journal:
            prior = dict(journal[sid])
            if prior.get("payload_fingerprint") != self._submission_fingerprint(payload):
                raise APIError(
                    ErrorCode.CONFLICT,
                    "submission id reused with different payload",
                    {"submission_id": sid},
                )
            prior["submission_id"] = sid
            prior["replayed"] = True
            return prior

        values = payload.get("values") or {}
        source = str(payload.get("source") or "").strip()
        if not source:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "sampling-rate submission requires an explicit source (no guessing)",
            )
        if "ultrasound.sampling_rate_hz" not in values:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "submission must set ultrasound.sampling_rate_hz",
            )
        entry = values["ultrasound.sampling_rate_hz"]
        if not isinstance(entry, dict) or entry.get("value") is None:
            raise APIError(ErrorCode.VALIDATION_ERROR, "sampling rate value required")
        unit = str(entry.get("unit", "Hz"))
        # validate positivity and finiteness before persisting; unit
        # normalization to Hz is enforced by the parameter registry.
        try:
            numeric = float(entry["value"])
        except (TypeError, ValueError):
            numeric = 0.0
        if not numeric > 0 or not math.isfinite(numeric):
            raise APIError(
                ErrorCode.VALIDATION_ERROR, "sampling rate must be a positive finite number"
            )

        pending_run = payload.get("run_id") or self._latest_waiting_run(battery_id, experiment_id)
        if pending_run:
            run_record = self.get_run(str(pending_run))
            if (run_record.get("battery_id"), run_record.get("experiment_id")) != (
                battery_id,
                experiment_id,
            ):
                raise APIError(
                    ErrorCode.VALIDATION_ERROR,
                    "run identity does not match the sampling-parameter experiment",
                )

        ps_payload = {
            "values": values,
            "source": source,
            "verified": bool(payload.get("verified")),
        }
        save_error: str | None = None
        parameter_set_id: str | None = None
        try:
            ps = self.create_parameter_set(battery_id, experiment_id, ps_payload)
            parameter_set_id = ps["parameter_set_id"]
        except APIError as exc:
            save_error = f"{exc.error_code.value}: {exc.detail if hasattr(exc, 'detail') else exc}"

        run_id = payload.get("run_id")
        action_id = payload.get("action_id")
        resume_status = "NOT_ATTEMPTED"
        resume_error: str | None = None
        resolved_action = False
        run_state: str | None = None

        if parameter_set_id is not None:
            # resolve the pending action on the run when one is attached
            target_run = pending_run
            if target_run:
                try:
                    target_action = action_id or self._pending_fs_action(target_run)
                    if target_action:
                        self._runs.submit_user_action(
                            target_run,
                            target_action,
                            values={
                                "ultrasound.sampling_rate_hz": {
                                    "value": numeric,
                                    "unit": unit,
                                    "_source": source,
                                    "verification_status": (
                                        "VERIFIED"
                                        if bool(payload.get("verified"))
                                        else "UNVERIFIED"
                                    ),
                                }
                            },
                            runs_root=self.runs_root,
                        )
                        resolved_action = True
                    else:
                        self._runs.resume_run(target_run, runs_root=self.runs_root)
                    run = self._runs.get_run(target_run, runs_root=self.runs_root)
                    run_id = target_run
                    run_state = run.get("status")
                    resume_status = "RESUMED"
                except (OrchestratorError, ValueError, FileNotFoundError, OSError) as exc:
                    # partial-success boundary: PS persisted, resume leg failed
                    resume_status = "FAILED"
                    resume_error = f"{type(exc).__name__}: {exc}"

        result = {
            "submission_id": sid,
            "payload_fingerprint": self._submission_fingerprint(payload),
            "parameter_set_id": parameter_set_id,
            "save_status": "SAVED" if parameter_set_id else "FAILED",
            "save_error": save_error,
            "fs_value": numeric,
            "fs_unit": unit,
            "source": source,
            "verification_status": "VERIFIED" if bool(payload.get("verified")) else "UNVERIFIED",
            "run_id": run_id,
            "pending_action_resolved": resolved_action,
            "resume_status": resume_status,
            "resume_error": resume_error,
            "run_state": run_state,
        }
        if parameter_set_id is not None:
            self._journal_submission(battery_id, experiment_id, sid, result)
        return result

    def retry_submission_resume(
        self, battery_id: str, experiment_id: str, submission_id: str
    ) -> dict[str, Any]:
        """Retry ONLY the resume leg of a partially-successful submission.

        Never re-writes the parameter set (no duplicate PS creation).
        """
        journal = self._submission_journal(battery_id, experiment_id)
        prior = journal.get(submission_id)
        if prior is None:
            raise APIError(ErrorCode.NOT_FOUND, "submission not found")
        run_id = prior.get("run_id")
        if not run_id:
            raise APIError(ErrorCode.VALIDATION_ERROR, "submission has no attached run")
        run_record = self.get_run(str(run_id))
        if (run_record.get("battery_id"), run_record.get("experiment_id")) != (
            battery_id,
            experiment_id,
        ):
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "run identity does not match the sampling-parameter experiment",
            )
        try:
            target_action = self._pending_fs_action(run_id)
            if target_action:
                self._runs.submit_user_action(
                    run_id,
                    target_action,
                    values={
                        "ultrasound.sampling_rate_hz": {
                            "value": prior.get("fs_value"),
                            "unit": prior.get("fs_unit", "Hz"),
                            "_source": prior.get("source", "retry"),
                            "verification_status": prior.get("verification_status", "UNVERIFIED"),
                        }
                    },
                    runs_root=self.runs_root,
                )
            run = self._runs.resume_run(run_id, runs_root=self.runs_root)
            updated = dict(prior)
            updated.update(
                {
                    "resume_status": "RESUMED",
                    "resume_error": None,
                    "pending_action_resolved": True,
                    "run_state": run.get("status"),
                }
            )
            self._journal_submission(battery_id, experiment_id, submission_id, updated)
            return updated
        except Exception as exc:  # surfaced to Retry Resume UI
            updated = dict(prior)
            updated.update(
                {"resume_status": "FAILED", "resume_error": f"{type(exc).__name__}: {exc}"}
            )
            self._journal_submission(battery_id, experiment_id, submission_id, updated)
            raise APIError(
                ErrorCode.SCIENTIFIC_ACTION_REQUIRED,
                f"resume failed again: {exc}",
            ) from exc

    @staticmethod
    def _submission_fingerprint(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _submission_journal_path(self, battery_id: str, experiment_id: str) -> Path:
        return (
            self.processed_root
            / "parameter_submissions"
            / battery_id
            / experiment_id
            / "submissions.json"
        )

    def _submission_journal(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        p = self._submission_journal_path(battery_id, experiment_id)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _journal_submission(
        self, battery_id: str, experiment_id: str, sid: str, result: dict[str, Any]
    ) -> None:
        p = self._submission_journal_path(battery_id, experiment_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        journal = self._submission_journal(battery_id, experiment_id)
        journal[sid] = result
        p.write_text(json.dumps(journal, indent=2), encoding="utf-8")

    def _latest_waiting_run(self, battery_id: str, experiment_id: str) -> str | None:
        runs_dir = self.runs_root
        if not runs_dir.is_dir():
            return None
        best: tuple[str, str] | None = None
        for d in sorted(runs_dir.iterdir()):
            manifest = d / "run_manifest.json"
            if not manifest.is_file():
                continue
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            waiting_fs = (
                m.get("battery_id") == battery_id
                and m.get("experiment_id") == experiment_id
                and m.get("status") == "WAITING_FOR_USER"
                and any(
                    a.get("action_type") == "MISSING_SAMPLING_RATE"
                    for a in m.get("user_actions", [])
                )
            )
            if waiting_fs and (best is None or d.name > best[0]):
                best = (d.name, "RUN::" + d.name)
        return best[1] if best else None

    def _pending_fs_action(self, run_id: str) -> str | None:
        try:
            actions = self._runs.list_user_actions(run_id, runs_root=self.runs_root)
        except (FileNotFoundError, OrchestratorError):
            return None
        for a in actions:
            if a.get("action_type") == "MISSING_SAMPLING_RATE":
                return a["action_id"]
        return None

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
        battery_id = validate_id(str(payload["battery_id"]), "battery_id")
        experiment_id = validate_id(str(payload["experiment_id"]), "experiment_id")
        self._require_experiment(battery_id, experiment_id)
        self._assert_ultrasound_parser_provenance(battery_id, experiment_id)
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
            / battery_id
            / experiment_id
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
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
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
                        identity = manifest.relative_to(gates_root).parts
                        if len(identity) >= 3:
                            self._assert_ultrasound_parser_provenance(identity[0], identity[1])
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
                        identity = manifest.relative_to(gf_root).parts
                        if len(identity) >= 3:
                            self._assert_ultrasound_parser_provenance(identity[0], identity[1])
                        return {"gate_id": gate_id, **g}
            for gs_dir in sorted(gf_root.rglob("*")):
                if gs_dir.is_dir() and gs_dir.name == gate_id:
                    return {"gate_set_id": gate_id}
        raise APIError(ErrorCode.NOT_FOUND, "gate not found")

    def list_gates(self, battery_id: str, experiment_id: str) -> list[dict[str, Any]]:
        self._assert_ultrasound_parser_provenance(battery_id, experiment_id)
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
        battery_id = validate_id(str(payload["battery_id"]), "battery_id")
        experiment_id = validate_id(str(payload["experiment_id"]), "experiment_id")
        self._assert_parser_provenance(battery_id, experiment_id)
        try:
            spec = FeatureAnalysisSpec(
                analysis_mode=payload["analysis_mode"],
                target=payload["target"],
                candidate_features=list(payload["candidate_features"]),
                split_id=payload.get("split_id") or None,
                fold_index=payload.get("fold_index"),
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
        manifests = (
            [
                path
                for path in fa_root.rglob("analysis_manifest.json")
                if path.parent.name == analysis_id
            ]
            if fa_root.is_dir()
            else []
        )
        if not manifests:
            raise APIError(ErrorCode.NOT_FOUND, "feature analysis not found")
        if len(manifests) != 1:
            return {
                "analysis_id": analysis_id,
                "status": "INTEGRITY_BLOCKED",
                "availability": "BLOCKED",
                "freshness_status": "INTEGRITY_BLOCKED",
                "freshness_reasons": ["ANALYSIS_ID_AMBIGUOUS"],
            }

        manifest_path = manifests[0]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative = manifest_path.relative_to(fa_root)
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            manifest = None
            relative = ()
        relative_parts = relative.parts if isinstance(relative, Path) else ()
        if not isinstance(manifest, dict) or len(relative_parts) < 5:
            return {
                "analysis_id": analysis_id,
                "status": "INTEGRITY_BLOCKED",
                "availability": "BLOCKED",
                "freshness_status": "INTEGRITY_BLOCKED",
                "freshness_reasons": ["ANALYSIS_MANIFEST_INVALID"],
            }
        battery_id, experiment_id = relative_parts[:2]
        if (
            manifest.get("analysis_id") != analysis_id
            or manifest.get("battery_id", battery_id) != battery_id
            or manifest.get("experiment_id", experiment_id) != experiment_id
        ):
            return {
                "analysis_id": analysis_id,
                "status": "INTEGRITY_BLOCKED",
                "availability": "BLOCKED",
                "freshness_status": "INTEGRITY_BLOCKED",
                "freshness_reasons": ["ANALYSIS_IDENTITY_MISMATCH"],
            }

        self._assert_parser_provenance(battery_id, experiment_id)
        from battery_workbench.feature_analysis.output import (
            verify_analysis_input_checksums,
            verify_analysis_output_checksums,
        )

        output_status, output_reasons = verify_analysis_output_checksums(
            manifest_path.parent, manifest
        )
        input_status, input_reasons = verify_analysis_input_checksums(
            self.processed_root, manifest
        )
        reasons = output_reasons + input_reasons
        if output_status == "INTEGRITY_BLOCKED" or input_status == "INTEGRITY_BLOCKED":
            freshness_status = "INTEGRITY_BLOCKED"
        elif input_status == "STALE_SOURCE":
            freshness_status = "STALE_SOURCE"
        elif output_status == "LEGACY_UNVERIFIED" or input_status == "LEGACY_UNVERIFIED":
            freshness_status = "LEGACY"
        else:
            freshness_status = "CURRENT"

        analysis_mode = manifest.get("analysis_mode")
        if freshness_status == "CURRENT" and analysis_mode == "TRAIN_ONLY_ML_SAFE":
            dataset_id = manifest.get("dataset_id")
            split_id = manifest.get("split_id")
            dependencies = [(dataset_id, "DATASET"), (split_id, "SPLIT")]
            for dependency_id, dependency_type in dependencies:
                if not isinstance(dependency_id, str) or not dependency_id:
                    freshness_status = "INTEGRITY_BLOCKED"
                    reasons.append(f"ANALYSIS_{dependency_type}_IDENTITY_MISSING")
                    break
                dependency = self.get_artifact(dependency_id)
                fields = dependency.get("fields", {})
                if fields.get("battery_id") not in (None, battery_id) or fields.get(
                    "experiment_id"
                ) not in (None, experiment_id):
                    freshness_status = "INTEGRITY_BLOCKED"
                    reasons.append(f"ANALYSIS_{dependency_type}_SCOPE_MISMATCH")
                    break
                if dependency.get("availability") == "BLOCKED":
                    freshness_status = "INTEGRITY_BLOCKED"
                    reasons.extend(
                        fields.get("freshness_reasons", [])
                        or [f"ANALYSIS_{dependency_type}_INTEGRITY_BLOCKED"]
                    )
                    break
                if dependency.get("availability") != "AVAILABLE":
                    freshness_status = "STALE_SOURCE"
                    reasons.extend(
                        fields.get("freshness_reasons", [])
                        or [f"ANALYSIS_{dependency_type}_STALE"]
                    )
                    break

        if freshness_status == "INTEGRITY_BLOCKED":
            status, availability = "INTEGRITY_BLOCKED", "BLOCKED"
        elif freshness_status == "STALE_SOURCE":
            status, availability = "STALE_SOURCE", "STALE"
        elif freshness_status == "LEGACY":
            status, availability = "LEGACY_UNVERIFIED", "STALE"
        else:
            selected = (manifest.get("selection") or {}).get("selected_features") or []
            status, availability = ("AVAILABLE" if selected else "LIMITED"), "AVAILABLE"
        result = {
            "analysis_id": analysis_id,
            "status": status,
            "availability": availability,
            "freshness_status": freshness_status,
            "freshness_reasons": list(dict.fromkeys(reasons)),
        }
        if freshness_status == "CURRENT":
            selection = manifest.get("selection") or {}
            selection_status = _feature_selection_status(selection)
            result.update(
                {
                    "analysis_mode": analysis_mode,
                    "target": manifest.get("target"),
                    "split_id": manifest.get("split_id"),
                    "fold_index": manifest.get("fold_index"),
                    "dataset_id": manifest.get("dataset_id"),
                    "candidate_features": manifest.get("candidate_features", []),
                    "methods": manifest.get("methods", []),
                    "selected_features": selection.get("selected_features", []),
                    "selection_basis": selection.get("selection_basis"),
                    "selection_policy": selection.get("policy"),
                    "selection_policy_version": selection.get("policy_version"),
                    "selection_status": selection_status,
                }
            )
        return result

    def _temperature_target_status(self, battery_id: str, experiment_id: str) -> tuple[bool, str]:
        """Measure the channel, then keep the target blocked without verified evidence."""
        import pandas as pd

        events_path = (
            self.processed_root
            / "multimodal"
            / battery_id
            / experiment_id
            / "measurement_events.parquet"
        )
        if not events_path.is_file():
            return temperature_target_gate(valid_count=0, temp_range_c=None)
        from battery_workbench.api.integrity import assert_processed_artifact_integrity

        manifest_path = events_path.parent / "measurement_event_manifest.json"
        try:
            assert_processed_artifact_integrity(
                self.processed_root,
                manifest_path,
                battery_id=battery_id,
                experiment_id=experiment_id,
                required_outputs={"events", "candidates"},
                required_inputs={"aligned", "sync_candidates", "electrical_records"},
            )
        except APIError:
            return temperature_target_gate(valid_count=0, temp_range_c=None)
        try:
            frame = pd.read_parquet(events_path)
        except OSError:
            return temperature_target_gate(valid_count=0, temp_range_c=None)
        if "temperature_c" not in frame.columns:
            return temperature_target_gate(valid_count=0, temp_range_c=None)
        series = frame["temperature_c"].dropna()
        if series.empty:
            return temperature_target_gate(valid_count=0, temp_range_c=None)
        return temperature_target_gate(
            valid_count=int(series.size),
            temp_range_c=float(series.max() - series.min()),
            # No authenticated sensor-location/calibration evidence registry
            # exists yet; observation count/range alone must never enable y.
            evidence_verified=False,
        )

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
        # Only the Reference SOC dataset family is materialized in this
        # workflow; a non-SOC explicit spec must never be written under the
        # "SOC" family directory (mislabeled artifact risk).
        target_name = payload.get("target")
        if explicit_spec and target_name not in (
            None,
            "",
            "soc_reference_percent",
            "reference_soc_percent",
        ):
            if str(target_name) == "temperature_c":
                # A channel and >=2C range are necessary only; the target
                # stays blocked until sensor-location/calibration evidence
                # is verified through a trusted evidence workflow.
                allowed, temp_reason = self._temperature_target_status(battery_id, experiment_id)
                if not allowed:
                    raise APIError(
                        ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                        f"dataset target not ready: {target_name} — {temp_reason}",
                    )
                # Passed the gate: materialize under its own family, never
                # under "SOC" (mislabeled artifact risk).
                family = "TEMPERATURE"
            else:
                reason = {
                    "soh_capacity_reference_percent": "SOH 仅 2 个 cycle 级独立状态（NOT_READY），不做监督数据集构建",
                }.get(str(target_name), "当前流程仅物化 Reference SOC 数据集族")
                raise APIError(
                    ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                    f"dataset target not ready: {target_name} — {reason}",
                )
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
            dataset_root = self.processed_root / "datasets"
            manifests = [
                path
                for path in dataset_root.rglob("dataset_manifest.json")
                if path.parent.name == artifact_id
            ] if dataset_root.is_dir() else []
            if len(manifests) > 1:
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "DATASET",
                    "availability": "BLOCKED",
                    "status": "INTEGRITY_BLOCKED",
                    "row_count": None,
                    "preview": [],
                    "fields": {"freshness_reasons": ["DATASET_ID_AMBIGUOUS"]},
                }
            for manifest in manifests:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    from battery_workbench.datasets.freshness import dataset_freshness

                    freshness = dataset_freshness(
                        self.processed_root, manifest, data, raw_root=self.raw_root
                    )
                    if not isinstance(data, dict):
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "DATASET",
                            "availability": freshness["availability"],
                            "status": freshness["freshness_status"],
                            "row_count": None,
                            "preview": [],
                            "fields": freshness,
                        }
                    source_integrity_reasons = [
                        reason
                        for reason in freshness["freshness_reasons"]
                        if reason.startswith(("SOURCE_PROVENANCE_INVALID:", "SOURCE_RAW_MISMATCH:"))
                    ]
                    if source_integrity_reasons:
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "DATASET",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "source_integrity_status": "INTEGRITY_BLOCKED",
                                "freshness_reasons": source_integrity_reasons,
                            },
                        }
                    status = (
                        data.get("dataset_status", "")
                        if freshness["freshness_status"] == "FRESH"
                        else "STALE_SOURCE"
                    )
                    body = {
                        "artifact_id": artifact_id,
                        "artifact_type": "DATASET",
                        "availability": freshness["availability"],
                        "status": status,
                        "row_count": data.get("joined_rows"),
                        "preview": [],
                    }
                    sanitized = {
                        k: v
                        for k, v in data.items()
                        if k not in {"output_path", "feature_set_path", "label_set_path"}
                    }
                    sanitized["declared_dataset_status"] = data.get("dataset_status", "")
                    sanitized.update(freshness)
                    body["fields"] = sanitized
                    return body
        if prefix == "SPLIT":
            split_root = self.processed_root / "splits"
            manifests = [
                path
                for path in split_root.rglob("split_manifest.json")
                if path.parent.name == artifact_id
            ] if split_root.is_dir() else []
            if len(manifests) > 1:
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "SPLIT",
                    "availability": "BLOCKED",
                    "status": "INTEGRITY_BLOCKED",
                    "row_count": None,
                    "preview": [],
                    "fields": {"freshness_reasons": ["SPLIT_ID_AMBIGUOUS"]},
                }
            for manifest in manifests:
                    try:
                        data = json.loads(manifest.read_text(encoding="utf-8"))
                        if not isinstance(data, dict):
                            raise TypeError("split manifest root must be an object")
                        split_relative = manifest.relative_to(self.processed_root / "splits")
                        split_identity = split_relative.parts[:2]
                    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {"freshness_reasons": ["SPLIT_MANIFEST_INVALID"]},
                        }

                    dataset_id = data.get("dataset_id")
                    battery_id, experiment_id = split_identity
                    if (
                        len(split_relative.parts) < 3
                        or data.get("split_id") != artifact_id
                        or not isinstance(dataset_id, str)
                        or data.get("battery_id", battery_id) != battery_id
                        or data.get("experiment_id", experiment_id) != experiment_id
                    ):
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {"freshness_reasons": ["SPLIT_IDENTITY_MISMATCH"]},
                        }

                    dataset_root = self.processed_root / "datasets" / battery_id / experiment_id
                    dataset_manifests = [
                        path
                        for path in dataset_root.rglob("dataset_manifest.json")
                        if path.parent.name == dataset_id
                    ] if dataset_root.is_dir() else []
                    if len(dataset_manifests) != 1:
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "STALE",
                            "status": "STALE_SOURCE",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "dataset_id": dataset_id,
                                "freshness_reasons": ["SPLIT_DATASET_MISSING_OR_AMBIGUOUS"],
                            },
                        }

                    from battery_workbench.datasets.freshness import dataset_freshness

                    dataset_manifest = dataset_manifests[0]
                    try:
                        dataset_data = json.loads(dataset_manifest.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        dataset_data = None
                    freshness = dataset_freshness(
                        self.processed_root,
                        dataset_manifest,
                        dataset_data,
                        raw_root=self.raw_root,
                    )
                    integrity_reasons = [
                        reason
                        for reason in freshness["freshness_reasons"]
                        if reason.startswith(("SOURCE_PROVENANCE_INVALID:", "SOURCE_RAW_MISMATCH:"))
                    ]
                    if integrity_reasons:
                        invalid_modalities = sorted(
                            {
                                reason.split(":", maxsplit=1)[1].lower()
                                for reason in integrity_reasons
                                if reason.startswith(
                                    ("SOURCE_PROVENANCE_INVALID:", "SOURCE_RAW_MISMATCH:")
                                )
                            }
                        )
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "source_integrity_status": "INTEGRITY_BLOCKED",
                                "dataset_id": dataset_id,
                                "freshness_reasons": integrity_reasons,
                                "invalid_modalities": invalid_modalities,
                                "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                            },
                        }
                    if freshness["freshness_status"] != "FRESH":
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "STALE",
                            "status": "STALE_SOURCE",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "dataset_id": dataset_id,
                                "freshness_status": freshness["freshness_status"],
                                "freshness_reasons": freshness["freshness_reasons"],
                                "recovery_action": "BUILD_DATASET",
                            },
                        }

                    if data.get("readiness_status") == "SPEC_PENDING_RUN":
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "NOT_AVAILABLE_CURRENT_ENVIRONMENT",
                            "status": "SPEC_PENDING_RUN",
                            "row_count": None,
                            "preview": [],
                            "fields": {"dataset_id": dataset_id},
                        }

                    expected_outputs = data.get("output_checksums")
                    required_outputs = {
                        "split_assignments": "split_assignments.parquet",
                        "leakage_audit": "leakage_audit.json",
                        "evaluation_readiness": "evaluation_readiness.json",
                    }
                    checksum_reasons: list[str] = []
                    if not isinstance(expected_outputs, dict) or set(expected_outputs) != set(
                        required_outputs
                    ):
                        checksum_reasons.append("SPLIT_OUTPUT_CHECKSUMS_MISSING_OR_INVALID")
                    else:
                        split_root = manifest.parent.resolve()
                        for output_name, filename in required_outputs.items():
                            output_path = manifest.parent / filename
                            expected_checksum = expected_outputs.get(output_name)
                            try:
                                resolved_output = output_path.resolve(strict=True)
                                resolved_output.relative_to(split_root)
                            except (OSError, RuntimeError, ValueError):
                                checksum_reasons.append(f"SPLIT_OUTPUT_MISSING_OR_OUTSIDE:{output_name}")
                                continue
                            if not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
                                checksum_reasons.append(f"SPLIT_OUTPUT_CHECKSUM_INVALID:{output_name}")
                                continue
                            digest = hashlib.sha256()
                            try:
                                with resolved_output.open("rb") as stream:
                                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                        digest.update(chunk)
                            except OSError:
                                checksum_reasons.append(
                                    f"SPLIT_OUTPUT_UNREADABLE:{output_name}"
                                )
                                continue
                            if digest.hexdigest().lower() != expected_checksum.lower():
                                checksum_reasons.append(f"SPLIT_OUTPUT_CHECKSUM_MISMATCH:{output_name}")
                    if checksum_reasons:
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "dataset_id": dataset_id,
                                "freshness_reasons": checksum_reasons,
                            },
                        }
                    from battery_workbench.splits.integrity import (
                        split_dataset_source_reasons,
                    )

                    source_reasons = split_dataset_source_reasons(
                        self.processed_root,
                        data,
                        dataset_path=dataset_manifest.parent / "dataset.parquet",
                        dataset_manifest_path=dataset_manifest,
                    )
                    if source_reasons:
                        changed = any(
                            reason.startswith("SPLIT_SOURCE_DATASET_CHANGED:")
                            for reason in source_reasons
                        )
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "STALE" if changed else "BLOCKED",
                            "status": "STALE_SOURCE" if changed else "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "dataset_id": dataset_id,
                                "freshness_status": "STALE" if changed else "INTEGRITY_BLOCKED",
                                "freshness_reasons": source_reasons,
                                "recovery_action": "REBUILD_SPLIT" if changed else "REBUILD_DATASET_AND_SPLIT",
                            },
                        }
                    from battery_workbench.splits.integrity import split_assignment_reasons

                    assignment_reasons = split_assignment_reasons(
                        self.processed_root,
                        data,
                        assignments_path=manifest.parent / "split_assignments.parquet",
                        dataset_path=dataset_manifest.parent / "dataset.parquet",
                    )
                    if assignment_reasons:
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "SPLIT",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "dataset_id": dataset_id,
                                "freshness_status": "INTEGRITY_BLOCKED",
                                "freshness_reasons": assignment_reasons,
                                "recovery_action": "REBUILD_SPLIT",
                            },
                        }
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "SPLIT",
                        "availability": "AVAILABLE",
                        "status": data.get("readiness_status", ""),
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "dataset_id": dataset_id,
                            "freshness_status": "FRESH",
                            "output_checksums_verified": True,
                        },
                    }
        if prefix == "COHORT":
            cohort_root = self.processed_root / "cohorts"
            manifests = [
                path
                for path in cohort_root.rglob("cohort_manifest.json")
                if path.parent.name == artifact_id
            ] if cohort_root.is_dir() else []
            if len(manifests) > 1:
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "COHORT_DATASET",
                    "availability": "BLOCKED",
                    "status": "INTEGRITY_BLOCKED",
                    "row_count": None,
                    "preview": [],
                    "fields": {"freshness_reasons": ["COHORT_ID_AMBIGUOUS"]},
                }
            for manifest_path in manifests:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    from battery_workbench.datasets.cohort import (
                        cohort_source_integrity_reasons,
                        cohort_sources_current,
                    )

                    integrity_reasons = cohort_source_integrity_reasons(
                        self.processed_root, data, raw_root=self.raw_root
                    )
                    if integrity_reasons:
                        return {
                            "artifact_id": artifact_id,
                            "artifact_type": "COHORT_DATASET",
                            "availability": "BLOCKED",
                            "status": "INTEGRITY_BLOCKED",
                            "row_count": None,
                            "preview": [],
                            "fields": {
                                "source_integrity_status": "INTEGRITY_BLOCKED",
                                "freshness_reasons": integrity_reasons,
                            },
                        }
                    is_current = cohort_sources_current(
                        self.processed_root, data, raw_root=self.raw_root
                    )
                    data["status"] = "READY_FOR_BATTERY_SPLIT" if is_current else "STALE_SOURCE"
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "COHORT_DATASET",
                        "availability": "AVAILABLE" if is_current else "STALE",
                        "status": data.get("status", ""),
                        "row_count": data.get("row_count"),
                        "preview": [],
                        "fields": {
                            key: value for key, value in data.items() if key != "output_path"
                        },
                    }
        if prefix == "MODEL":
            models_root = self.processed_root / "models"
            matches = [
                path
                for path in models_root.rglob("model_manifest.json")
                if path.parent.name == artifact_id
            ] if models_root.is_dir() else []
            if len(matches) == 1:
                manifest_path = matches[0]
                try:
                    model = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "model manifest is unreadable",
                        {"artifact_id": artifact_id},
                    ) from exc
                identity = manifest_path.parent.relative_to(models_root).parts
                if (
                    not isinstance(model, dict)
                    or len(identity) != 5
                    or identity[4] != artifact_id
                    or model.get("model_id") != artifact_id
                    or model.get("dataset_id") != identity[2]
                    or model.get("split_id") != identity[3]
                ):
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "model identity does not match its manifest path",
                        {"artifact_id": artifact_id},
                    )
                battery_id, experiment_id = identity[:2]
                from battery_workbench.provenance.parser_manifest import (
                    invalid_parser_manifest_modalities,
                )

                invalid_modalities = invalid_parser_manifest_modalities(
                    self.processed_root, battery_id, experiment_id
                )
                if invalid_modalities:
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "BLOCKED",
                        "status": "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "source_integrity_status": "INTEGRITY_BLOCKED",
                            "invalid_modalities": invalid_modalities,
                            "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                        },
                    }
                dataset_manifests = list(
                    (
                        self.processed_root
                        / "datasets"
                        / battery_id
                        / experiment_id
                    ).rglob(f"{identity[2]}/dataset_manifest.json")
                )
                dataset_manifest = dataset_manifests[0] if len(dataset_manifests) == 1 else None
                split_manifest = (
                    self.processed_root
                    / "splits"
                    / battery_id
                    / experiment_id
                    / identity[2]
                    / identity[3]
                    / "split_manifest.json"
                )
                if dataset_manifest is None or not dataset_manifest.is_file() or not split_manifest.is_file():
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "STALE",
                        "status": "STALE_LINEAGE",
                        "row_count": None,
                        "preview": [],
                        "fields": {"freshness_reasons": ["MODEL_DATASET_OR_SPLIT_MISSING"]},
                    }
                try:
                    dataset = json.loads(dataset_manifest.read_text(encoding="utf-8"))
                    split = json.loads(split_manifest.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "model lineage manifest is unreadable",
                        {"artifact_id": artifact_id},
                    ) from exc
                from battery_workbench.datasets.freshness import dataset_freshness

                freshness = dataset_freshness(
                    self.processed_root,
                    dataset_manifest,
                    dataset,
                    raw_root=self.raw_root,
                )
                raw_source_reasons = [
                    reason
                    for reason in freshness["freshness_reasons"]
                    if reason.startswith("SOURCE_RAW_MISMATCH:")
                ]
                if raw_source_reasons:
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "BLOCKED",
                        "status": "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "integrity_reasons": ["PARSER_RAW_SOURCE_MISMATCH"],
                            "invalid_modalities": [
                                reason.rsplit(":", 1)[-1].lower()
                                for reason in raw_source_reasons
                            ],
                            "recovery_action": "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE",
                        },
                    }
                lineage_matches = (
                    isinstance(dataset, dict)
                    and isinstance(split, dict)
                    and dataset.get("dataset_id") == identity[2]
                    and split.get("split_id") == identity[3]
                    and split.get("dataset_id") == identity[2]
                    and split.get("battery_id") == battery_id
                    and split.get("experiment_id") == experiment_id
                )
                if not lineage_matches or freshness["freshness_status"] != "FRESH":
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "STALE",
                        "status": "STALE_SOURCE",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "freshness_reasons": (
                                freshness["freshness_reasons"]
                                if freshness["freshness_status"] != "FRESH"
                                else ["MODEL_DATASET_SPLIT_IDENTITY_MISMATCH"]
                            ),
                        },
                    }
                split_dir = split_manifest.parent
                split_checksums = split.get("output_checksums")
                split_output_paths = {
                    "split_assignments": split_dir / "split_assignments.parquet",
                    "leakage_audit": split_dir / "leakage_audit.json",
                    "evaluation_readiness": split_dir / "evaluation_readiness.json",
                }
                invalid_split_outputs = []
                for output_name, output_path in split_output_paths.items():
                    expected_checksum = (
                        split_checksums.get(output_name)
                        if isinstance(split_checksums, dict)
                        else None
                    )
                    try:
                        if not output_path.is_file() or not isinstance(expected_checksum, str):
                            invalid_split_outputs.append(output_name)
                            continue
                        digest = hashlib.sha256()
                        with output_path.open("rb") as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(chunk)
                        if digest.hexdigest() != expected_checksum:
                            invalid_split_outputs.append(output_name)
                    except OSError:
                        invalid_split_outputs.append(output_name)
                if invalid_split_outputs:
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "BLOCKED",
                        "status": "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "integrity_reasons": ["SPLIT_OUTPUT_CHECKSUM_MISMATCH"],
                            "invalid_outputs": invalid_split_outputs,
                        },
                    }
                from battery_workbench.splits.integrity import (
                    split_assignment_reasons,
                    split_dataset_source_reasons,
                )

                split_source_reasons = split_dataset_source_reasons(
                    self.processed_root,
                    split,
                    dataset_path=dataset_manifest.parent / "dataset.parquet",
                    dataset_manifest_path=dataset_manifest,
                )
                if split_source_reasons:
                    source_changed = any(
                        reason.startswith("SPLIT_SOURCE_DATASET_CHANGED:")
                        for reason in split_source_reasons
                    )
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "STALE" if source_changed else "BLOCKED",
                        "status": "STALE_SOURCE" if source_changed else "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "freshness_reasons": split_source_reasons,
                            "recovery_action": "REBUILD_SPLIT_AND_MODELS"
                            if source_changed
                            else "REBUILD_DATASET_AND_SPLIT",
                        },
                    }
                assignment_reasons = split_assignment_reasons(
                    self.processed_root,
                    split,
                    assignments_path=split_dir / "split_assignments.parquet",
                    dataset_path=dataset_manifest.parent / "dataset.parquet",
                )
                if assignment_reasons:
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "BLOCKED",
                        "status": "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "freshness_reasons": assignment_reasons,
                            "recovery_action": "REBUILD_SPLIT_AND_MODELS",
                        },
                    }
                checksums = model.get("output_checksums")
                output_paths = {
                    "model": manifest_path.parent / "model.joblib",
                    "held_out_predictions": manifest_path.parent / "held_out_predictions.parquet",
                }
                if not isinstance(checksums, dict):
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "STALE",
                        "status": "STALE_OUTPUT_PROVENANCE",
                        "row_count": None,
                        "preview": [],
                        "fields": {"freshness_reasons": ["MODEL_OUTPUT_CHECKSUMS_MISSING"]},
                    }
                invalid_outputs = []
                for output_name, output_path in output_paths.items():
                    try:
                        expected_checksum = checksums.get(output_name)
                        if not output_path.is_file() or not isinstance(expected_checksum, str):
                            invalid_outputs.append(output_name)
                            continue
                        digest = hashlib.sha256()
                        with output_path.open("rb") as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(chunk)
                        if digest.hexdigest() != expected_checksum:
                            invalid_outputs.append(output_name)
                    except OSError:
                        invalid_outputs.append(output_name)
                if invalid_outputs:
                    return {
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL",
                        "availability": "BLOCKED",
                        "status": "INTEGRITY_BLOCKED",
                        "row_count": None,
                        "preview": [],
                        "fields": {
                            "integrity_reasons": ["MODEL_OUTPUT_CHECKSUM_MISMATCH"],
                            "invalid_outputs": invalid_outputs,
                        },
                    }
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "MODEL",
                    "availability": "AVAILABLE",
                    "status": "CURRENT",
                    "row_count": None,
                    "preview": [],
                    "fields": {
                        "strategy": model.get("strategy"),
                        "dataset_id": identity[2],
                        "split_id": identity[3],
                        "fold_index": model.get("fold_index"),
                        "evaluation_readiness": (model.get("scientific_claims") or {}).get(
                            "readiness"
                        ),
                        "fold_coverage": (model.get("scientific_claims") or {}).get(
                            "fold_coverage"
                        ),
                        "selected_feature_count": len(model.get("selected_features") or []),
                        "policy_version": model.get("policy_version"),
                    },
                }
            if len(matches) > 1:
                return {
                    "artifact_id": artifact_id,
                    "artifact_type": "MODEL",
                    "availability": "BLOCKED",
                    "status": "INTEGRITY_BLOCKED",
                    "row_count": None,
                    "preview": [],
                    "fields": {"freshness_reasons": ["MODEL_ID_AMBIGUOUS"]},
                }
        if prefix in ("GATE", "GATESET"):
            return self.get_gate(artifact_id)
        # Do not claim that an unhandled artifact type is available merely
        # because its identifier has a valid shape. Only artifact families
        # resolved above have their manifest/source state checked here.
        return {
            "artifact_id": artifact_id,
            "artifact_type": prefix,
            "availability": "NOT_AVAILABLE_CURRENT_ENVIRONMENT",
            "status": "UNRESOLVED",
            "row_count": None,
            "preview": [],
            "fields": {
                "reason": "artifact type is not resolved by the metadata API",
            },
        }

    def create_cohort_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Materialize a new immutable cohort version from manifest identities."""
        from pydantic import ValidationError

        from battery_workbench.api.future_contracts import CohortDatasetRequest
        from battery_workbench.datasets.cohort import (
            CohortMaterializationError,
            materialize_cohort_dataset,
        )

        try:
            request = CohortDatasetRequest.model_validate(payload)
            return materialize_cohort_dataset(
                request=request,
                processed_root=self.processed_root,
                raw_root=self.raw_root,
            )
        except ValidationError as exc:
            raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cohort dataset request") from exc
        except CohortMaterializationError as exc:
            raise APIError(
                ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                "source datasets cannot be harmonized into an eligible cohort",
                {"reason": str(exc)},
            ) from exc

    def list_datasets(self) -> list[dict[str, Any]]:
        """List dataset identities and definition metadata without filesystem paths."""
        from battery_workbench.datasets.cohort import list_dataset_catalogue

        return list_dataset_catalogue(self.processed_root, raw_root=self.raw_root)

    def list_cohort_datasets(self) -> list[dict[str, Any]]:
        """List immutable cohort manifests without exposing filesystem paths."""
        from battery_workbench.datasets.cohort import (
            cohort_source_integrity_reasons,
            cohort_sources_current,
        )

        root = self.processed_root / "cohorts"
        if not root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.rglob("cohort_manifest.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                integrity_reasons = cohort_source_integrity_reasons(
                    self.processed_root, data, raw_root=self.raw_root
                )
                is_current = cohort_sources_current(
                    self.processed_root, data, raw_root=self.raw_root
                )
                data.pop("output_path", None)
                if integrity_reasons:
                    data["status"] = "INTEGRITY_BLOCKED"
                    data["row_count"] = None
                    data["source_integrity_status"] = "INTEGRITY_BLOCKED"
                    data["freshness_reasons"] = integrity_reasons
                else:
                    data["status"] = "READY_FOR_BATTERY_SPLIT" if is_current else "STALE_SOURCE"
                items.append(data)
            except (OSError, json.JSONDecodeError):
                continue
        return items

    def run_cohort_lobo(self, cohort_dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run fixed baselines on a verified cohort artifact and persist evidence."""
        import pandas as pd

        from battery_workbench.datasets.cohort import _sha256, cohort_sources_current
        from battery_workbench.modeling.cohort_lobo import evaluate_cohort_lobo

        manifests = [
            path
            for path in (self.processed_root / "cohorts").rglob("cohort_manifest.json")
            if path.parent.name == cohort_dataset_id
        ]
        if len(manifests) != 1:
            raise APIError(ErrorCode.NOT_FOUND, "cohort dataset not found")
        manifest_path = manifests[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not cohort_sources_current(
            self.processed_root, manifest, raw_root=self.raw_root
        ):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "cohort sources changed after harmonization; rebuild a new cohort version",
            )
        output_rel = Path(manifest.get("output_path", ""))
        if output_rel.is_absolute() or ".." in output_rel.parts:
            raise APIError(ErrorCode.INTEGRITY_ERROR, "cohort output path is invalid")
        parquet_path = (self.processed_root / output_rel).resolve()
        if self.processed_root.resolve() not in parquet_path.parents or not parquet_path.is_file():
            raise APIError(ErrorCode.ARTIFACT_NOT_AVAILABLE, "cohort Parquet is unavailable")
        if _sha256(parquet_path) != manifest.get("output_checksum"):
            raise APIError(ErrorCode.INTEGRITY_ERROR, "cohort Parquet checksum mismatch")
        from pydantic import ValidationError

        from battery_workbench.api.future_contracts import CohortLOBORequest

        try:
            evaluation_request = CohortLOBORequest.model_validate(payload)
        except ValidationError as exc:
            raise APIError(ErrorCode.VALIDATION_ERROR, "invalid cohort LOBO request") from exc
        frame = pd.read_parquet(parquet_path)
        try:
            result = evaluate_cohort_lobo(
                frame,
                dataset_id=cohort_dataset_id,
                features=list(manifest.get("predictor_columns", [])),
                target=str(manifest.get("target_column", "")),
                strategies=evaluation_request.strategies,
                random_state=evaluation_request.random_state,
                cohort_id=str(manifest.get("cohort_id", "")),
            )
        except (ValueError, KeyError) as exc:
            raise APIError(
                ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                "cohort cannot support the requested LOBO evaluation",
                {"reason": str(exc)},
            ) from exc
        # Change the cache identity when entity identity semantics change. An
        # older evaluation must not be reused with stronger independence claims.
        result["evaluation_id"] = (
            "LOBO::"
            + hashlib.sha256(
                f"{result['evaluation_id']}|declared-group-response-semantics-v2".encode()
            ).hexdigest()[:24]
        )
        declared_group_count = int(result.pop("battery_count", 0))
        result["battery_count"] = None
        result["declared_group_count"] = declared_group_count
        result["evaluation_scope"] = "DECLARED_GROUP_LOBO_TECHNICAL_EVALUATION"
        result["split_unit"] = "DECLARED_BATTERY_ID"
        result["group_identity_status"] = "NOT_ASSESSED"
        for strategy_metrics in result["macro_by_strategy"].values():
            strategy_metrics["declared_group_count"] = strategy_metrics.pop("battery_count")
        coverage = result["held_out_prediction_coverage"]
        coverage["independent_unit"] = "DECLARED_BATTERY_ID"
        coverage["declared_group_count"] = declared_group_count
        coverage["expected_declared_group_count"] = coverage.pop("expected_battery_count")
        coverage["observed_declared_group_count_per_strategy"] = coverage.pop(
            "observed_battery_count_per_strategy"
        )
        result["declared_group_results"] = [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"battery_id", "held_out_battery_id", "train_battery_ids"}
                },
                "declared_group_id": row["battery_id"],
                "held_out_declared_group_id": row["held_out_battery_id"],
                "train_declared_group_ids": row["train_battery_ids"],
            }
            for row in result.pop("battery_results")
        ]
        result["uncertainty_assessment"] = {
            "independent_unit": "DECLARED_BATTERY_ID",
            "independent_group_count": None,
            "declared_group_count": declared_group_count,
            "group_identity_status": "NOT_ASSESSED",
            "confidence_interval": {
                "status": "NOT_ESTIMATED",
                "reason": "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN",
                "resampling_unit": "DECLARED_BATTERY_ID",
            },
        }
        evaluation_id = result["evaluation_id"]
        evaluation_dir = manifest_path.parent / "evaluations" / evaluation_id
        evaluation_dir.mkdir(parents=True, exist_ok=True)
        evaluation_manifest_path = evaluation_dir / "evaluation_manifest.json"
        if evaluation_manifest_path.is_file():
            cached = json.loads(evaluation_manifest_path.read_text(encoding="utf-8"))
            if not _cohort_evaluation_artifacts_current(self.processed_root, cached):
                raise APIError(
                    ErrorCode.INTEGRITY_ERROR,
                    "stored cohort evaluation artifacts are missing or failed checksum validation",
                )
            return cached
        predictions = pd.DataFrame(result.pop("predictions"))
        assignments = pd.DataFrame(result.pop("split_assignments"))
        predictions_path = evaluation_dir / "held_out_predictions.parquet"
        assignments_path = evaluation_dir / "split_assignments.parquet"
        predictions.to_parquet(predictions_path, index=False)
        assignments.to_parquet(assignments_path, index=False)
        result["provenance"] = {
            "cohort_id": manifest["cohort_id"],
            "cohort_dataset_id": cohort_dataset_id,
            "source_datasets": manifest["source_datasets"],
            "harmonization_policy_id": manifest["harmonization_policy_id"],
            "harmonization_method_version": manifest["harmonization_method_version"],
            "cohort_manifest_checksum": _sha256(manifest_path),
            "cohort_dataset_checksum": manifest["output_checksum"],
        }
        result["identity_verification_status"] = manifest.get(
            "identity_verification_status", "NOT_ASSESSED"
        )
        result["scientific_generalization_eligible"] = False
        result["limitations"] = list(result.get("limitations", [])) + [
            "Battery identities are operator-declared and have not been independently reviewed",
            "LOBO group separation is a technical evaluation, not evidence of distinct physical batteries",
        ]
        result["artifacts"] = {
            "held_out_predictions": str(predictions_path.relative_to(self.processed_root)),
            "split_assignments": str(assignments_path.relative_to(self.processed_root)),
        }
        result["artifact_checksums"] = {
            "held_out_predictions": _sha256(predictions_path),
            "split_assignments": _sha256(assignments_path),
        }
        report_json_path = evaluation_dir / "cohort_evaluation_report.json"
        report_html_path = evaluation_dir / "cohort_evaluation_report.html"
        report_payload = {key: value for key, value in result.items()}
        report_json_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        import html

        report_html_path.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><title>Cohort LOBO Report</title></head>"
            "<body><h1>Cohort LOBO Limited Evaluation</h1><pre>"
            + html.escape(json.dumps(report_payload, ensure_ascii=False, indent=2))
            + "</pre></body></html>\n",
            encoding="utf-8",
        )
        result["artifacts"].update(
            {
                "cohort_report_json": str(report_json_path.relative_to(self.processed_root)),
                "cohort_report_html": str(report_html_path.relative_to(self.processed_root)),
            }
        )
        result["artifact_checksums"].update(
            {
                "cohort_report_json": _sha256(report_json_path),
                "cohort_report_html": _sha256(report_html_path),
            }
        )
        evaluation_manifest_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result

    def get_cohort_lobo_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        root = self.processed_root / "cohorts"
        for path in sorted(root.rglob("evaluation_manifest.json")) if root.is_dir() else []:
            if path.parent.name == evaluation_id:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                cohort_id = (manifest.get("provenance") or {}).get("cohort_dataset_id")
                cohort_manifests = [
                    candidate
                    for candidate in root.rglob("cohort_manifest.json")
                    if candidate.parent.name == cohort_id
                ]
                if len(cohort_manifests) != 1:
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "cohort evaluation source identity is unavailable",
                    )
                cohort = json.loads(cohort_manifests[0].read_text(encoding="utf-8"))
                from battery_workbench.datasets.cohort import cohort_source_integrity_reasons

                integrity_reasons = cohort_source_integrity_reasons(
                    self.processed_root, cohort, raw_root=self.raw_root
                )
                if integrity_reasons:
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "cohort evaluation source integrity is invalid",
                        {
                            "source_integrity_status": "INTEGRITY_BLOCKED",
                            "freshness_reasons": integrity_reasons,
                            "recovery_action": "REBUILD_COHORT_AFTER_SOURCE_REPAIR",
                        },
                    )
                if not _cohort_evaluation_artifacts_current(self.processed_root, manifest):
                    raise APIError(
                        ErrorCode.INTEGRITY_ERROR,
                        "cohort evaluation artifacts are missing or failed checksum validation",
                    )
                return manifest
        raise APIError(ErrorCode.NOT_FOUND, "cohort LOBO evaluation not found")

    # ---------- splits (deterministic, reuse-only) ----------
    def _require_fresh_dataset(
        self, dataset_id: str, battery_id: str, experiment_id: str
    ) -> dict[str, Any]:
        manifests = [
            path
            for path in (self.processed_root / "datasets").rglob("dataset_manifest.json")
            if path.parent.name == dataset_id
        ]
        if len(manifests) != 1:
            raise APIError(ErrorCode.NOT_FOUND, "dataset not found")
        manifest_path = manifests[0]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise APIError(ErrorCode.INTEGRITY_ERROR, "dataset manifest is unreadable") from exc
        if not isinstance(manifest, dict):
            raise APIError(ErrorCode.INTEGRITY_ERROR, "dataset manifest is invalid")
        if (
            manifest.get("dataset_id") != dataset_id
            or manifest.get("battery_id") != battery_id
            or manifest.get("experiment_id") != experiment_id
        ):
            raise APIError(ErrorCode.INTEGRITY_ERROR, "dataset identity does not match request")
        from battery_workbench.datasets.freshness import dataset_freshness

        freshness = dataset_freshness(
            self.processed_root, manifest_path, manifest, raw_root=self.raw_root
        )
        if freshness["freshness_status"] != "FRESH":
            raise APIError(
                ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                "dataset sources changed or cannot be verified; rebuild the dataset before modeling",
                freshness,
            )
        if manifest.get("dataset_status") not in {"READY_FOR_SPLIT", "READY_WITH_LIMITATIONS"}:
            raise APIError(
                ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
                "dataset is not ready for modeling",
                {"dataset_status": manifest.get("dataset_status")},
            )
        return manifest

    def create_split(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = payload.get("dataset_id", "")
        validate_id(dataset_id, "dataset_id")
        battery_id = payload.get("battery_id", "CELL_001")
        experiment_id = payload.get("experiment_id", "EXP_001")
        self._require_fresh_dataset(dataset_id, battery_id, experiment_id)
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
        self._require_fresh_dataset(
            payload["dataset_id"], payload["battery_id"], payload["experiment_id"]
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
        self._assert_parser_provenance(battery_id, experiment_id)
        from battery_workbench.reporting.schemas import ReportSpec

        spec = ReportSpec(
            target=target,
            battery_id=battery_id,
            experiment_id=experiment_id,
            source_artifact_ids=list(payload.get("source_artifact_ids") or []),
            sections=list(payload.get("sections") or []),
        )
        report_file = (
            self.processed_root
            / "artifacts"
            / battery_id
            / experiment_id
            / "reports"
            / spec.report_id
            / "scientific_report.json"
        )
        reused = report_file.is_file()
        report = self._runs.generate_report(
            battery_id=battery_id,
            experiment_id=experiment_id,
            target=target,
            source_artifact_ids=spec.source_artifact_ids,
            sections=spec.sections,
        )
        report["reuse_status"] = "REUSED" if reused else "CREATED"
        report["limitations"] = list(report.get("limitations_summary") or [])
        context = self._report_workflow_context(battery_id, experiment_id)
        return self._annotate_report_freshness(
            report,
            report.get("report_id"),
            context,
            report_path=(
                self.processed_root
                / "artifacts"
                / battery_id
                / experiment_id
                / "reports"
                / str(report.get("report_id"))
                / "scientific_report.json"
            ),
            battery_id=battery_id,
            experiment_id=experiment_id,
        )

    def list_reports(
        self, battery_id: str, experiment_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        self._require_experiment(battery_id, experiment_id)
        reports_root = self.processed_root / "artifacts" / battery_id / experiment_id / "reports"
        entries: list[tuple[Path, dict[str, Any]]] = []
        if reports_root.is_dir():
            for report_file in sorted(reports_root.rglob("scientific_report.json")):
                try:
                    data = json.loads(report_file.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    data = {"report_id": report_file.parent.name}
                if not isinstance(data, dict):
                    data = {"report_id": report_file.parent.name}
                entries.append((report_file, data))
        if not entries:
            return []
        latest_report_id = (
            max(entries, key=lambda entry: entry[0].stat().st_mtime)[1].get("report_id")
            if entries
            else None
        )
        context = self._report_workflow_context(battery_id, experiment_id)
        items = [
            self._annotate_report_freshness(
                data,
                latest_report_id,
                context,
                report_path=path,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
            for path, data in entries
        ]
        items.sort(key=lambda r: r.get("report_id", ""))
        if cursor:
            items = [r for r in items if r.get("report_id", "") > cursor]
        return items[:limit]

    def get_report(self, report_id: str) -> dict[str, Any]:
        validate_id(report_id, "report_id")
        reports_root = self.processed_root / "artifacts"
        if reports_root.is_dir():
            matches = []
            for candidate in reports_root.rglob("scientific_report.json"):
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    data = {"report_id": candidate.parent.name}
                if not isinstance(data, dict):
                    data = {"report_id": candidate.parent.name}
                if data.get("report_id") == report_id or candidate.parent.name == report_id:
                    matches.append((candidate, data))
            if len(matches) > 1:
                raise APIError(
                    ErrorCode.INTEGRITY_ERROR,
                    "report ID resolves to multiple report artifacts",
                    {"report_id": report_id, "match_count": len(matches)},
                )
            if len(matches) == 1:
                report_file, data = matches[0]
                experiment_id, battery_id = report_file.parents[2].name, report_file.parents[3].name
                entries = list(
                    (report_file.parent.parent).rglob("scientific_report.json")
                )
                latest_report_id = max(
                    entries, key=lambda path: path.stat().st_mtime
                ).parent.name
                context = self._report_workflow_context(battery_id, experiment_id)
                return self._annotate_report_freshness(
                    data,
                    latest_report_id,
                    context,
                    report_path=report_file,
                    battery_id=battery_id,
                    experiment_id=experiment_id,
                )
        raise APIError(ErrorCode.NOT_FOUND, "report not found")

    def _report_workflow_context(self, battery_id: str, experiment_id: str) -> dict[str, Any]:
        from battery_workbench.api.workflow_context import build_workflow_context

        return build_workflow_context(
            self.processed_root,
            battery_id,
            experiment_id,
            raw_root=self.raw_root,
        )

    def _annotate_report_freshness(
        self,
        report: dict[str, Any],
        latest_report_id: Any,
        context: dict[str, Any],
        *,
        report_path: Path | None = None,
        battery_id: str | None = None,
        experiment_id: str | None = None,
    ) -> dict[str, Any]:
        if context.get("meta", {}).get("source_integrity_status") == "INTEGRITY_BLOCKED":
            return {
                "report_id": report.get("report_id"),
                "generated_at": report.get("generated_at"),
                "scientific_status": "INTEGRITY_BLOCKED",
                "limitations": ["SOURCE_PROVENANCE_INVALID"],
                "report_freshness": {
                    "status": "INTEGRITY_BLOCKED",
                    "reasons": ["SOURCE_PROVENANCE_INVALID"],
                },
            }
        integrity_status = "NOT_CHECKED"
        integrity_reasons: list[str] = []
        if report_path is not None and report_path.is_file():
            from battery_workbench.reporting.report import verify_report_outputs

            integrity_status, integrity_reasons = verify_report_outputs(
                report_path,
                battery_id=battery_id,
                experiment_id=experiment_id,
                reports_root=(
                    self.processed_root
                    / "artifacts"
                    / str(battery_id)
                    / str(experiment_id)
                    / "reports"
                ),
            )
        if integrity_status == "INTEGRITY_BLOCKED":
            return {
                "report_id": report.get("report_id"),
                "scientific_status": "INTEGRITY_BLOCKED",
                "report_freshness": {
                    "status": "INTEGRITY_BLOCKED",
                    "reasons": integrity_reasons,
                },
                "limitations": ["REPORT_OUTPUT_INTEGRITY_INVALID"],
            }
        is_latest = report.get("report_id") == latest_report_id
        status = (
            context.get("artifact_freshness", {}).get("report", "LEGACY")
            if is_latest
            else "SUPERSEDED"
        )
        reasons: list[str] = []
        freshness = context.get("artifact_freshness", {})
        if freshness.get("dataset") == "STALE":
            reasons.append("DATASET_SOURCE_STALE")
        if freshness.get("models") in {"STALE", "LEGACY", "MISSING"}:
            reasons.append("MODEL_EVALUATION_NOT_CURRENT")
        canonical = (report.get("experiment_record") or {}).get("latest_canonical_artifacts") or {}
        current_chain = context.get("scientific_context", {})
        if (
            canonical.get("dataset_id") != current_chain.get("dataset_id")
            or canonical.get("split_id") != current_chain.get("split_id")
        ):
            reasons.append("REPORT_DATASET_OR_SPLIT_MISMATCH")
        if status == "LEGACY" and not reasons:
            reasons.append("REPORT_DATASET_OR_SPLIT_LINEAGE_MISSING")
        if status == "SUPERSEDED":
            reasons.append("NEWER_REPORT_EXISTS")
        if integrity_status == "LEGACY":
            reasons.extend(integrity_reasons)
            if status == "CURRENT":
                status = "LEGACY"
        annotated = dict(report)
        annotated["report_freshness"] = {
            "status": status,
            "reasons": list(dict.fromkeys(reasons)),
        }
        if integrity_status != "NOT_CHECKED":
            annotated["report_freshness"]["output_integrity_status"] = integrity_status
        return annotated

"""BRW-026 ToolGateway — the only path an agent takes to scientific code.

Agent → ToolGateway.execute(tool_name, context, inputs) → WorkbenchService /
IntakeEngine. The gateway enforces: security hygiene, eligibility,
confirmation binding, WAITING_FOR_USER passthrough, ClaimGuard on claims,
audit logging, and the unified result envelope.
"""

from __future__ import annotations

from typing import Any, ClassVar

from battery_workbench.agent_tools.eligibility import (
    EligibilityEngine,
    ReadinessSnapshot,
    ToolBlockedError,
)
from battery_workbench.agent_tools.models import (
    AgentScientificContext,
    ConfirmationPolicy,
    ConfirmationStore,
    EvidenceRef,
    PendingConfirmation,
    ScientificContext,
    ToolAuditEntry,
    ToolAuditLog,
    ToolResult,
)
from battery_workbench.agent_tools.registry import AgentToolRegistry, build_default_registry
from battery_workbench.agent_tools.security import (
    SecurityViolation,
    check_input_safety,
    check_parameter_guess,
)
from battery_workbench.api.errors import APIError
from battery_workbench.api.service import WorkbenchService
from battery_workbench.orchestrator.engine import OrchestratorError
from battery_workbench.reporting.schemas import ClaimGuard


class ToolExecutionError(RuntimeError):
    pass


def _digest(tool_name: str, inputs: dict[str, Any]) -> str:
    return PendingConfirmation.digest(tool_name, inputs)


class ToolGateway:
    """Single execution seam for agent tool calls."""

    def __init__(
        self,
        *,
        service: WorkbenchService,
        registry: AgentToolRegistry | None = None,
        audit_log: ToolAuditLog | None = None,
        confirmations: ConfirmationStore | None = None,
    ) -> None:
        self.service = service
        self.registry = registry or build_default_registry()
        self.audit = audit_log or ToolAuditLog()
        # bind BRW-027R semantic adapter handlers defined at module level
        for _name in (
            "inspect_research_state", "select_target", "inspect_alignment",
            "inspect_gate_readiness", "inspect_canonical_tof",
            "analyze_target_relationships",
            "prepare_ml_safe_dataset", "run_baseline_suite", "get_model_comparison",
        ):
            _fn = globals().get(f"_tool_{_name}")
            if _fn is not None and not hasattr(self, f"_tool_{_name}"):
                import types as _types

                setattr(self, f"_tool_{_name}", _types.MethodType(_fn, self))
        self.confirmations = confirmations or ConfirmationStore()
        self.eligibility = EligibilityEngine()

    # ---------- snapshot ----------
    def _readiness_snapshot(self, ctx: AgentScientificContext) -> ReadinessSnapshot:
        in_library = ctx.composite_id in self.service.intake.load_library()
        if not in_library and not self.service._experiment_exists(
            ctx.battery_id, ctx.experiment_id
        ):
            return ReadinessSnapshot(
                lifecycle="MISSING",
                readiness={},
                limitations=[],
                pending_actions=[],
                has_dataset=False,
                has_split=False,
                has_intake_assets=False,
                tof_blocked=False,
                soh_not_ready=False,
                experiment_missing=True,
            )
        try:
            summary = self.service.get_workspace_summary(ctx.battery_id, ctx.experiment_id)
        except Exception:  # noqa: BLE001 — freshly created library experiment has no artifacts yet
            library_entry = self.service.intake.load_library().get(ctx.composite_id, {})
            return ReadinessSnapshot(
                lifecycle=str(library_entry.get("status", "AWAITING_DATA")),
                readiness={},
                limitations=[],
                pending_actions=["upload_experiment_asset"],
                has_dataset=False,
                has_split=False,
                has_intake_assets=False,
                tof_blocked=False,
                soh_not_ready=False,
            )
        readiness = summary.get("readiness", {}) or {}
        tof_blocked = any(
            "tof" in key.lower() and str(value).upper() == "BLOCKED"
            for key, value in readiness.items()
        )
        soh_not_ready = any(
            "soh" in key.lower() and "NOT_READY" in str(value).upper()
            for key, value in readiness.items()
        )
        status = str(summary.get("scientific_status", "")).upper()
        artifacts = summary.get("latest_canonical_artifacts", {}) or {}
        assets = self.service.intake.load_library().get(ctx.composite_id, {})
        return ReadinessSnapshot(
            lifecycle=status or "AWAITING_DATA",
            readiness=readiness,
            limitations=[l.get("code", "") for l in summary.get("limitations_registry", [])],
            pending_actions=summary.get("next_actions", []),
            has_dataset=bool(artifacts.get("dataset_id")),
            has_split=bool(artifacts.get("split_id")),
            has_intake_assets=bool(assets) or bool(artifacts),
            tof_blocked=tof_blocked,
            soh_not_ready=soh_not_ready,
        )

    def _scientific_context(self, ctx: AgentScientificContext) -> ScientificContext:
        snap = self._readiness_snapshot(ctx)
        sc = ScientificContext(
            readiness=[{"key": k, "value": str(v)} for k, v in snap.readiness.items()],
            limitations=[{"code": c} for c in snap.limitations],  # type: ignore[misc]
        )
        if snap.tof_blocked:
            sc.warnings.append("TOF BLOCKED — value unavailable (null), never zero")
        if snap.soh_not_ready:
            sc.warnings.append("SOH NOT_READY_FOR_MODEL_EVALUATION")
        return sc

    # ---------- execute ----------
    def execute(
        self,
        tool_name: str,
        context: AgentScientificContext,
        inputs: dict[str, Any],
        *,
        confirmation_id: str | None = None,
    ) -> ToolResult:
        try:
            tool = self.registry.get(tool_name)
        except KeyError as e:
            raise ToolExecutionError(f"unknown tool: {tool_name}") from e

        try:
            check_input_safety(tool_name, inputs)
        except SecurityViolation as exc:
            return self._finish(
                tool_name,
                context,
                inputs,
                ToolResult(
                    status="FAILED",
                    error={"code": "SECURITY_VIOLATION", "message": str(exc)},
                ),
                confirmation_status="NOT_REQUIRED",
            )

        # eligibility
        snapshot = self._readiness_snapshot(context)
        allowed, reason = self.eligibility.evaluate(tool, snapshot)
        if not allowed:
            result = ToolResult(
                status="BLOCKED",
                error={"code": "TOOL_BLOCKED", "message": reason},
                scientific_context=self._scientific_context(context),
            )
            return self._finish(
                tool_name, context, inputs, result, confirmation_status="NOT_REQUIRED"
            )

        # no-guess guard runs BEFORE confirmation: invalid scientific input is
        # rejected outright regardless of confirmation state (§9)
        no_guess = getattr(tool, "no_guess_parameters", [])
        values_field = inputs.get("values")
        if no_guess and isinstance(values_field, dict):
            scientific_keys = {
                k
                for k in values_field
                if isinstance(k, str) and k.startswith(("ultrasound.", "experiment."))
            }
            if scientific_keys and not (values_field.get("_source") or values_field.get("source")):
                return self._finish(
                    tool_name,
                    context,
                    inputs,
                    ToolResult(
                        status="FAILED",
                        error={
                            "code": "SECURITY_VIOLATION",
                            "message": (
                                f"values for {sorted(scientific_keys)} require a '_source' "
                                "field identifying the human provider (agent must not guess)"
                            ),
                        },
                    ),
                    confirmation_status="NOT_REQUIRED",
                )

        # confirmation policy
        if tool.confirmation_required in (
            ConfirmationPolicy.USER_CONFIRMATION,
            ConfirmationPolicy.USER_INPUT_REQUIRED,
        ):
            if confirmation_id is None:
                pending = self.confirmations.issue(tool_name, inputs, tool.confirmation_required)
                result = ToolResult(
                    status="CONFIRMATION_REQUIRED",
                    data={"policy": tool.confirmation_required.value, "summary": pending.summary},
                    confirmation={
                        "confirmation_id": pending.confirmation_id,
                        "tool_name": pending.tool_name,
                        "inputs_digest": pending.inputs_digest,
                        "expires_at": pending.expires_at,
                    },
                    scientific_context=self._scientific_context(context),
                    next_actions=[f"重新调用 {tool_name} 并携带 confirmation_id 以执行"],
                )
                return self._finish(
                    tool_name, context, inputs, result, confirmation_status="PENDING"
                )
            try:
                self.confirmations.validate(confirmation_id, tool_name, inputs)
            except PermissionError as exc:
                result = ToolResult(
                    status="CONFIRMATION_REQUIRED",
                    error={"code": "CONFIRMATION_INVALID", "message": str(exc)},
                    scientific_context=self._scientific_context(context),
                )
                return self._finish(
                    tool_name, context, inputs, result, confirmation_status="INVALID"
                )
            self.confirmations.consume(confirmation_id)

        # dispatch
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            result = ToolResult(
                status="FAILED", error={"code": "NOT_IMPLEMENTED", "message": tool_name}
            )
        else:
            try:
                result = handler(context, inputs)
            except APIError as exc:
                result = ToolResult(
                    status="FAILED",
                    error={"code": exc.code.value, "message": exc.message, "details": exc.details},
                    scientific_context=self._scientific_context(context),
                )
            except OrchestratorError as exc:
                result = ToolResult(
                    status="FAILED",
                    error={"code": "ORCHESTRATOR_ERROR", "message": str(exc)},
                    scientific_context=self._scientific_context(context),
                )
            except ToolBlockedError as exc:
                result = ToolResult(
                    status="BLOCKED",
                    error={"code": "TOOL_BLOCKED", "message": exc.reason},
                    scientific_context=self._scientific_context(context),
                )
            except PermissionError as exc:
                result = ToolResult(
                    status="BLOCKED",
                    error={"code": "NOT_FOUND_OR_FORBIDDEN", "message": str(exc)},
                    scientific_context=self._scientific_context(context),
                )
        return self._finish(tool_name, context, inputs, result, confirmation_status="CONFIRMED")

    # ---------- envelope helpers ----------
    def _finish(
        self,
        tool_name: str,
        context: AgentScientificContext,
        inputs: dict[str, Any],
        result: ToolResult,
        *,
        confirmation_status: str,
    ) -> ToolResult:
        self.audit.append(
            ToolAuditEntry(
                tool_call_id=result.tool_call_id,
                tool_name=tool_name,
                timestamp=result.request_id,
                inputs_digest=_digest(tool_name, inputs),
                confirmation_status=confirmation_status,
                result_status=result.status,
                resource_ids={
                    "battery_id": context.battery_id,
                    "experiment_id": context.experiment_id,
                    **({"run_id": context.run_id} if context.run_id else {}),
                    **({"gate_id": context.gate_id} if context.gate_id else {}),
                },
                run_id=context.run_id,
                request_id=result.request_id,
                evidence_refs=[f"{e.evidence_type}:{e.evidence_ref}" for e in result.evidence],
            )
        )
        return result

    def _wrap(
        self,
        data: dict[str, Any],
        ctx: AgentScientificContext,
        *,
        status: str = "SUCCEEDED",
        evidence: list[EvidenceRef] | None = None,
        next_actions: list[str] | None = None,
    ) -> ToolResult:
        return ToolResult(
            status=status,  # type: ignore[arg-type]
            data=data,
            scientific_context=self._scientific_context(ctx),
            evidence=evidence or [],
            next_actions=next_actions or [],
        )

    # ---------- discovery ----------
    def _tool_list_experiments(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        resp = self.service.intake.load_library()
        legacy = self.service.list_experiments()
        known = set(resp.keys())
        items = list(resp.values())
        for l in legacy:
            composite = l.get("experiment_composite_id")
            if composite and composite not in known:
                items.append(
                    {
                        "battery_id": l["battery_id"],
                        "experiment_id": l["experiment_id"],
                        "composite_id": composite,
                        "name": composite,
                        "status": "READY",
                        "is_demo": True,
                    }
                )
        return self._wrap({"experiments": items, "count": len(items)}, ctx)

    def _tool_inspect_experiment(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        try:
            data = self.service.get_experiment(b, e)
        except APIError:
            # freshly created library experiment (no processed artifacts yet)
            try:
                data = self.service.intake.load_experiment(b, e).model_dump(mode="json")
            except KeyError as exc:
                raise PermissionError("experiment not found") from exc
        return self._wrap(data, ctx)

    def _tool_inspect_data_quality(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        from battery_workbench.api.routes.data import data_quality as _dq

        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        data = _dq(_FakeRequest(self.service), b, e)["data"]  # type: ignore[arg-type]
        return self._wrap(data, ctx)

    def _tool_inspect_synchronization(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        from battery_workbench.api.routes.data import synchronization as _sync

        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        data = _sync(_FakeRequest(self.service), b, e)["data"]  # type: ignore[arg-type]
        return self._wrap(data, ctx)

    def _tool_inspect_measurement_events(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        from battery_workbench.api.routes.data import measurement_events as _me

        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        data = _me(
            _FakeRequest(self.service),  # type: ignore[arg-type]
            b,
            e,
            int(inputs.get("limit", 20)),
            inputs.get("cursor"),  # type: ignore[arg-type]
        )["data"]
        return self._wrap(data, ctx)

    def _tool_inspect_run(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        run_id = inputs.get("run_id") or ctx.run_id
        if not run_id:
            raise PermissionError("run_id required")
        data = self.service.get_run(run_id)
        return self._wrap(data, ctx)

    def _tool_inspect_lineage(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        data = self.service.get_lineage(b, e)
        return self._wrap(data, ctx)

    def _tool_inspect_intake_capabilities(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        from battery_workbench.io.adapters.registry import build_default_adapter_registry

        registry = build_default_adapter_registry()
        adapters = [
            {
                "modality": m,
                "adapter_id": registry.get(m).adapter_name,
                "adapter_version": registry.get(m).adapter_version,
            }
            for m in sorted(registry.modalities())
        ]
        return self._wrap(
            {
                "adapters": adapters,
                "supported_roles": ["ELECTRICAL", "ULTRASOUND", "EXPERIMENT_METADATA", "AUXILIARY"],
            },
            ctx,
        )

    # ---------- intake ----------
    def _tool_create_experiment(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        record = self.service.intake.create_experiment(
            battery_id=inputs["battery_id"],
            experiment_id=inputs.get("experiment_id"),
            name=inputs["name"],
            notes=str(inputs.get("notes", "")),
        )
        return self._wrap(record.model_dump(mode="json"), ctx, next_actions=["start_intake"])

    def _tool_load_demo(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        from battery_workbench.api.routes.data import load_demo as _load_demo

        data = _load_demo(
            _FakeRequest(self.service),  # type: ignore[arg-type]
            inputs["battery_id"],
            inputs["experiment_id"],
        )["data"]
        return self._wrap(data, ctx)

    def _tool_start_intake(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        session = self.service.intake.create_session(b, e)
        return self._wrap(
            {**session.model_dump(mode="json"), "battery_id": b, "experiment_id": e},
            ctx,
            next_actions=["upload_experiment_asset"],
        )

    def _tool_upload_experiment_asset(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        session_id = inputs["session_id"]
        content = inputs.get("content")
        if content is None:
            raise SecurityViolation(
                "asset content required (file_ref tokens are not supported yet)"
            )
        session = self.service.intake.load_session(session_id)
        # latin-1 roundtrip is byte-preserving for agent-delivered binary assets
        content = content.encode("latin-1") if isinstance(content, str) else content
        record = self.service.intake.store_asset(
            session,
            role=inputs["role"],
            original_filename=inputs["file_ref"],
            content=content,
        )
        return self._wrap(record.model_dump(mode="json"), ctx, next_actions=["detect_asset_format"])

    def _tool_detect_asset_format(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        session = self.service.intake.load_session(inputs["session_id"])
        detections = self.service.intake.detect(session)
        states = [d.state for d in detections]
        if "UNSUPPORTED" in states:
            return self._wrap(
                {"detections": [d.model_dump(mode="json") for d in detections]},
                ctx,
                status="BLOCKED",
                next_actions=["UNSUPPORTED: 更换文件或新增 adapter"],
            )
        if "DETECTED_AMBIGUOUS" in states:
            return self._wrap(
                {"detections": [d.model_dump(mode="json") for d in detections]},
                ctx,
                status="BLOCKED",
                next_actions=["DETECTED_AMBIGUOUS: 用户必须选择正确 adapter"],
            )
        return self._wrap(
            {"detections": [d.model_dump(mode="json") for d in detections]},
            ctx,
            next_actions=["validate_intake"],
        )

    def _tool_validate_intake(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        session = self.service.intake.load_session(inputs["session_id"])
        validation = self.service.intake.validate(session)
        data = validation.model_dump(mode="json")
        return self._wrap(
            data,
            ctx,
            status="SUCCEEDED" if validation.overall_passed else "FAILED",
            next_actions=["commit_intake"]
            if validation.overall_passed
            else ["RESOLVE_VALIDATION_FAILURES"],
        )

    def _tool_commit_intake(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        session = self.service.intake.load_session(inputs["session_id"])
        result = self.service.intake.commit(session)
        status = (
            "REUSED"
            if result.get("committed_at") and session.status == "COMMITTED"
            else "SUCCEEDED"
        )
        return self._wrap(
            result, ctx, status=status, next_actions=["run pipeline (INGEST_TO_MEASUREMENT_EVENTS)"]
        )

    def _tool_cancel_intake(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        session = self.service.intake.load_session(inputs["session_id"])
        session = self.service.intake.cancel(session)
        return self._wrap({"status": session.status}, ctx)

    # ---------- parameters ----------
    def _tool_inspect_missing_parameters(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        status = self.service.get_status(b, e)
        params = self.service.list_parameters(b, e)
        return self._wrap(
            {
                "scientific_status": status,
                "parameter_sets": params,
                "no_guess_parameters": [
                    "ultrasound.sampling_rate_hz",
                    "ultrasound.trigger_sample_index",
                    "experiment.timezone",
                    "experiment.ultrasound_path_length_m",
                ],
            },
            ctx,
        )

    def _tool_set_experiment_parameter(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        name = inputs["parameter_name"]
        value = inputs["value"]
        source = inputs.get("source", "")
        check_parameter_guess(name, value, inferred_from=source or None)
        if not source:
            raise SecurityViolation(
                f"setting {name} requires an explicit user-provided source (no inference)"
            )
        # 参数写入通过 run 的 user_overrides 通道（BRW-015），此处返回用户动作指引
        return self._wrap(
            {
                "parameter_name": name,
                "value": value,
                "source": source,
                "note": "parameter applies through orchestrator user_overrides at next run; stored as USER_SUPPLIED/UNVERIFIED",
            },
            ctx,
            next_actions=["run pipeline with the provided parameter"],
        )

    # ---------- waveforms / gates ----------
    def _tool_list_waveform_frames(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        frames = self._waveform_list(b, e)
        return self._wrap(frames, ctx)

    def _waveform_list(self, b: str, e: str) -> dict[str, Any]:
        frames_path = self.service.processed_root / "ultrasound" / b / e / "frames.parquet"
        if not frames_path.is_file():
            raise PermissionError("waveform store not available")
        import pandas as pd

        frames = pd.read_parquet(frames_path, columns=["frame_index_raw", "waveform_sample_count"])
        return {
            "frame_count": len(frames),
            "waveform_length": int(frames["waveform_sample_count"].iloc[0]) if len(frames) else 0,
            "x_axis": "SAMPLE_INDEX",
            "time_axis_available": False,
        }

    def _tool_inspect_waveform_frame(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        import numpy as np
        import pandas as pd
        import zarr

        base = self.service.processed_root / "ultrasound" / b / e
        if not (base / "frames.parquet").is_file():
            return ToolResult(
                status="BLOCKED",
                error={
                    "code": "ARTIFACT_NOT_AVAILABLE",
                    "message": "waveform store not available; run the ingest pipeline first",
                },
                scientific_context=self._scientific_context(ctx),
            )
        frames = pd.read_parquet(
            base / "frames.parquet",
            columns=["frame_index_raw", "waveform_group", "waveform_row_index"],
        )
        row = frames[frames["frame_index_raw"] == int(inputs["frame_index"])]
        if row.empty:
            raise PermissionError("frame not found")
        r = row.iloc[0]
        zg = zarr.open_group(str(base / "waveforms.zarr"), mode="r")
        wave = np.asarray(
            zg[str(r.waveform_group)][int(r.waveform_row_index)]  # type: ignore[index]
        )
        max_points = min(int(inputs.get("max_points", 250)), 1000)
        step = max(1, len(wave) // max_points)
        samples = [
            {"sample_index": int(i), "amplitude_a_u": float(wave[i])}
            for i in range(0, len(wave), step)
        ]
        return self._wrap(
            {
                "frame_index": int(inputs["frame_index"]),
                "waveform_length": len(wave),
                "x_axis": "SAMPLE_INDEX",
                "time_axis_us": None,
                "sampling_rate_status": "UNKNOWN",
                "samples": samples,
                "note": "bounded preview; full waveform never returned",
            },
            ctx,
        )

    def _tool_list_gates(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        return self._wrap({"gates": self.service.list_gates(b, e)}, ctx)

    def _tool_propose_gate(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        start = int(inputs["start_sample"])
        end = int(inputs["end_sample"])
        length = int(inputs.get("waveform_length", 1250))
        gate_name = inputs.get("gate_name", f"Gate-{start}-{end}")
        issues = []
        if not (0 <= start < end <= length):
            issues.append("bounds must satisfy 0 <= start < end <= waveform_length")
        return self._wrap(
            {
                "proposal": {
                    "gate_name": gate_name,
                    "start_sample": start,
                    "end_sample": end,
                    "waveform_length": length,
                    "valid": not issues,
                },
                "issues": issues,
            },
            ctx,
            next_actions=["create_gate (requires user confirmation)"],
        )

    def _tool_create_gate(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        result = self.service.create_gate(
            {
                "battery_id": b,
                "experiment_id": e,
                "gate_name": inputs["gate_name"],
                "start_sample": int(inputs["start_sample"]),
                "end_sample": int(inputs["end_sample"]),
                "waveform_length": int(inputs.get("waveform_length", 1250)),
            }
        )
        ctx.gate_id = result["gate_id"]
        status = "REUSED" if result["reuse_status"] == "REUSED" else "SUCCEEDED"
        return self._wrap(result, ctx, status=status)

    # ---------- features / analysis ----------
    def _tool_list_available_features(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        return self._wrap({"features": self.service.list_features(b, e)}, ctx)

    def _tool_inspect_feature(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        name = inputs["feature_name"]
        features = self.service.list_features(b, e)
        feature = next((f for f in features if f["feature_name"] == name), None)
        if feature is None:
            raise PermissionError(f"unknown feature: {name}")
        return self._wrap(feature, ctx)

    def _tool_analyze_feature_relationships(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        result = self.service.create_feature_analysis(
            {
                "battery_id": b,
                "experiment_id": e,
                "analysis_mode": inputs["analysis_mode"],
                "target": inputs["target"],
                "candidate_features": list(inputs["candidate_features"]),
            }
        )
        evidence = [
            EvidenceRef(
                evidence_type="DERIVED_COMPUTATION",
                evidence_ref=f"feature_analysis:{result['analysis_id']}",
                artifact_id=result["analysis_id"],
                availability="AVAILABLE",
            )
        ]
        ctx.analysis_id = result["analysis_id"]
        return self._wrap(
            result, ctx, evidence=evidence, next_actions=["propose_feature_selection"]
        )

    def _tool_propose_feature_selection(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        features = list(inputs["selected_features"])
        return self._wrap(
            {"selected_features": features, "basis": "agent proposal (draft)", "confirmed": False},
            ctx,
            next_actions=["confirm_feature_selection (requires user confirmation)"],
        )

    def _tool_confirm_feature_selection(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        features = list(inputs["selected_features"])
        available = {
            f["feature_name"]
            for f in self.service.list_features(b, e)
            if f["availability"] == "AVAILABLE"
        }
        unknown = [f for f in features if f not in available]
        if unknown:
            raise PermissionError(f"unavailable features cannot be selected: {unknown}")
        return self._wrap(
            {"selected_features": features, "confirmed": True, "confirmation": "user"},
            ctx,
            next_actions=["prepare_soc_dataset"],
        )

    # ---------- dataset / evaluation ----------
    def _tool_prepare_soc_dataset(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        result = self.service.create_dataset(
            {
                "battery_id": b,
                "experiment_id": e,
                "dataset_family": "SOC",
                "selected_features": list(inputs.get("selected_features", [])),
            }
        )
        ctx.dataset_id = result.get("dataset_id")
        status = "REUSED" if result.get("status") == "REUSED" else "SUCCEEDED"
        return self._wrap(
            result, ctx, status=status, next_actions=["prepare_grouped_evaluation_split"]
        )

    def _tool_prepare_grouped_evaluation_split(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        dataset_id = inputs.get("dataset_id") or ctx.dataset_id
        if not dataset_id:
            raise ToolBlockedError(
                "prepare_grouped_evaluation_split",
                "dataset_id required (run prepare_soc_dataset first)",
            )
        result = self.service.create_split(
            {
                "battery_id": b,
                "experiment_id": e,
                "dataset_id": dataset_id,
            }
        )
        ctx.split_id = result.get("split_id")
        status = "REUSED" if result.get("status") == "REUSED" else "SUCCEEDED"
        return self._wrap(result, ctx, status=status, next_actions=["run_limited_soc_baselines"])

    def _tool_run_limited_soc_baselines(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        dataset_id = inputs.get("dataset_id") or ctx.dataset_id
        split_id = inputs.get("split_id") or ctx.split_id
        if not dataset_id or not split_id:
            raise ToolBlockedError("run_limited_soc_baselines", "dataset_id and split_id required")
        result = self.service.create_baseline_model(
            {
                "battery_id": b,
                "experiment_id": e,
                "strategy": "RIDGE",
                "dataset_id": dataset_id,
                "split_id": split_id,
                "fold_index": 1,
                "selection_id": "SEL::agent",
                "selected_features": list(inputs.get("selected_features", [])),
            }
        )
        evidence = [
            EvidenceRef(
                evidence_type="DERIVED_COMPUTATION",
                evidence_ref=f"model:{result['model_id']}",
                artifact_id=result["model_id"],
                availability="AVAILABLE",
            )
        ]
        return self._wrap(
            result,
            ctx,
            evidence=evidence,
            next_actions=["inspect_model_comparison", "generate_scientific_report"],
        )

    def _tool_inspect_model_comparison(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        results = self.service.get_results(b, e, limit=200)
        macro = [r for r in results if r.get("result_type") == "MODEL_COMPARISON"]
        dummy = next((r for r in macro if r.get("strategy") == "DUMMY_MEAN"), None)
        evidence = [
            EvidenceRef(
                evidence_type=r["evidence_type"],
                evidence_ref=r["evidence_ref"],
                artifact_id=r.get("source_artifact_id"),
                availability="AVAILABLE",
            )
            for r in macro[:3]
        ]
        data: dict[str, Any] = {"macro": macro, "dummy_baseline": dummy}
        if dummy and macro:
            real = [
                r
                for r in macro
                if r.get("strategy") != "DUMMY_MEAN" and isinstance(r.get("value"), (int, float))
            ]
            if real:
                best = min(real, key=lambda r: r["value"])
                data["real_beats_dummy"] = bool((best["value"] or 0) < (dummy.get("value") or 0))
                data["honest_note"] = (
                    "evaluation complete; predictive advantage not demonstrated"
                    if (best["value"] or 0) >= (dummy.get("value") or 0)
                    else ""
                )
        return self._wrap(data, ctx, evidence=evidence)

    # ---------- run execution ----------
    _ALLOWED_PROFILES: ClassVar[set[str]] = {
        "INGEST_TO_MEASUREMENT_EVENTS",
        "SCIENTIFIC_ANALYSIS",
        "FULL_PRE_MODEL",
    }

    def _tool_start_run(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        profile = inputs["profile"]
        if profile not in self._ALLOWED_PROFILES:
            raise ToolBlockedError(
                "start_run", f"profile {profile!r} is not an allowed fixed profile"
            )
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        plan = self.service._runs.plan_run(
            runs_root=self.service.runs_root,
            profile=profile,
            battery_id=b,
            experiment_id=e,
            dry_run=bool(inputs.get("dry_run", False)),
            **({"stages": inputs["stages"]} if inputs.get("stages") else {}),
            **({"parameters": inputs["parameters"]} if inputs.get("parameters") else {}),
            **({"split": inputs["split"]} if inputs.get("split") else {}),
        )
        result = self.service._runs.start_run(plan, runs_root=self.service.runs_root)
        ctx.run_id = result.get("run_id")
        return self._wrap(result, ctx, next_actions=["list_pending_user_actions", "inspect_run"])

    # ---------- human interaction (resume loop) ----------
    def _owned_run(self, ctx: AgentScientificContext, run_id: str) -> dict[str, Any]:
        """Load a run and verify it belongs to the bound experiment (§5 isolation)."""
        run = self.service.get_run(run_id)
        run_battery = run.get("battery_id")
        run_experiment = run.get("experiment_id")
        if (
            run_battery
            and run_experiment
            and (run_battery, run_experiment) != (ctx.battery_id, ctx.experiment_id)
        ):
            raise PermissionError(
                f"run {run_id} belongs to {run_battery}/{run_experiment}, "
                f"not the bound experiment {ctx.composite_id}"
            )
        return run

    def _tool_list_pending_user_actions(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        run_id = inputs.get("run_id") or ctx.run_id
        if not run_id:
            raise PermissionError("run_id required")
        run = self._owned_run(ctx, run_id)
        actions = run.get("user_actions", [])
        return self._wrap(
            {"run_id": run_id, "run_status": run.get("status"), "pending_actions": actions},
            ctx,
            next_actions=[
                f"submit_user_action(action_id={a.get('action_id')}) with user-provided values"
                for a in actions
            ]
            or ["run has no pending actions"],
        )

    def _tool_submit_user_action(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        run_id = inputs.get("run_id") or ctx.run_id
        if not run_id:
            raise PermissionError("run_id required")
        self._owned_run(ctx, run_id)  # ownership binding
        action_id = inputs["action_id"]
        values = dict(inputs.get("values") or {})
        # provenance marker is tool-layer metadata, never a scientific parameter
        values.pop("_source", None)
        result = self.service._runs.submit_user_action(
            run_id, action_id, values=values, runs_root=self.service.runs_root
        )
        return self._wrap(result, ctx, next_actions=["resume_run"])

    def _tool_resume_run(self, ctx: AgentScientificContext, inputs: dict[str, Any]) -> ToolResult:
        run_id = inputs.get("run_id") or ctx.run_id
        if not run_id:
            raise PermissionError("run_id required")
        run = self._owned_run(ctx, run_id)
        # lineage preservation: resume_run appends RUN_RESUMED to the SAME run_dir (BRW-019 §14)
        if run.get("status") not in ("WAITING_FOR_USER", "FAILED", "PARTIAL"):
            # submit_user_action already resumed internally (BRW-019 submit→resume
            # contract). Idempotent: same run, no new run created.
            return self._wrap(
                {
                    **run,
                    "resumed_run_id": run_id,
                    "original_run_id": run_id,
                    "lineage_preserved": True,
                    "note": "already resumed/finished; no new run created",
                },
                ctx,
                next_actions=["inspect_run"],
            )
        result = self.service._runs.resume_run(run_id, runs_root=self.service.runs_root)
        ctx.run_id = run_id
        return self._wrap(
            {
                **result,
                "resumed_run_id": run_id,
                "original_run_id": run_id,
                "lineage_preserved": True,
            },
            ctx,
            next_actions=["inspect_run", "list_pending_user_actions"],
        )

    # ---------- reporting / evidence ----------
    def _tool_generate_scientific_report(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        try:
            result = self.service.generate_report({"battery_id": b, "experiment_id": e})
        except APIError as exc:
            if exc.code.value == "NOT_FOUND":
                # freshly created library experiment: no artifacts yet — report is REUSED-empty
                return self._wrap(
                    {
                        "report_id": None,
                        "status": "NOT_AVAILABLE",
                        "reason": "no scientific artifacts yet; run the pipeline first",
                    },
                    ctx,
                    status="REUSED",
                    next_actions=["run pipeline INGEST_TO_MEASUREMENT_EVENTS first"],
                )
            raise
        return self._wrap(
            result, ctx, next_actions=["inspect_scientific_report", "explain_result_evidence"]
        )

    def _tool_inspect_scientific_report(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        data = self.service.get_report(inputs["report_id"])
        return self._wrap(data, ctx)

    def _tool_explain_result_evidence(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        result_id = inputs["result_id"]
        claim = inputs.get("claim", "")
        if claim:
            try:
                ClaimGuard.check(claim)  # raises on unsupported claims
            except ValueError as exc:
                return ToolResult(
                    status="BLOCKED",
                    error={"code": "UNSUPPORTED_CLAIM", "message": str(exc)},
                    scientific_context=self._scientific_context(ctx),
                )
        results = self.service.get_results(b, e, limit=500)
        record = next((r for r in results if r.get("result_id") == result_id), None)
        if record is None:
            raise PermissionError(f"result not found: {result_id}")
        evidence = [
            EvidenceRef(
                evidence_type=str(record.get("evidence_type") or "UNKNOWN"),
                evidence_ref=str(record.get("evidence_ref") or ""),
                artifact_id=record.get("source_artifact_id"),
                availability="AVAILABLE",
            )
        ]
        return self._wrap(
            {
                "result_id": record.get("result_id"),
                "value": record.get("value"),
                "units": record.get("units"),
                "evidence_type": record.get("evidence_type"),
                "evidence_ref": record.get("evidence_ref"),
                "artifact_id": record.get("source_artifact_id"),
                "limitations": record.get("limitations", []),
                "claim_scope": record.get("limitations") or ["LIMITED_CROSS_CYCLE_GENERALIZATION"],
                "claim_checked": claim or None,
            },
            ctx,
            evidence=evidence,
        )

    def _tool_inspect_evidence(
        self, ctx: AgentScientificContext, inputs: dict[str, Any]
    ) -> ToolResult:
        b = inputs.get("battery_id") or ctx.battery_id
        e = inputs.get("experiment_id") or ctx.experiment_id
        return self._wrap({"evidence": self.service.get_evidence(b, e)}, ctx)


class _FakeRequest:  # type: ignore[type-arg]
    """Minimal request shim so tools can reuse API route handlers."""

    def __init__(self, service: WorkbenchService) -> None:
        self.app = type("App", (), {"state": type("State", (), {"workbench_service": service})()})()


# ---------------------------------------------------------------------------
# BRW-027R high-level semantic adapters — thin orchestration over existing
# service capabilities; no scientific algorithms here.
# ---------------------------------------------------------------------------


def _tool_inspect_research_state(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    from battery_workbench.api.routes.assistant import _FakeRequestBridge
    from battery_workbench.api.routes.features_v2 import (
        alignment_summary as _align_summary,
    )
    from battery_workbench.api.routes.features_v2 import (
        list_targets as _targets,
    )

    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    bridge = _FakeRequestBridge(self.service)
    targets = _targets(bridge, b, e)["data"]["targets"]
    alignment = _align_summary(bridge, b, e)["data"]
    return self._wrap(
        {
            "targets": targets,
            "alignment": alignment,
            "session_refs": {
                "dataset_id": ctx.dataset_id,
                "split_id": ctx.split_id,
                "run_id": ctx.run_id,
                "current_page": ctx.current_ui_route,
            },
        },
        ctx,
    )


def _tool_select_target(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    from battery_workbench.api.routes.assistant import _FakeRequestBridge
    from battery_workbench.api.routes.features_v2 import list_targets as _targets

    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    target_id = inputs["target_id"]
    bridge = _FakeRequestBridge(self.service)
    targets = {t["target_id"]: t for t in _targets(bridge, b, e)["data"]["targets"]}
    if target_id not in targets:
        return ToolResult(status="BLOCKED", error={"code": "UNKNOWN_TARGET", "message": target_id})
    t = targets[target_id]
    ready = t["readiness"] in ("READY", "READY_FOR_LIMITED_EVALUATION")
    return self._wrap(
        {"target": t, "ready": ready,
         "note": "Reference SOC is a retrospective reference label" if target_id == "reference_soc_percent" else None},
        ctx,
        status="SUCCEEDED" if ready else "BLOCKED",
        next_actions=["inspect_alignment"],
    )


def _tool_inspect_alignment(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    from battery_workbench.api.routes.assistant import _FakeRequestBridge
    from battery_workbench.api.routes.features_v2 import (
        alignment_exclusions as _excl,
    )
    from battery_workbench.api.routes.features_v2 import (
        alignment_summary as _align_summary,
    )

    bridge = _FakeRequestBridge(self.service)
    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    summary = _align_summary(bridge, b, e)["data"]
    excl = _excl(bridge, b, e)["data"]["exclusions"]
    return self._wrap({"summary": summary, "exclusions": excl}, ctx)


def _tool_inspect_gate_readiness(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    gates = self._tool_list_gates(ctx, inputs)
    return self._wrap(
        {"gates": gates.data.get("gates", []),
         "note": "gate templates require recalibration on configuration change"},
        ctx,
    )


def _tool_inspect_canonical_tof(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    """BRW-017R2 — canonical envelope-peak TOF readiness + audit summary.

    Reads fs provenance and computes the canonical series summary through the
    same route the API exposes; no fs guessing, no XCorr reuse.
    """
    from battery_workbench.api.routes.assistant import _FakeRequestBridge
    from battery_workbench.api.routes.features_v2 import canonical_tof as _route

    bridge = _FakeRequestBridge(self.service)
    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    out = _route(bridge, b, e, limit=min(int(inputs.get("limit", 200)), 4000))["data"]
    return self._wrap(out, ctx)


def _tool_analyze_target_relationships(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    from battery_workbench.api.routes.assistant import _FakeRequestBridge
    from battery_workbench.api.routes.features_v2 import feature_target_ranking as _rank

    bridge = _FakeRequestBridge(self.service)
    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    body = {
        "target_id": inputs["target_id"],
        "features": list(inputs["features"]),
        "mode": inputs.get("mode", "EXPLORATORY"),
    }
    out = _rank(bridge, b, e, body)["data"]
    return self._wrap(out, ctx)


def _tool_prepare_ml_safe_dataset(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    target_id = inputs.get("target_id", "reference_soc_percent")
    result = self.service.create_dataset(
        {
            "battery_id": b,
            "experiment_id": e,
            "dataset_family": "SOC",
            "target": "soc_reference_percent" if target_id == "reference_soc_percent" else target_id,
            "selected_features": list(inputs.get("features", [])) or None,
        }
    )
    return self._wrap(result, ctx, next_actions=["prepare_grouped_evaluation_split"])


def _tool_run_baseline_suite(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    b = inputs.get("battery_id") or ctx.battery_id
    e = inputs.get("experiment_id") or ctx.experiment_id
    dataset_id = inputs.get("dataset_id") or ctx.dataset_id
    split_id = inputs.get("split_id") or ctx.split_id
    if not dataset_id or not split_id:
        raise PermissionError("dataset_id and split_id required")
    return self._tool_run_limited_soc_baselines(
        ctx, {"battery_id": b, "experiment_id": e, "dataset_id": dataset_id, "split_id": split_id}
    )


def _tool_get_model_comparison(
    self, ctx: AgentScientificContext, inputs: dict[str, Any]
) -> ToolResult:
    return self._tool_inspect_model_comparison(ctx, inputs)


TOOL_GATEWAY_EXTRA_HANDLERS = True

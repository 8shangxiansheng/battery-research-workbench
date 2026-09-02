"""BRW-019 Pipeline Orchestrator engine: dry-run, execution, resume, retry.

The engine only sequences adapters and manages state/events. It never
computes scientific values and never guesses user inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from battery_workbench.orchestrator.dag import (
    NODE_DEPENDENCIES,
    topological_order,
)
from battery_workbench.orchestrator.nodes import default_nodes
from battery_workbench.orchestrator.resolver import content_hash
from battery_workbench.orchestrator.schemas import (
    AnalysisPlan,
    ArtifactRef,
    ExecutionPlan,
    NodeResult,
    NodeState,
    RunManifest,
    RunState,
    UserActionRequired,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class OrchestratorError(RuntimeError):
    pass


@dataclass
class RunContext:
    raw_root: Path
    processed_root: Path
    runs_root: Path
    run_id: str
    run_dir: Path
    user_overrides: dict[str, Any] = field(default_factory=dict)


class PipelineOrchestrator:
    def __init__(self, *, raw_root: Path, processed_root: Path, runs_root: Path | None = None):
        self.raw_root = Path(raw_root)
        self.processed_root = Path(processed_root)
        self.runs_root = (
            Path(runs_root)
            if runs_root is not None
            else self.processed_root.parent / "artifacts" / "runs"
        )
        self.nodes = {n.node_type: n for n in default_nodes()}

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan_run(
        self,
        *,
        profile: str,
        battery_id: str,
        experiment_id: str,
        dry_run: bool = False,
        reuse_existing: bool = True,
        force_recompute: list[str] | None = None,
        runs_root: Path | None = None,
        **plan_fields: Any,
    ) -> AnalysisPlan:
        from battery_workbench.orchestrator.schemas import build_plan

        return build_plan(
            profile=profile,
            battery_id=battery_id,
            experiment_id=experiment_id,
            dry_run=dry_run,
            reuse_existing=reuse_existing,
            force_recompute=force_recompute or [],
            **plan_fields,
        )

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def dry_run(self, plan: AnalysisPlan) -> ExecutionPlan:
        """Dry run: REUSED / RUNNING / BLOCKED / WAITING_FOR_USER / SKIPPED.

        Dry run writes no scientific artifacts.
        """
        order = topological_order(plan.stages, NODE_DEPENDENCIES)
        states: dict[str, NodeState] = {}
        results: dict[str, NodeResult] = {}

        for node_id in order:
            node = self.nodes[node_id]
            ref, reason = node.resolve_existing_output(plan, {}, self.processed_root)
            deps = NODE_DEPENDENCIES.get(node_id, [])
            dep_states = [states[d] for d in deps if d in states]

            if node_id in plan.execution.force_recompute:
                result = NodeResult(
                    node_id=node_id, state=NodeState.RUNNING, reason="forced recompute"
                )
            elif any(s == NodeState.RUNNING for s in dep_states):
                result = NodeResult(
                    node_id=node_id,
                    state=NodeState.RUNNING,
                    reason="upstream invalidated (will re-evaluate)",
                )
            elif plan.execution.reuse_existing and ref is not None:
                status_note = f" [status={ref.status}]" if ref.status else ""
                result = NodeResult(
                    node_id=node_id,
                    state=NodeState.REUSED,
                    reason=reason + status_note,
                    outputs=[ref],
                )
            elif any(s in (NodeState.BLOCKED, NodeState.WAITING_FOR_USER) for s in dep_states):
                result = NodeResult(
                    node_id=node_id, state=NodeState.BLOCKED, reason="upstream blocked/waiting"
                )
            else:
                readiness = node.validate_readiness(plan, {})
                if readiness.ok:
                    result = NodeResult(node_id=node_id, state=NodeState.RUNNING, reason=reason)
                elif readiness.user_action is not None:
                    result = NodeResult(
                        node_id=node_id,
                        state=NodeState.WAITING_FOR_USER,
                        reason=readiness.reason,
                        user_action_required=readiness.user_action,
                    )
                else:
                    result = NodeResult(
                        node_id=node_id, state=NodeState.BLOCKED, reason=readiness.reason
                    )
            results[node_id] = result
            states[node_id] = result.state

        ordered = [results[n] for n in order]
        return ExecutionPlan(plan_id=plan.plan_id, dry_run=True, nodes=ordered)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def start_run(self, plan: AnalysisPlan, *, runs_root: Path | None = None) -> dict[str, Any]:
        runs_root = Path(runs_root) if runs_root is not None else self.runs_root
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = f"RUN::{stamp}-{plan.plan_id.split('::')[1][:8]}"
        run_dir = runs_root / run_id.replace("RUN::", "")
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_plan(plan, run_dir)
        ctx = RunContext(
            raw_root=self.raw_root,
            processed_root=self.processed_root,
            runs_root=runs_root,
            run_id=run_id,
            run_dir=run_dir,
            user_overrides=dict(plan.parameters.get("user_overrides") or {}),
        )
        self._append_event(run_dir, "RUN_CREATED", detail={"plan_id": plan.plan_id})
        return self._execute(plan, ctx)

    def _execute(self, plan: AnalysisPlan, ctx: RunContext) -> dict[str, Any]:
        order = topological_order(plan.stages, NODE_DEPENDENCIES)
        node_states: dict[str, NodeState] = {}
        user_actions: list[UserActionRequired] = []
        run_status = RunState.RUNNING

        # pass 1: reuse resolution + readiness
        resolved: dict[str, ArtifactRef] = {}
        node_results: dict[str, NodeResult] = {}
        for node_id in order:
            node = self.nodes[node_id]
            ref, reason = node.resolve_existing_output(plan, {}, self.processed_root)
            if (
                ref is not None
                and plan.execution.reuse_existing
                and node_id not in plan.execution.force_recompute
            ):
                result = NodeResult(
                    node_id=node_id,
                    node_version=node.node_version,
                    state=NodeState.REUSED,
                    engineering_success=True,
                    outputs=[ref],
                    reason=reason,
                    metrics={"reuse": True},
                )
                resolved[node_id] = ref
            else:
                readiness = node.validate_readiness(plan, resolved)
                if readiness.ok:
                    result = NodeResult(
                        node_id=node_id,
                        node_version=node.node_version,
                        state=NodeState.READY,
                        reason=reason,
                    )
                elif readiness.user_action is not None:
                    result = NodeResult(
                        node_id=node_id,
                        node_version=node.node_version,
                        state=NodeState.WAITING_FOR_USER,
                        reason=readiness.reason,
                        user_action_required=readiness.user_action,
                    )
                else:
                    result = NodeResult(
                        node_id=node_id,
                        node_version=node.node_version,
                        state=NodeState.BLOCKED,
                        reason=readiness.reason,
                    )
            node_results[node_id] = result
            node_states[node_id] = result.state

        # pass 2: run READY nodes in order (skip BLOCKED/WAITING/REUSED);
        # propagate blocked/failed/waiting to downstream
        for node_id in order:
            result = node_results[node_id]
            node = self.nodes[node_id]
            deps = NODE_DEPENDENCIES.get(node_id, [])
            dep_states = [node_states.get(d) for d in deps if d in node_states]
            if any(
                s
                in (
                    NodeState.FAILED,
                    NodeState.BLOCKED,
                    NodeState.WAITING_FOR_USER,
                    NodeState.PENDING,
                )
                for s in dep_states
            ):
                if result.state in (NodeState.READY, NodeState.PENDING):
                    result.state = NodeState.BLOCKED
                    result.reason = result.reason or "upstream not available"
                node_states[node_id] = result.state
                continue
            if result.state in (NodeState.READY, NodeState.PENDING):
                # collect upstream refs: from this run, or resolved on demand
                # (partial plans may execute a node whose deps are pre-existing)
                inputs: dict[str, ArtifactRef] = {}
                missing_deps: list[str] = []
                for dep in deps:
                    dep_result = node_results.get(dep)
                    if dep_result and dep_result.outputs:
                        inputs[dep] = dep_result.outputs[0]
                        continue
                    dep_node = self.nodes.get(dep)
                    if dep_node is None:
                        missing_deps.append(dep)
                        continue
                    dep_ref, _ = dep_node.resolve_existing_output(plan, {}, self.processed_root)
                    if dep_ref is not None:
                        inputs[dep] = dep_ref
                    else:
                        missing_deps.append(dep)
                if missing_deps:
                    result.state = NodeState.BLOCKED
                    result.reason = f"missing upstream artifacts: {missing_deps}"
                    node_states[node_id] = NodeState.BLOCKED
                    self._append_event(ctx.run_dir, "NODE_BLOCKED", node_id=node_id)
                    continue
                self._append_event(ctx.run_dir, "NODE_STARTED", node_id=node_id)
                try:
                    output = node.run(plan, inputs, ctx)
                    ref = ArtifactRef(
                        artifact_type=node_id,
                        artifact_id=str(output.get("artifact_id", "")),
                        battery_id=plan.project.battery_id,
                        experiment_id=plan.project.experiment_id,
                        path=str(output.get("path", "")),
                        manifest_path=str(output.get("manifest_path", "")),
                        producer_node=node_id,
                        producer_version=str(output.get("producer_version", "")),
                        content_hash=content_hash(Path(output["path"]))
                        if Path(output.get("path", "")).exists()
                        else "",
                        status=str(output.get("metrics", {}).get("status", "")),
                    )
                    result.state = NodeState.SUCCEEDED
                    result.engineering_success = True
                    result.outputs = [ref]
                    result.limitations = output.get("limitations", [])
                    result.metrics = output.get("metrics", {})
                    result.reason = "executed via existing module"
                    resolved[node_id] = ref
                    node_states[node_id] = NodeState.SUCCEEDED
                    self._append_event(ctx.run_dir, "NODE_SUCCEEDED", node_id=node_id)
                except Exception as exc:  # noqa: BLE001 — engine boundary
                    result.state = NodeState.FAILED
                    result.reason = f"{type(exc).__name__}: {exc}"
                    node_states[node_id] = NodeState.FAILED
                    self._append_event(ctx.run_dir, "NODE_FAILED", node_id=node_id, detail=str(exc))
            elif result.state == NodeState.WAITING_FOR_USER:
                user_actions.append(result.user_action_required)  # type: ignore[arg-type]
                self._append_event(
                    ctx.run_dir,
                    "USER_ACTION_REQUIRED",
                    node_id=node_id,
                    detail=result.user_action_required.model_dump(mode="json"),  # type: ignore[union-attr]
                )
                if result.user_action_required and result.user_action_required.blocking:
                    run_status = RunState.WAITING_FOR_USER

        # downstream of FAILED/BLOCKED/WAITING: BLOCKED
        for node_id in order:
            result = node_results[node_id]
            if result.state not in (NodeState.PENDING,):
                continue
            deps = NODE_DEPENDENCIES.get(node_id, [])
            if any(
                node_states.get(d)
                in (NodeState.FAILED, NodeState.BLOCKED, NodeState.WAITING_FOR_USER)
                for d in deps
            ):
                result.state = NodeState.BLOCKED
                result.reason = "upstream blocked/failed/waiting"
                node_states[node_id] = NodeState.BLOCKED

        # PENDING nodes that were never run (skipped by scope)
        for node_id in order:
            if node_results[node_id].state == NodeState.PENDING:
                node_results[node_id].state = NodeState.SKIPPED
                node_states[node_id] = NodeState.SKIPPED

        if any(n.state == NodeState.FAILED for n in node_results.values()):
            run_status = RunState.FAILED
        elif any(n.state == NodeState.WAITING_FOR_USER for n in node_results.values()):
            run_status = RunState.WAITING_FOR_USER
        elif any(n.state == NodeState.BLOCKED for n in node_results.values()):
            run_status = RunState.PARTIAL
        else:
            run_status = RunState.SUCCEEDED

        manifest = RunManifest(
            run_id=ctx.run_id,
            analysis_plan_id=plan.plan_id,
            battery_id=plan.project.battery_id,
            experiment_id=plan.project.experiment_id,
            status=run_status,
            started_at=_now(),
            processed_root=str(self.processed_root),
            nodes=list(node_results.values()),
            user_actions=user_actions,
            limitations=[lim for n in node_results.values() for lim in n.limitations],
            final_artifacts=[n.outputs[0] for n in node_results.values() if n.outputs],
        )
        self._write_run_manifest(manifest, ctx.run_dir)
        self._write_execution_plan(plan, node_results, ctx.run_dir)
        self._write_final_outputs(manifest, ctx.run_dir)
        self._append_event(
            ctx.run_dir, f"RUN_{run_status.value}", detail={"status": run_status.value}
        )
        return self._manifest_to_dict(manifest, run_dir=ctx.run_dir)

    # ------------------------------------------------------------------
    # Resume / retry
    # ------------------------------------------------------------------

    def resume_run(
        self,
        run_id: str,
        *,
        user_inputs: dict[str, Any] | None = None,
        action_id: str | None = None,
        runs_root: Path | None = None,
    ) -> dict[str, Any]:
        runs_root = Path(runs_root) if runs_root is not None else self.runs_root
        run_dir = runs_root / run_id.replace("RUN::", "")
        manifest = self._read_run_manifest(run_dir)
        if manifest["status"] not in ("WAITING_FOR_USER", "FAILED", "PARTIAL"):
            raise OrchestratorError(f"run {run_id} is not resumable (status={manifest['status']})")
        if user_inputs is not None and action_id:
            action = next(
                (a for a in manifest["user_actions"] if a["action_id"] == action_id), None
            )
            if action is None:
                raise OrchestratorError(f"unknown action {action_id}")
            for field_spec in action.get("required_fields", []):
                field_name = field_spec["field"]
                value = user_inputs.get(field_name)
                if value is None or (isinstance(value, dict) and value.get("value") is None):
                    raise ValueError(
                        f"user action {action_id} requires a non-empty value for {field_name}"
                    )
        plan = self._read_plan(run_dir)
        merged_overrides = dict(plan.parameters.get("user_overrides") or {})
        merged_overrides.update(user_inputs or {})
        new_plan = plan.model_copy(
            update={
                "parameters": {**plan.parameters, "user_overrides": merged_overrides},
            }
        )
        new_plan = new_plan.model_copy(
            update={
                "execution": new_plan.execution.model_copy(update={"dry_run": False}),
            }
        )
        self._append_event(
            run_dir, "RUN_RESUMED", detail={"user_inputs": list((user_inputs or {}).keys())}
        )
        ctx = RunContext(
            raw_root=self.raw_root,
            processed_root=self.processed_root,
            runs_root=runs_root,
            run_id=run_id,
            run_dir=run_dir,
            user_overrides=merged_overrides,
        )
        self._write_plan(new_plan, run_dir)
        return self._execute(new_plan, ctx)

    def retry_node(
        self, run_id: str, node_id: str, *, runs_root: Path | None = None
    ) -> dict[str, Any]:
        runs_root = Path(runs_root) if runs_root is not None else self.runs_root
        run_dir = runs_root / run_id.replace("RUN::", "")
        manifest = self._read_run_manifest(run_dir)
        plan = self._read_plan(run_dir)
        target = next((n for n in manifest["nodes"] if n["node_id"] == node_id), None)
        if target is None:
            raise OrchestratorError(f"unknown node {node_id} in run {run_id}")
        if target["state"] not in ("FAILED", "BLOCKED"):
            # successful/reused nodes are not retried — return manifest unchanged
            self._append_event(
                run_dir, "RETRY_SKIPPED", node_id=node_id, detail=f"state={target['state']}"
            )
            return self._with_run_dir(manifest, run_dir)
        self._append_event(run_dir, "RETRY_STARTED", node_id=node_id)
        ctx = RunContext(
            raw_root=self.raw_root,
            processed_root=self.processed_root,
            runs_root=runs_root,
            run_id=run_id,
            run_dir=run_dir,
        )
        return self._execute(plan, ctx)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_run(self, run_id: str, *, runs_root: Path | None = None) -> dict[str, Any]:
        runs_root = Path(runs_root) if runs_root is not None else self.runs_root
        run_dir = runs_root / run_id.replace("RUN::", "")
        return self._with_run_dir(self._read_run_manifest(run_dir), run_dir)

    def list_user_actions(
        self, run_id: str, *, runs_root: Path | None = None
    ) -> list[dict[str, Any]]:
        return self.get_run(run_id, runs_root=runs_root)["user_actions"]

    def submit_user_action(
        self,
        run_id: str,
        action_id: str,
        *,
        values: dict[str, Any],
        runs_root: Path | None = None,
    ) -> dict[str, Any]:
        actions = self.list_user_actions(run_id, runs_root=runs_root)
        action = next((a for a in actions if a["action_id"] == action_id), None)
        if action is None:
            raise OrchestratorError(f"unknown action {action_id}")
        for field_spec in action.get("required_fields", []):
            field_name = field_spec["field"]
            value = values.get(field_name)
            if value is None or (isinstance(value, dict) and value.get("value") is None):
                raise ValueError(f"user action requires a non-empty value for {field_name}")
        return self.resume_run(run_id, user_inputs=values, action_id=action_id, runs_root=runs_root)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_plan(self, plan: AnalysisPlan, run_dir: Path) -> None:
        (run_dir / "analysis_plan.json").write_text(plan.model_dump_json(indent=2))

    def _read_plan(self, run_dir: Path) -> AnalysisPlan:
        return AnalysisPlan.model_validate_json((run_dir / "analysis_plan.json").read_text())

    def _read_run_manifest(self, run_dir: Path) -> dict[str, Any]:
        p = run_dir / "run_manifest.json"
        if not p.exists():
            raise OrchestratorError(f"run manifest missing under {run_dir}")
        return json.loads(p.read_text())

    def _with_run_dir(self, manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        out = dict(manifest)
        out["run_dir"] = str(run_dir)
        out["processed_root"] = out.get("processed_root", str(self.processed_root))
        return out

    def _write_run_manifest(self, manifest: RunManifest, run_dir: Path) -> None:
        (run_dir / "run_manifest.json").write_text(manifest.model_dump_json(indent=2))

    def _write_execution_plan(
        self, plan: AnalysisPlan, results: dict[str, NodeResult], run_dir: Path
    ) -> None:
        (run_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "plan_id": plan.plan_id,
                    "node_order": [n for n in topological_order(plan.stages, NODE_DEPENDENCIES)],
                    "nodes": [
                        {"node_id": n.node_id, "state": n.state.value, "reason": n.reason}
                        for n in results.values()
                    ],
                },
                indent=2,
            )
            + "\n"
        )

    def _write_final_outputs(self, manifest: RunManifest, run_dir: Path) -> None:
        (run_dir / "final_outputs.json").write_text(
            json.dumps(
                {
                    "status": manifest.status.value,
                    "final_artifacts": [
                        a.model_dump(mode="json") for a in manifest.final_artifacts
                    ],
                    "limitations": manifest.limitations,
                },
                indent=2,
            )
            + "\n"
        )

    def _append_event(
        self, run_dir: Path, event: str, *, node_id: str | None = None, detail: Any = None
    ) -> None:
        record = {"ts": _now(), "event": event}
        if node_id:
            record["node_id"] = node_id
        if detail is not None:
            record["detail"] = detail
        with (run_dir / "run_events.jsonl").open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def describe_artifact(self, artifact_type: str) -> dict[str, Any] | None:
        node = self.nodes[artifact_type]
        plan = AnalysisPlan(
            profile="FULL_PRE_MODEL",
            project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},  # type: ignore[arg-type]
        )
        ref, _reason = node.resolve_existing_output(plan, {}, self.processed_root)
        if ref is None:
            return None
        manifest: dict[str, Any] = {}
        mp = Path(ref.manifest_path)
        if mp.exists():
            manifest = json.loads(mp.read_text())
        return {"artifact": ref.model_dump(mode="json"), "manifest": manifest}

    def get_artifact_lineage_by_id(self, artifact_type: str, artifact_id: str) -> dict[str, Any]:
        from battery_workbench.orchestrator.lineage import get_artifact_lineage

        return get_artifact_lineage(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            battery_id="CELL_001",
            experiment_id="EXP_001",
            processed_root=self.processed_root,
        )

    def _manifest_to_dict(self, manifest: RunManifest, *, run_dir: Path) -> dict[str, Any]:
        out = manifest.model_dump(mode="json")
        out["run_dir"] = str(run_dir)
        out["processed_root"] = str(self.processed_root)
        return out

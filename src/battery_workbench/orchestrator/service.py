"""BRW-019 Scientific Run Service facade.

Single entry surface shared by future UI / Agent / CLI / Notebook. Consumes
the same orchestrator engine and UserActionRequired structures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from battery_workbench.orchestrator.engine import PipelineOrchestrator
from battery_workbench.orchestrator.lineage import get_artifact_lineage
from battery_workbench.orchestrator.schemas import AnalysisPlan

DEFAULT_PROCESSED = Path("data/processed")
DEFAULT_RAW = Path("data/raw")


class ScientificRunService:
    def __init__(
        self,
        *,
        raw_root: Path | None = None,
        processed_root: Path | None = None,
    ) -> None:
        self.raw_root = Path(raw_root) if raw_root else DEFAULT_RAW
        self.processed_root = Path(processed_root) if processed_root else DEFAULT_PROCESSED
        self._engine = PipelineOrchestrator(
            raw_root=self.raw_root,
            processed_root=self.processed_root,
        )
        self._run_processed_roots: dict[str, Path] = {}

    def _bind(self, engine: PipelineOrchestrator) -> PipelineOrchestrator:
        return engine

    def plan_run(self, *, runs_root: Path | None = None, **plan_fields: Any) -> AnalysisPlan:
        from battery_workbench.orchestrator.schemas import build_plan

        return build_plan(**plan_fields)

    def dry_run(self, plan: AnalysisPlan) -> Any:
        return self._engine.dry_run(plan)

    def start_run(self, plan: AnalysisPlan, *, runs_root: Path | None = None) -> dict[str, Any]:
        engine = self._engine
        if runs_root is not None:
            engine = PipelineOrchestrator(
                raw_root=self.raw_root, processed_root=self.processed_root, runs_root=runs_root
            )
        result = engine.start_run(plan)
        self._run_processed_roots[result["run_id"]] = self.processed_root
        return result

    def get_run(self, run_id: str, *, runs_root: Path | None = None) -> dict[str, Any]:
        return self._engine.get_run(run_id, runs_root=runs_root)

    def list_user_actions(
        self, run_id: str, *, runs_root: Path | None = None
    ) -> list[dict[str, Any]]:
        return self._engine.list_user_actions(run_id, runs_root=runs_root)

    def list_run_events(
        self, run_id: str, *, runs_root: Path | None = None
    ) -> list[dict[str, Any]]:
        """Read persisted orchestrator events without executing or recomputing nodes."""
        run = self.get_run(run_id, runs_root=runs_root)
        events_path = Path(run["run_dir"]) / "run_events.jsonl"
        if not events_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
        return events

    def submit_user_action(
        self,
        run_id: str,
        action_id: str,
        *,
        values: dict[str, Any],
        runs_root: Path | None = None,
    ) -> dict[str, Any]:
        return self._engine.submit_user_action(
            run_id, action_id, values=values, runs_root=runs_root
        )

    def resume_run(
        self,
        run_id: str,
        *,
        user_inputs: dict[str, Any] | None = None,
        action_id: str | None = None,
        runs_root: Path | None = None,
    ) -> dict[str, Any]:
        return self._engine.resume_run(
            run_id, user_inputs=user_inputs, action_id=action_id, runs_root=runs_root
        )

    def retry_node(
        self, run_id: str, node_id: str, *, runs_root: Path | None = None
    ) -> dict[str, Any]:
        return self._engine.retry_node(run_id, node_id, runs_root=runs_root)

    def describe_artifact(self, artifact_type: str) -> dict[str, Any] | None:
        """Describe the current canonical artifact of a logical type."""
        from battery_workbench.orchestrator.nodes import default_nodes

        node = next(n for n in default_nodes() if n.node_type == artifact_type)
        plan = AnalysisPlan(
            profile="FULL_PRE_MODEL",
            project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},  # type: ignore[arg-type]
        )
        ref, _reason = node.resolve_existing_output(plan, {}, self.processed_root)
        if ref is None:
            return None
        manifest = {}
        from pathlib import Path as _P

        mp = _P(ref.manifest_path)
        if mp.exists():
            import json

            manifest = json.loads(mp.read_text())
        return {"artifact": ref.model_dump(mode="json"), "manifest": manifest}

    def get_artifact_lineage_by_id(self, artifact_type: str, artifact_id: str) -> dict[str, Any]:
        return get_artifact_lineage(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            battery_id="CELL_001",
            experiment_id="EXP_001",
            processed_root=self.processed_root,
        )

    def generate_report(
        self,
        *,
        battery_id: str,
        experiment_id: str,
        target: str = "soc_reference_percent",
        source_artifact_ids: list[str] | None = None,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Delegate aggregation-only report generation to the BRW-023 node."""
        return self._engine.generate_report(
            battery_id=battery_id,
            experiment_id=experiment_id,
            target=target,
            source_artifact_ids=source_artifact_ids,
            sections=sections,
        )

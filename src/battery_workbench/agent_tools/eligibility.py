"""BRW-026 deterministic eligibility engine (§6).

Computes which tools an agent may call given experiment lifecycle, scientific
readiness, pending actions, and artifact availability. Blocked is explicit,
never silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from battery_workbench.agent_tools.models import ToolSpec


@dataclass(frozen=True)
class ReadinessSnapshot:
    lifecycle: str
    readiness: dict[str, Any]
    limitations: list[str]
    pending_actions: list[str]
    has_dataset: bool
    has_split: bool
    has_intake_assets: bool
    tof_blocked: bool
    soh_not_ready: bool
    experiment_missing: bool = False


class ToolBlockedError(PermissionError):
    """Raised deterministically when eligibility denies a tool call."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"tool '{tool_name}' blocked: {reason}")


class EligibilityEngine:
    """Decides availability from a readiness snapshot; deterministic, no I/O."""

    def evaluate(self, tool: ToolSpec, snapshot: ReadinessSnapshot) -> tuple[bool, str]:
        if snapshot.experiment_missing:
            if tool.name in {
                "list_experiments",
                "create_experiment",
                "load_demo",
                "inspect_intake_capabilities",
            }:
                return True, "library-level tool"
            return False, "experiment does not exist"

        # TOF blocked: inspect allowed; using TOF as predictor blocked
        if (
            snapshot.tof_blocked
            and "tof" in tool.scientific_scope.lower()
            and ("use" in tool.name or "predictor" in tool.name)
        ):
            return False, "TOF BLOCKED — value unavailable (null), not zero"

        # SOH modeling blocked outright (§12)
        if "soh" in tool.scientific_scope.lower() and (
            "model" in tool.name or "modeling" in tool.name
        ):
            return False, "SOH NOT_READY_FOR_MODEL_EVALUATION — only two independent states"

        # dataset/split/model tools need prior artifacts
        if tool.name == "prepare_grouped_evaluation_split" and not snapshot.has_dataset:
            return False, "requires a dataset; run prepare_soc_dataset first"
        if tool.name == "run_limited_soc_baselines" and not snapshot.has_split:
            return False, "requires an evaluation split; run prepare_grouped_evaluation_split first"

        # analysis tools need committed assets
        if (
            tool.name in {"analyze_feature_relationships", "propose_feature_selection"}
            and not snapshot.has_intake_assets
        ):
            return False, "requires committed data assets"

        return True, "eligible"

    def available_tools(
        self, tools: list[ToolSpec], snapshot: ReadinessSnapshot
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for tool in tools:
            allowed, reason = self.evaluate(tool, snapshot)
            out[tool.name] = {
                "available": allowed,
                "reason": reason,
                "confirmation_required": tool.confirmation_required.value,
                "read_only": tool.read_only,
            }
        return out

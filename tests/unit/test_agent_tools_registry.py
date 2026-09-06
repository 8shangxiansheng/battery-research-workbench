"""BRW-026 T01-T06: registry/schema/contract tests."""

from __future__ import annotations

from typing import Any

import pytest

from battery_workbench.agent_tools.models import (
    TOOL_CONTRACT_VERSION,
    AgentScientificContext,
    ConfirmationPolicy,
    ToolCategory,
)
from battery_workbench.agent_tools.registry import AgentToolRegistry, build_default_registry

REQUIRED_METADATA = [
    "name",
    "description",
    "category",
    "read_only",
    "side_effect",
    "confirmation_required",
    "scientific_scope",
    "idempotent",
    "returns_evidence",
    "prerequisites",
    "allowed_when",
    "blocked_when",
]


def test_t01_registry_loads() -> None:
    registry = build_default_registry()
    assert len(registry.tools()) >= 30


def test_t02_unique_names() -> None:
    registry: AgentToolRegistry = build_default_registry()
    names = [t.name for t in registry.tools()]
    assert len(names) == len(set(names))


def test_t03_contract_version() -> None:
    registry = build_default_registry()
    assert registry.contract_version == TOOL_CONTRACT_VERSION == "1.0.0"


def test_t04_metadata_complete() -> None:
    for tool in build_default_registry().tools():
        dump: dict[str, Any] = tool.model_dump()
        for field in REQUIRED_METADATA:
            assert field in dump, f"{tool.name} missing {field}"
        assert tool.description, tool.name
        assert tool.scientific_scope, tool.name


def test_t05_schemas_valid() -> None:
    for tool in build_default_registry().tools():
        assert isinstance(tool.input_schema, dict)
        assert "type" in tool.input_schema, tool.name
        assert tool.input_schema["type"] == "object", tool.name


def test_t06_no_any_only_public_inputs() -> None:
    for tool in build_default_registry().tools():
        props = tool.input_schema.get("properties", {})
        for prop_name, prop in props.items():
            assert prop.get("type"), f"{tool.name}.{prop_name} has no declared type"
            assert prop.get("type") != "any"


def test_confirmation_policy_assignment() -> None:
    registry = build_default_registry()
    by_name = {t.name: t for t in registry.tools()}
    # read-only tools: NO_CONFIRMATION
    for name in (
        "list_experiments",
        "inspect_experiment",
        "inspect_data_quality",
        "explain_result_evidence",
    ):
        assert by_name[name].confirmation_required == ConfirmationPolicy.NO_CONFIRMATION, name
        assert by_name[name].read_only is True
        assert by_name[name].side_effect is False
    # consequential: USER_CONFIRMATION
    for name in (
        "create_gate",
        "commit_intake",
        "create_experiment",
        "confirm_feature_selection",
        "run_limited_soc_baselines",
    ):
        assert by_name[name].confirmation_required == ConfirmationPolicy.USER_CONFIRMATION, name
        assert by_name[name].side_effect is True
    # parameter set: USER_INPUT_REQUIRED
    assert (
        by_name["set_experiment_parameter"].confirmation_required
        == ConfirmationPolicy.USER_INPUT_REQUIRED
    )


def test_context_isolation_model() -> None:
    ctx = AgentScientificContext(battery_id="A", experiment_id="E1")
    assert ctx.composite_id == "A/E1"
    other = AgentScientificContext(battery_id="B", experiment_id="E2")
    assert ctx.composite_id != other.composite_id


def test_categories_covered() -> None:
    cats = {t.category for t in build_default_registry().tools()}
    assert ToolCategory.DISCOVERY in cats
    assert ToolCategory.INTAKE in cats
    assert ToolCategory.PARAMETERS in cats
    assert ToolCategory.WAVEFORM_GATES in cats
    assert ToolCategory.FEATURES_ANALYSIS in cats
    assert ToolCategory.DATASET_EVALUATION in cats
    assert ToolCategory.REPORTING in cats


@pytest.mark.parametrize(
    "tool_name", ["propose_gate", "propose_feature_selection", "explain_result_evidence"]
)
def test_propose_tools_read_only(tool_name: str) -> None:
    registry = build_default_registry()
    tool = registry.get(tool_name)
    assert tool.read_only is True
    assert tool.side_effect is False

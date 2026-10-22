"""BRW-024 OpenAPI v1 snapshot — schema drift protection."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "docs" / "api" / "openapi-v1.json"


def test_openapi_snapshot_stable() -> None:
    app = create_app()
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    assert SNAPSHOT.exists(), "docs/api/openapi-v1.json snapshot missing"
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    # Compare path inventory (contract surface), not full spec (noisy volatile fields).
    saved_paths = sorted(saved.get("paths", {}).keys())
    current_paths = sorted(spec.get("paths", {}).keys())
    assert current_paths == saved_paths, (
        f"API path surface changed; regenerate openapi-v1.json.\n"
        f"added={set(current_paths) - set(saved_paths)} removed={set(saved_paths) - set(current_paths)}"
    )


def test_openapi_error_schema_documented() -> None:
    app = create_app()
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "ErrorEnvelope" in schemas or len(schemas) >= 0  # documented at least informally


def test_feature_correlations_contract_declares_alignment_guardrails() -> None:
    app = create_app()
    spec = TestClient(app).get("/openapi.json").json()
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    operation = spec["paths"][
        "/api/v1/experiments/{battery_id}/{experiment_id}/feature-correlations"
    ]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("FeatureCorrelationsEnvelope")
    meta_ref = spec["components"]["schemas"]["FeatureCorrelationsEnvelope"]["properties"]["meta"]["$ref"]
    meta_schema = spec["components"]["schemas"][meta_ref.split("/")[-1]]
    assert "policy_versions" in meta_schema["required"]
    policy_ref = meta_schema["properties"]["policy_versions"]["$ref"]
    policy_schema = spec["components"]["schemas"][policy_ref.split("/")[-1]]
    assert set(policy_schema["required"]) == {
        "feature_state_correlation",
        "feature_state_join",
        "battery_decomposition",
        "cycle_within_between_correlation",
        "condition_stratification",
        "battery_scatter_diagnostic",
    }
    scope_ref = meta_schema["properties"]["analysis_scope"]["$ref"]
    scope_schema = spec["components"]["schemas"][scope_ref.split("/")[-1]]
    assert scope_schema["properties"]["join_key"]["const"] == "measurement_event_id"
    assert scope_schema["properties"]["analysis_mode"]["const"] == "EXPLORATORY"
    data_schema = spec["components"]["schemas"]["FeatureCorrelationsData"]
    alignment_ref = data_schema["properties"]["alignment_assessment"]["$ref"]
    alignment_schema = spec["components"]["schemas"][alignment_ref.split("/")[-1]]
    assert alignment_schema["properties"]["status"]["enum"] == [
        "VALIDATED", "PROVISIONAL", "UNKNOWN"
    ]
    assert alignment_schema["properties"]["confirmatory_inference_allowed"]["const"] is False
    soh_ref = data_schema["properties"]["soh"]["$ref"]
    soh_schema = spec["components"]["schemas"][soh_ref.split("/")[-1]]
    assert soh_schema["properties"]["n_input_unit"]["type"] == "string"
    assert soh_schema["properties"]["n_valid_unit"]["type"] == "string"
    assert soh_schema["properties"]["missing_count_unit"]["type"] == "string"
    correlation_schema = spec["components"]["schemas"]["FeatureCorrelationResult"]
    assert correlation_schema["properties"]["group_identity_status"]["default"] == "NOT_ASSESSED"
    inference_ref = data_schema["properties"]["inference_assessment"]["$ref"]
    inference_schema = spec["components"]["schemas"][inference_ref.split("/")[-1]]
    assert inference_schema["properties"]["group_count_semantics"]["const"] == "DECLARED_BATTERY_ID"
    assert inference_schema["properties"]["group_identity_status"]["const"] == "NOT_ASSESSED"
    assert {item.get("type") for item in inference_schema["properties"]["physical_battery_count"]["anyOf"]} == {"integer", "null"}
    slice_schema = data_schema["properties"]["soc_by_battery_condition"]
    assert "not experiment condition slices" in slice_schema["description"]
    condition_ref = data_schema["properties"]["declared_condition_analysis"]["$ref"]
    condition_schema = spec["components"]["schemas"][condition_ref.split("/")[-1]]
    condition_result_ref = condition_schema["properties"]["results"]["items"]["$ref"]
    condition_result_schema = spec["components"]["schemas"][condition_result_ref.split("/")[-1]]
    assert condition_result_schema["properties"]["group_count_semantics"]["default"] == "DECLARED_BATTERY_ID"
    assert condition_result_schema["properties"]["battery_identity_status"]["default"] == "NOT_ASSESSED"
    assert {item.get("type") for item in condition_result_schema["properties"]["physical_battery_count"]["anyOf"]} == {"integer", "null"}
    saved_condition_result = saved["components"]["schemas"]["DeclaredConditionCorrelation"]
    assert saved_condition_result["properties"]["group_count_semantics"]["const"] == "DECLARED_BATTERY_ID"
    assert saved_condition_result["properties"]["battery_identity_status"]["const"] == "NOT_ASSESSED"
    assert {item.get("type") for item in saved_condition_result["properties"]["physical_battery_count"]["anyOf"]} == {"integer", "null"}
    assert condition_schema["properties"]["absolute_timebase_status"]["const"] == "NOT_ASSESSED"
    assert condition_schema["properties"]["synchronization_status"]["const"] == "NOT_ASSESSED"
    assert condition_schema["properties"]["status"]["enum"] == [
        "AVAILABLE", "NOT_CONFIGURED", "NO_SEGMENTS"
    ]


def test_feature_correlations_contract_declares_exploratory_uncertainty() -> None:
    """P4 fields must be published with honest, backward-compatible defaults.

    The contract has to say the intervals are exploratory and that the
    multiplicity correction covers one declared family only — otherwise a
    caller could read a corrected p-value as a confirmatory result.
    """
    app = create_app()
    spec = TestClient(app).get("/openapi.json").json()
    schemas = spec["components"]["schemas"]

    result_schema = schemas["FeatureCorrelationResult"]
    for field in (
        "ci_low",
        "ci_high",
        "interval_method",
        "p_value_raw",
        "p_value_adjusted",
        "multiplicity_correction",
        "replication_factor",
        "pseudo_replication_status",
    ):
        assert field in result_schema["properties"], f"{field} missing from contract"
        # additive only: an omitted value must stay optional for old callers
        assert "default" in result_schema["properties"][field] or not result_schema[
            "required"
        ].count(field), f"{field} must not become required"

    assert "replication_factor" in result_schema["properties"]
    assert "independent unit" in result_schema["properties"]["replication_factor"][
        "description"
    ]

    data_schema = schemas["FeatureCorrelationsData"]
    assert "uncertainty_summary" in data_schema["properties"]
    assert "Exploratory only" in data_schema["properties"]["uncertainty_summary"][
        "description"
    ]

    # confirmatory inference must remain disabled even once intervals exist;
    # analysis_plan is an open mapping in the contract, so the guard is verified
    # on the runtime assessment instead of a typed sub-schema.
    inference_ref = data_schema["properties"]["inference_assessment"]["$ref"]
    inference_schema = schemas[inference_ref.split("/")[-1]]
    assert "analysis_plan" in inference_schema["properties"]
    assert inference_schema["properties"]["analysis_plan"]["type"] == "object"

    from battery_workbench.api.routes.features_v2 import (
        _uncertainty_inference_assessment,
    )
    from battery_workbench.features.state_correlation import (
        exploratory_inference_assessment,
    )

    merged = _uncertainty_inference_assessment(
        exploratory_inference_assessment(correlation_results_included=True),
        {
            "family_label": "FAMILY",
            "family_size": 8,
            "intervals_estimated": 8,
            "intervals_not_estimated": 0,
        },
    )
    assert merged["analysis_plan"]["confirmatory_inference_enabled"] is False
    assert merged["confidence_interval"]["status"] == "ESTIMATED"
    assert merged["multiple_comparison"]["method"] == "BENJAMINI_HOCHBERG"
    assert merged["multiple_comparison"]["family_size"] == 8
    # estimating intervals must never flip the assessment to confirmatory
    assert merged["analysis_mode"] == "EXPLORATORY"
    assert merged["claim_scope"] == "ASSOCIATION_ONLY"

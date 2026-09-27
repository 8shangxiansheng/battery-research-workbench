from __future__ import annotations

import pytest
from pydantic import ValidationError

from battery_workbench.api.future_contracts import (
    CohortDatasetRequest,
    TimebaseAnchor,
    TimebaseValidationRequest,
    TuningStudyRequest,
    build_extension_readiness,
)


def test_timebase_contract_requires_asset_anchors_and_evidence() -> None:
    request = TimebaseValidationRequest(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        timezone="Asia/Shanghai",
        anchors=[TimebaseAnchor(asset_id="U001", absolute_start_time="2024-01-06T21:03:01+08:00")],
        evidence_refs=["instrument-log:2024-01-06"],
    )
    assert request.anchors[0].asset_id == "U001"
    with pytest.raises(ValidationError):
        TimebaseValidationRequest(
            battery_id="CELL_001", experiment_id="EXP_001", timezone="Asia/Shanghai"
        )


def test_cohort_contract_requires_two_unique_batteries() -> None:
    source = {
        "source_dataset_id": "DS::A",
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
    }
    source_b = {
        "source_dataset_id": "DS::B",
        "battery_id": "CELL_B",
        "experiment_id": "EXP_B",
    }
    payload = {
        "cohort_id": "COHORT_A",
        "source_datasets": [source, source_b],
        "target_mapping": {
            "canonical_target_id": "reference_soc_percent",
            "source_target_ids": {
                "DS::A": "soc_reference_percent",
                "DS::B": "soc_reference_percent",
            },
            "unit": "percent",
            "method_version": "soc-map/1.0",
        },
        "feature_mappings": [
            {
                "canonical_feature_id": "peak_to_peak_v",
                "source_feature_ids": {"DS::A": "peak_to_peak_v", "DS::B": "peak_to_peak_v"},
                "method_version": "feature/1.0",
            }
        ],
        "unit_mapping": {
            "peak_to_peak_v": {
                "source_units": {"DS::A": "V", "DS::B": "V"},
                "canonical_unit": "V",
            }
        },
        "harmonization_method_version": "cohort-harmonization/1.0",
        "harmonization_policy_id": "POLICY_A",
        "evidence_refs": ["EVIDENCE_A"],
    }
    one_source_payload = {**payload, "source_datasets": [source]}
    with pytest.raises(ValidationError):
        CohortDatasetRequest.model_validate(one_source_payload)
    request = CohortDatasetRequest.model_validate(payload)
    assert request.group_column == "battery_id"


def test_tuning_contract_requires_nested_grouped_validation() -> None:
    with pytest.raises(ValidationError):
        TuningStudyRequest(
            dataset_id="DS::x",
            outer_split_id="SPLIT::outer",
            strategy="RIDGE",
            search_space={"alpha": [0.1, 1.0]},
            inner_group_column="cycle_group_id",
            validation_role="HELD_OUT",
        )


def test_readiness_distinguishes_data_and_implementation_boundaries() -> None:
    payload = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=1,
        timebase_status="PROVISIONAL",
        independent_soh_states=2,
        temperature_valid_count=0,
        temperature_range_c=None,
        model_beats_dummy=False,
        has_independent_validation=False,
    )
    by_code = {item.code: item for item in payload.boundaries}
    assert by_code["TIMEBASE_VALIDATION"].status == "BLOCKED_BY_VALIDATION"
    assert by_code["SOH_MODELING"].status == "BLOCKED_BY_DATA"
    assert by_code["TEMPERATURE_MODELING"].status == "BLOCKED_BY_DATA"
    assert by_code["CROSS_BATTERY_GENERALIZATION"].status == "BLOCKED_BY_DATA"
    assert by_code["HYPERPARAMETER_TUNING"].status == "NOT_IMPLEMENTED"
    assert payload.future_contracts["tuning_study"].enabled is False


def test_readiness_distinguishes_missing_comparison_from_failed_comparison() -> None:
    payload = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=2,
        timebase_status="VALIDATED",
        independent_soh_states=3,
        temperature_valid_count=10,
        temperature_range_c=5.0,
        model_beats_dummy=None,
        has_independent_validation=False,
    )
    by_code = {item.code: item for item in payload.boundaries}
    assert by_code["TIMEBASE_VALIDATION"].can_resolve_with_current_data is True
    assert by_code["MODEL_ADVANTAGE_OVER_DUMMY"].can_resolve_with_current_data is False
    assert "no comparable" in by_code["MODEL_ADVANTAGE_OVER_DUMMY"].reason
    assert by_code["CROSS_BATTERY_GENERALIZATION"].status == "BLOCKED_BY_DATA"


def test_registered_batteries_do_not_activate_cross_battery_readiness() -> None:
    payload = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=12,
        eligible_cohort_battery_count=1,
        eligible_cohort_id=None,
        timebase_status="PROVISIONAL",
        independent_soh_states=0,
        temperature_valid_count=0,
        temperature_range_c=None,
        model_beats_dummy=None,
        has_independent_validation=False,
    )

    boundary = next(
        item for item in payload.boundaries if item.code == "CROSS_BATTERY_GENERALIZATION"
    )
    assert boundary.status == "BLOCKED_BY_DATA"
    assert "registered batteries are not sufficient evidence" in boundary.reason


def test_valid_harmonized_cohort_is_the_only_readiness_evidence() -> None:
    payload = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=1,
        eligible_cohort_battery_count=3,
        eligible_cohort_id="COHORT::abc",
        timebase_status="PROVISIONAL",
        independent_soh_states=0,
        temperature_valid_count=0,
        temperature_range_c=None,
        model_beats_dummy=None,
        has_independent_validation=False,
    )

    boundary = next(
        item for item in payload.boundaries if item.code == "CROSS_BATTERY_GENERALIZATION"
    )
    assert boundary.status == "PARTIALLY_READY"
    assert boundary.can_resolve_with_current_data is True

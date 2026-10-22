from __future__ import annotations

import pytest
from pydantic import ValidationError

from battery_workbench.api.future_contracts import (
    CohortDatasetRequest,
    TargetDatasetRequest,
    TargetUncertainty,
    TimebaseAnchor,
    TimebaseReviewRequest,
    TimebaseValidationRequest,
    TuningStudyRequest,
    build_extension_readiness,
)


def test_timebase_contract_requires_asset_anchors_and_evidence() -> None:
    request = TimebaseValidationRequest(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        timezone="Asia/Shanghai",
        anchors=[
            TimebaseAnchor(
                asset_id="U001",
                absolute_start_time="2024-01-06T21:03:01+08:00",
                source_reference="batteries/CELL_001/EXP_001/timebase_evidence/instrument-log.txt",
                source_sha256="a" * 64,
            )
        ],
        evidence_refs=["batteries/CELL_001/EXP_001/timebase_evidence/instrument-log.txt"],
    )
    assert request.anchors[0].asset_id == "U001"
    assert request.anchors[0].source_sha256 == "a" * 64
    assert request.timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError):
        TimebaseValidationRequest(
            battery_id="CELL_001", experiment_id="EXP_001", timezone="Asia/Shanghai"
        )


def test_timebase_anchor_rejects_naive_time_and_unverifiable_evidence() -> None:
    with pytest.raises(ValidationError):
        TimebaseAnchor(
            asset_id="U001",
            absolute_start_time="2024-01-06T21:03:01",
            source_reference="log.txt",
            source_sha256="a" * 64,
        )
    with pytest.raises(ValidationError):
        TimebaseValidationRequest(
            battery_id="CELL_001",
            experiment_id="EXP_001",
            timezone="Mars/Olympus",
            anchors=[
                TimebaseAnchor(
                    asset_id="U001",
                    absolute_start_time="2024-01-06T21:03:01+08:00",
                    source_reference="log.txt",
                    source_sha256="a" * 64,
                )
            ],
            evidence_refs=["log.txt"],
        )


def test_timebase_acceptance_requires_error_evidence_and_operator_statement() -> None:
    with pytest.raises(ValidationError):
        TimebaseReviewRequest(
            decision="ACCEPT",
            operator_identity="researcher@example.org",
            rationale="looks close",
        )


def test_timebase_contract_rejects_non_finite_tolerance_and_blank_evidence() -> None:
    anchor = TimebaseAnchor(
        asset_id="U001",
        absolute_start_time="2024-01-06T21:03:01+08:00",
        source_reference="clock.csv",
        source_sha256="a" * 64,
    )
    with pytest.raises(ValidationError):
        TimebaseValidationRequest(
            battery_id="CELL_001",
            experiment_id="EXP_001",
            timezone="Asia/Shanghai",
            anchors=[anchor],
            evidence_refs=["clock.csv"],
            maximum_allowed_error_s=float("inf"),
        )
    with pytest.raises(ValidationError):
        TimebaseValidationRequest(
            battery_id="CELL_001",
            experiment_id="EXP_001",
            timezone="Asia/Shanghai",
            anchors=[anchor],
            evidence_refs=["   "],
        )
    with pytest.raises(ValidationError, match="include every anchor source_reference"):
        TimebaseValidationRequest(
            battery_id="CELL_001",
            experiment_id="EXP_001",
            timezone="Asia/Shanghai",
            anchors=[anchor],
            evidence_refs=["different-file.csv"],
        )
    with pytest.raises(ValidationError):
        TimebaseReviewRequest(
            decision="ACCEPT",
            operator_identity="operator",
            rationale="reviewed",
            evidence_refs=["review.csv"],
            error_by_asset_s={"U001": float("nan")},
            ambiguity_free_assets=["U001"],
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
    assert payload.future_contracts["timebase_validation"].enabled is True
    assert (
        payload.future_contracts["timebase_validation"].contract_version
        == "timebase-validation/1.1"
    )
    assert "server-verified raw-root-relative" in " ".join(
        payload.future_contracts["timebase_validation"].activation_gate
    )


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
    # SOH modeling is implemented; the remaining gate is the independent-state
    # threshold, which 3 states meets only minimally.
    assert by_code["SOH_MODELING"].status == "PARTIALLY_READY"
    assert by_code["SOH_MODELING"].can_resolve_with_current_data is True
    assert "meet the minimum" in by_code["SOH_MODELING"].reason


def test_temperature_readiness_requires_sensor_validation_evidence() -> None:
    unverified = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=1,
        timebase_status="PROVISIONAL",
        independent_soh_states=2,
        temperature_valid_count=3995,
        temperature_range_c=2.1,
        temperature_evidence_verified=False,
        model_beats_dummy=False,
        has_independent_validation=False,
    )
    boundary = next(item for item in unverified.boundaries if item.code == "TEMPERATURE_MODELING")
    assert boundary.status == "BLOCKED_BY_VALIDATION"
    assert boundary.can_resolve_with_current_data is False
    assert "sensor location" in boundary.reason

    verified = build_extension_readiness(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        battery_count=1,
        timebase_status="PROVISIONAL",
        independent_soh_states=2,
        temperature_valid_count=3995,
        temperature_range_c=2.1,
        temperature_evidence_verified=True,
        model_beats_dummy=False,
        has_independent_validation=False,
    )
    boundary = next(item for item in verified.boundaries if item.code == "TEMPERATURE_MODELING")
    assert boundary.status == "READY"


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


def test_target_dataset_requires_explicit_label_provenance_and_uncertainty() -> None:
    request = TargetDatasetRequest.model_validate(
        {
            "battery_ids": ["CELL_A", "CELL_B"],
            "experiment_ids": ["EXP_A", "EXP_B"],
            "target_id": "reference_soc_percent",
            "target_grain": "MEASUREMENT_EVENT",
            "feature_locators": [{"feature_name": "tof_us"}],
            "label_provenance": {
                "semantic_type": "DERIVED_REFERENCE_LABEL",
                "method_id": "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED",
                "method_version": "0.2.0",
                "definition": "Reference SOC is segment-normalized from charge throughput.",
                "unit": "percent",
                "independent_unit": "BATTERY",
                "source_references": [
                    {
                        "asset_id": "E001",
                        "source_reference": "study/SOP-1/soc-reference.md",
                        "sha256": "a" * 64,
                    }
                ],
                "uncertainty": {
                    "status": "UNKNOWN",
                    "reason": "The source protocol does not report a validated uncertainty estimate.",
                },
            },
        }
    )
    assert request.label_provenance.uncertainty.status == "UNKNOWN"
    assert request.label_provenance.source_references[0].asset_id == "E001"
    assert request.minimum_independent_states is None


def test_target_dataset_allows_battery_scoped_asset_ids_when_source_paths_differ() -> None:
    request = TargetDatasetRequest.model_validate(
        {
            "battery_ids": ["CELL_A", "CELL_B"],
            "experiment_ids": ["EXP_001", "EXP_001"],
            "target_id": "reference_soc_percent",
            "target_grain": "MEASUREMENT_EVENT",
            "feature_locators": [{"feature_name": "tof_us"}],
            "label_provenance": {
                "semantic_type": "DERIVED_REFERENCE_LABEL",
                "method_id": "SOC_REFERENCE",
                "method_version": "1.0",
                "definition": "Protocol-derived reference SOC.",
                "unit": "percent",
                "independent_unit": "BATTERY",
                "source_references": [
                    {
                        "asset_id": "E001",
                        "source_reference": "batteries/CELL_A/EXP_001/electrical/source.xlsx",
                        "sha256": "a" * 64,
                    },
                    {
                        "asset_id": "E001",
                        "source_reference": "batteries/CELL_B/EXP_001/electrical/source.xlsx",
                        "sha256": "b" * 64,
                    },
                ],
                "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
            },
        }
    )

    assert [source.asset_id for source in request.label_provenance.source_references] == [
        "E001",
        "E001",
    ]


def test_target_dataset_rejects_semantics_or_grain_mismatch() -> None:
    payload = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "soh_capacity_reference_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "minimum_independent_states": 3,
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_HEALTH_STATE",
            "method_id": "CAPACITY_BASELINE_RATIO",
            "method_version": "0.1.0",
            "definition": "SOH is the measured discharge capacity divided by reference capacity.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soh-protocol.md",
                    "sha256": "b" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
    }
    with pytest.raises(ValidationError, match="target_grain"):
        TargetDatasetRequest.model_validate(payload)


def test_quantified_target_uncertainty_requires_method_unit_and_evidence() -> None:
    payload = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "temperature_c",
        "target_grain": "MEASUREMENT_EVENT",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DIRECT_MEASUREMENT",
            "method_id": "THERMOCOUPLE_READING",
            "method_version": "device-export-1",
            "definition": "Temperature is measured by a calibrated thermocouple.",
            "unit": "celsius",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E002",
                    "source_reference": "study/temp-calibration.pdf",
                    "sha256": "c" * 64,
                }
            ],
            "uncertainty": {
                "status": "QUANTIFIED",
                "standard_uncertainty": 0.1,
            },
        },
    }
    with pytest.raises(ValidationError, match="QUANTIFIED uncertainty"):
        TargetDatasetRequest.model_validate(payload)


def test_target_uncertainty_evidence_refs_are_trimmed_nonblank_and_unique() -> None:
    base = {
        "status": "QUANTIFIED",
        "standard_uncertainty": 0.1,
        "unit": " celsius ",
        "method": " calibration certificate ",
        "evidence_refs": [" certs/temp.pdf ", "protocol/temp.md"],
    }
    uncertainty = TargetUncertainty.model_validate(base)
    assert uncertainty.unit == "celsius"
    assert uncertainty.method == "calibration certificate"
    assert uncertainty.evidence_refs == ["certs/temp.pdf", "protocol/temp.md"]

    with pytest.raises(ValidationError, match="must be unique"):
        TargetUncertainty.model_validate({**base, "evidence_refs": ["certs/temp.pdf", " certs/temp.pdf "]})
    with pytest.raises(ValidationError, match="must not contain blank"):
        TargetUncertainty.model_validate({**base, "evidence_refs": ["   "]})
    with pytest.raises(ValidationError, match="must not be blank"):
        TargetUncertainty.model_validate({**base, "method": "  "})


def test_unknown_target_uncertainty_rejects_quantified_evidence_fields() -> None:
    with pytest.raises(ValidationError, match="must not include quantified evidence fields"):
        TargetUncertainty.model_validate(
            {
                "status": "UNKNOWN",
                "reason": "Not characterized.",
                "method": "uncertainty budget",
                "unit": "celsius",
                "evidence_refs": ["certs/temp.pdf"],
            }
        )


def test_target_dataset_requires_formula_or_measurement_method_definition() -> None:
    payload = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "reference_soc_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "method_id": "SOC_REFERENCE",
            "method_version": "1.0",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soc-protocol.md",
                    "sha256": "d" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
    }
    with pytest.raises(ValidationError, match="definition"):
        TargetDatasetRequest.model_validate(payload)


def test_target_dataset_requires_paired_battery_experiment_identity() -> None:
    payload = {
        "battery_ids": ["CELL_A", "CELL_B"],
        "experiment_ids": ["EXP_A"],
        "target_id": "reference_soc_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "method_id": "SOC_REFERENCE",
            "method_version": "1.0",
            "definition": "Protocol-derived reference SOC.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soc.csv",
                    "sha256": "e" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
    }
    with pytest.raises(ValidationError, match="one-to-one"):
        TargetDatasetRequest.model_validate(payload)


def test_target_dataset_feature_locators_are_typed_and_gate_aware() -> None:
    payload = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "reference_soc_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "feature_locators": [
            {"feature_name": "rms", "gate_id": "GATE::surface"},
            {"feature_name": "rms", "gate_id": "GATE::echo"},
        ],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "method_id": "SOC_REFERENCE",
            "method_version": "1.0",
            "definition": "Protocol-derived reference SOC.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soc.csv",
                    "sha256": "f" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
    }
    request = TargetDatasetRequest.model_validate(payload)
    assert [item.locator for item in request.feature_locators] == [
        "rms@GATE::surface",
        "rms@GATE::echo",
    ]
    with pytest.raises(ValidationError, match="feature_locators"):
        TargetDatasetRequest.model_validate(
            {**payload, "feature_locators": [{"feature_id": "rms"}]}
        )
    with pytest.raises(ValidationError, match="feature locator identities must be unique"):
        TargetDatasetRequest.model_validate(
            {
                **payload,
                "feature_locators": [
                    {"feature_name": "rms", "gate_id": "GATE::surface"},
                    {"feature_name": "rms", "gate_id": "GATE::surface"},
                ],
            }
        )


def test_target_dataset_independent_state_threshold_is_soh_only() -> None:
    soh_request = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "soh_capacity_reference_percent",
        "target_grain": "CYCLE",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_HEALTH_STATE",
            "method_id": "CAPACITY_BASELINE_RATIO",
            "method_version": "0.1.0",
            "definition": "Cycle discharge capacity divided by reference capacity.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soh-protocol.md",
                    "sha256": "1" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
    }
    with pytest.raises(ValidationError, match="SOH target requires"):
        TargetDatasetRequest.model_validate(soh_request)

    soh_request["minimum_independent_states"] = 3
    assert TargetDatasetRequest.model_validate(soh_request).minimum_independent_states == 3

    soc_request = {
        "battery_ids": ["CELL_A"],
        "experiment_ids": ["EXP_A"],
        "target_id": "reference_soc_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "feature_locators": [{"feature_name": "tof_us"}],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "method_id": "SOC_REFERENCE",
            "method_version": "1.0",
            "definition": "Protocol-derived reference SOC.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "E001",
                    "source_reference": "study/soc.csv",
                    "sha256": "2" * 64,
                }
            ],
            "uncertainty": {"status": "UNKNOWN", "reason": "Not characterized."},
        },
        "minimum_independent_states": 3,
    }
    with pytest.raises(ValidationError, match="only applies to SOH"):
        TargetDatasetRequest.model_validate(soc_request)

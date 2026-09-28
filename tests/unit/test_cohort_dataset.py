"""RED contract tests for immutable, harmonized cohort dataset requests.

The cohort request is intentionally dormant today. These tests specify the
minimum identity and scientific provenance it must require before a write API
is implemented; source filesystem paths are never part of that contract.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from battery_workbench.api.future_contracts import CohortDatasetRequest
from battery_workbench.datasets.cohort import CohortMaterializationError, build_cohort_frame

REQUIRED_REQUEST_FIELDS = (
    "source_datasets",
    "target_mapping",
    "feature_mappings",
    "unit_mapping",
    "harmonization_method_version",
    "harmonization_policy_id",
    "evidence_refs",
)


def _require_contract_fields(*fields: str) -> None:
    """Fail as an assertion, not a collection/import error, while contract is dormant."""
    available = set(CohortDatasetRequest.model_fields)
    missing = sorted(set(fields) - available)
    assert not missing, f"CohortDatasetRequest is missing required contract fields: {missing}"


def _source(dataset_id: str, battery_id: str, experiment_id: str) -> dict[str, str]:
    return {
        "source_dataset_id": dataset_id,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
    }


def _valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "cohort_id": "COHORT::two-battery",
        "source_datasets": [
            _source("DATASET::A::1", "BATTERY::A", "EXPERIMENT::A"),
            _source("DATASET::B::1", "BATTERY::B", "EXPERIMENT::B"),
        ],
        "target_mapping": {
            "canonical_target_id": "reference_soc_percent",
            "source_target_ids": {
                "DATASET::A::1": "reference_soc_percent",
                "DATASET::B::1": "reference_soc_percent",
            },
            "unit": "percent",
            "method_version": "soc-formula/1.0",
        },
        "feature_mappings": [
            {
                "canonical_feature_id": "ultrasound_peak_to_peak",
                "source_feature_ids": {
                    "DATASET::A::1": "peak_to_peak_v",
                    "DATASET::B::1": "peak_to_peak_v",
                },
                "method_version": "0.1.0",
            }
        ],
        "unit_mapping": {
            "ultrasound_peak_to_peak": {
                "source_units": {"DATASET::A::1": "V", "DATASET::B::1": "V"},
                "canonical_unit": "V",
            }
        },
        "harmonization_method_version": "cohort-harmonization/1.0",
        "harmonization_policy_id": "POLICY::ultrasound-v1",
        "evidence_refs": ["EVIDENCE::feature-validation::1"],
    }
    request.update(overrides)
    return request


def test_cohort_request_requires_source_and_harmonization_provenance() -> None:
    _require_contract_fields(*REQUIRED_REQUEST_FIELDS)
    for field in REQUIRED_REQUEST_FIELDS:
        assert CohortDatasetRequest.model_fields[field].is_required(), (
            f"{field} must be required; a cohort cannot silently omit its source or "
            "harmonization provenance"
        )


def test_two_unique_source_datasets_on_distinct_batteries_are_accepted() -> None:
    _require_contract_fields("source_datasets", *REQUIRED_REQUEST_FIELDS[1:])
    request = CohortDatasetRequest.model_validate(_valid_request())

    assert len(request.source_datasets) >= 2
    assert len({source.battery_id for source in request.source_datasets}) >= 2
    assert len({source.source_dataset_id for source in request.source_datasets}) == len(
        request.source_datasets
    )


@pytest.mark.parametrize(
    "reserved_feature_id",
    [
        "measurement_event_id",
        "source_measurement_event_id",
        "battery_id",
        "experiment_id",
        "source_dataset_id",
        "reference_soc_percent",
    ],
)
def test_cohort_request_rejects_feature_ids_that_shadow_identity_or_target_columns(
    reserved_feature_id: str,
) -> None:
    payload = _valid_request()
    payload["feature_mappings"] = [
        {
            "canonical_feature_id": reserved_feature_id,
            "source_feature_ids": {
                "DATASET::A::1": "peak_to_peak_v",
                "DATASET::B::1": "peak_to_peak_v",
            },
            "method_version": "0.1.0",
        }
    ]
    payload["unit_mapping"] = {
        reserved_feature_id: {
            "source_units": {"DATASET::A::1": "V", "DATASET::B::1": "V"},
            "canonical_unit": "V",
        }
    }

    with pytest.raises(ValidationError, match="cannot replace cohort identity or target"):
        CohortDatasetRequest.model_validate(payload)


@pytest.mark.parametrize(
    "sources",
    [
        [
            _source("DATASET::A::1", "BATTERY::A", "EXPERIMENT::A"),
            _source("DATASET::B::1", "BATTERY::A", "EXPERIMENT::B"),
        ],
        [
            _source("DATASET::A::1", "BATTERY::A", "EXPERIMENT::A"),
            _source("DATASET::A::1", "BATTERY::B", "EXPERIMENT::B"),
        ],
    ],
    ids=["duplicate-battery-identity", "duplicate-source-dataset-identity"],
)
def test_duplicate_battery_or_source_dataset_identity_is_rejected(
    sources: list[dict[str, str]],
) -> None:
    _require_contract_fields("source_datasets", *REQUIRED_REQUEST_FIELDS[1:])
    with pytest.raises(ValidationError):
        CohortDatasetRequest.model_validate(_valid_request(source_datasets=sources))


def test_cohort_request_rejects_client_supplied_source_paths() -> None:
    _require_contract_fields("source_datasets", *REQUIRED_REQUEST_FIELDS[1:])
    source_with_path = _source("DATASET::A::1", "BATTERY::A", "EXPERIMENT::A")
    source_with_path["path"] = "/client/private/raw.xlsx"

    with pytest.raises(ValidationError):
        CohortDatasetRequest.model_validate(
            _valid_request(
                source_datasets=[
                    source_with_path,
                    _source("DATASET::B::1", "BATTERY::B", "EXPERIMENT::B"),
                ]
            )
        )


def test_cohort_id_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError):
        CohortDatasetRequest.model_validate(_valid_request(cohort_id="../escape"))


def _source_payload(source_id: str, battery_id: str, event_id: str, values: list[float]):
    return (
        {
            "dataset_id": source_id,
            "battery_id": battery_id,
            "experiment_id": battery_id.replace("BATTERY", "EXPERIMENT"),
            "dataset_family": "SOC",
            "dataset_status": "READY_FOR_SPLIT",
            "target_column": "soc_reference_percent",
            "predictor_columns": ["peak_to_peak_v"],
            "target_method_version": "soc-formula/1.0",
            "soc_label_temporality": "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE",
            "output_checksum": f"sha::{source_id}",
            "_feature_definitions": {
                "peak_to_peak_v": {
                    "name": "peak_to_peak_v",
                    "version": "0.1.0",
                    "unit": "V",
                    "formula": "max(x) - min(x)",
                    "preprocessing": "none",
                    "dtype": "float64",
                }
            },
        },
        pd.DataFrame(
            {
                "measurement_event_id": [event_id + "::1", event_id + "::2"],
                "battery_id": [battery_id, battery_id],
                "experiment_id": [battery_id.replace("BATTERY", "EXPERIMENT")] * 2,
                "soc_reference_percent": [20.0, 40.0],
                "peak_to_peak_v": values,
            }
        ),
    )


def test_builder_harmonizes_rows_and_preserves_battery_provenance() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    sources = {
        "DATASET::A::1": _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0]),
        "DATASET::B::1": _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::B", [3.0, 4.0]),
    }

    cohort, provenance = build_cohort_frame(request, sources)

    assert list(cohort.columns) == [
        "measurement_event_id",
        "source_measurement_event_id",
        "battery_id",
        "experiment_id",
        "source_dataset_id",
        "reference_soc_percent",
        "ultrasound_peak_to_peak",
    ]
    assert cohort["battery_id"].nunique() == 2
    assert cohort["measurement_event_id"].is_unique
    assert cohort["reference_soc_percent"].tolist() == [20.0, 40.0, 20.0, 40.0]
    assert provenance["target_method_version"] == "soc-formula/1.0"
    assert provenance["predictor_columns"] == ["ultrasound_peak_to_peak"]


def test_builder_rejects_incompatible_soc_method_or_temporality() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    source_b = _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::B", [3.0, 4.0])
    source_b[0]["target_method_version"] = "soc-formula/2.0"
    sources = {
        "DATASET::A::1": _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0]),
        "DATASET::B::1": source_b,
    }

    with pytest.raises(CohortMaterializationError, match="target method version"):
        build_cohort_frame(request, sources)


def test_builder_rejects_unit_or_feature_version_not_matching_source_definition() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    source_a = _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0])
    source_a[0]["_feature_definitions"]["peak_to_peak_v"]["unit"] = "mV"
    sources = {
        "DATASET::A::1": source_a,
        "DATASET::B::1": _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::B", [3.0, 4.0]),
    }

    with pytest.raises(CohortMaterializationError, match="does not match its definition"):
        build_cohort_frame(request, sources)


def test_builder_rejects_same_name_version_unit_with_different_formula() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    source_b = _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::B", [3.0, 4.0])
    source_b[0]["_feature_definitions"]["peak_to_peak_v"]["formula"] = "mean(x)"
    sources = {
        "DATASET::A::1": _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0]),
        "DATASET::B::1": source_b,
    }

    with pytest.raises(CohortMaterializationError, match="not semantically equivalent"):
        build_cohort_frame(request, sources)


def test_builder_defensively_rejects_identity_column_overwrite() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    unsafe_mapping = request.feature_mappings[0].model_copy(
        update={"canonical_feature_id": "battery_id"}
    )
    unsafe_request = request.model_copy(
        update={
            "feature_mappings": [unsafe_mapping],
            "unit_mapping": {"battery_id": request.unit_mapping["ultrasound_peak_to_peak"]},
        }
    )
    sources = {
        "DATASET::A::1": _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0]),
        "DATASET::B::1": _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::B", [3.0, 4.0]),
    }

    with pytest.raises(CohortMaterializationError, match="cannot replace cohort identity or target"):
        build_cohort_frame(unsafe_request, sources)


def test_builder_namespaces_repeated_source_event_ids_by_battery() -> None:
    request = CohortDatasetRequest.model_validate(_valid_request())
    sources = {
        "DATASET::A::1": _source_payload("DATASET::A::1", "BATTERY::A", "EVENT::A", [1.0, 2.0]),
        "DATASET::B::1": _source_payload("DATASET::B::1", "BATTERY::B", "EVENT::A", [3.0, 4.0]),
    }

    cohort, _ = build_cohort_frame(request, sources)
    assert cohort["measurement_event_id"].is_unique
    assert cohort["source_measurement_event_id"].tolist() == [
        "EVENT::A::1",
        "EVENT::A::2",
        "EVENT::A::1",
        "EVENT::A::2",
    ]
    assert cohort["measurement_event_id"].str.startswith("COHORT_EVENT::").all()

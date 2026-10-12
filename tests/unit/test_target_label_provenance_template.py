from __future__ import annotations

from pathlib import Path

import yaml

from battery_workbench.api.future_contracts import (
    TargetDatasetRequest,
    TargetLabelProvenance,
    TargetUncertainty,
)

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "templates"
    / "target-label-provenance.yaml"
)


def _load_template() -> dict:
    with TEMPLATE.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    assert isinstance(payload, dict)
    return payload


def test_target_label_worksheet_fields_track_the_current_contract() -> None:
    worksheet = _load_template()
    request_fields = set(TargetDatasetRequest.model_fields)
    worksheet_request_fields = set(worksheet) - {
        "worksheet_version",
        "evidence_review",
    }

    assert worksheet["worksheet_version"] == "target-label-provenance-worksheet/1.0"
    assert worksheet["contract_version"] == "target-dataset/1.0"
    assert worksheet_request_fields == request_fields
    assert set(worksheet["label_provenance"]) == set(TargetLabelProvenance.model_fields)
    assert set(worksheet["label_provenance"]["uncertainty"]) == set(TargetUncertainty.model_fields)


def test_target_label_worksheet_does_not_choose_scientific_values() -> None:
    worksheet = _load_template()
    provenance = worksheet["label_provenance"]
    uncertainty = provenance["uncertainty"]

    assert worksheet["target_id"] is None
    assert worksheet["target_grain"] is None
    assert worksheet["minimum_independent_states"] is None
    assert worksheet["battery_ids"] == []
    assert worksheet["experiment_ids"] == []
    assert worksheet["feature_locators"] == []
    assert provenance["semantic_type"] is None
    assert provenance["method_id"] is None
    assert provenance["method_version"] is None
    assert provenance["definition"] is None
    assert provenance["unit"] is None
    assert provenance["independent_unit"] == "BATTERY"
    assert provenance["source_references"] == []
    assert uncertainty["status"] is None
    assert uncertainty["standard_uncertainty"] is None
    assert uncertainty["evidence_refs"] == []
    assert uncertainty["reason"] is None

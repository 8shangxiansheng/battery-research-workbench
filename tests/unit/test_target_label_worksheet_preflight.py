from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from battery_workbench.provenance.target_label_worksheet import (
    TargetLabelWorksheetError,
    validate_target_label_worksheet,
)


def _valid_worksheet() -> dict:
    return {
        "worksheet_version": "target-label-provenance-worksheet/1.0",
        "contract_version": "target-dataset/1.0",
        "target_id": "reference_soc_percent",
        "target_grain": "MEASUREMENT_EVENT",
        "minimum_independent_states": None,
        "battery_ids": ["BATTERY_SYNTHETIC"],
        "experiment_ids": ["EXPERIMENT_SYNTHETIC"],
        "feature_locators": [{"feature_name": "amplitude_a_u", "gate_id": None}],
        "label_provenance": {
            "semantic_type": "DERIVED_REFERENCE_LABEL",
            "method_id": "SYNTHETIC_METHOD",
            "method_version": "1",
            "definition": "Synthetic contract-only fixture; not a scientific method.",
            "unit": "percent",
            "independent_unit": "BATTERY",
            "source_references": [
                {
                    "asset_id": "ASSET_SYNTHETIC",
                    "source_reference": "data/raw/synthetic.xlsx",
                    "sha256": "a" * 64,
                }
            ],
            "uncertainty": {
                "status": "UNKNOWN",
                "standard_uncertainty": None,
                "unit": None,
                "method": None,
                "evidence_refs": [],
                "reason": "Synthetic contract-only fixture.",
            },
        },
        "evidence_review": {
            "protocol_reference": None,
            "measurement_grain_rationale": None,
            "known_limitations": [],
            "reviewer": None,
            "reviewed_at": None,
        },
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_preflight_validates_contract_without_claiming_scientific_readiness(tmp_path: Path) -> None:
    worksheet_path = tmp_path / "target-label.yaml"
    _write_yaml(worksheet_path, _valid_worksheet())
    original_bytes = worksheet_path.read_bytes()

    result = validate_target_label_worksheet(worksheet_path)

    assert result["status"] == "TARGET_LABEL_WORKSHEET_CONTRACT_VALIDATED"
    assert result["contract_version"] == "target-dataset/1.0"
    assert result["target_id"] == "reference_soc_percent"
    assert result["source_integrity_status"] == "NOT_CHECKED"
    assert result["label_semantics_status"] == "NOT_ASSESSED"
    assert result["target_readiness"] == "NOT_ASSESSED"
    assert result["materialization_enabled"] is False
    assert worksheet_path.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(target_grain="CYCLE"), "target_grain"),
        (
            lambda payload: payload["label_provenance"].update(unit="volts"),
            "target_grain, label semantic_type and unit",
        ),
        (
            lambda payload: payload["label_provenance"]["uncertainty"].update(
                standard_uncertainty=1.0
            ),
            "UNKNOWN uncertainty",
        ),
    ],
)
def test_preflight_rejects_contract_inconsistent_worksheets(
    tmp_path: Path, mutate, message: str
) -> None:
    payload = deepcopy(_valid_worksheet())
    mutate(payload)
    worksheet_path = tmp_path / "invalid-target-label.yaml"
    _write_yaml(worksheet_path, payload)

    with pytest.raises(TargetLabelWorksheetError, match=message):
        validate_target_label_worksheet(worksheet_path)


def test_preflight_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    payload = _valid_worksheet()
    payload["target_readiness"] = "READY"
    worksheet_path = tmp_path / "unknown-field.yaml"
    _write_yaml(worksheet_path, payload)

    with pytest.raises(TargetLabelWorksheetError, match="unexpected worksheet fields"):
        validate_target_label_worksheet(worksheet_path)


def test_preflight_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    worksheet_path = tmp_path / "duplicate-key.yaml"
    worksheet_path.write_text(
        "worksheet_version: target-label-provenance-worksheet/1.0\n"
        "contract_version: target-dataset/1.0\n"
        "target_id: reference_soc_percent\n"
        "target_id: temperature_c\n",
        encoding="utf-8",
    )

    with pytest.raises(TargetLabelWorksheetError, match="duplicate mapping keys"):
        validate_target_label_worksheet(worksheet_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["evidence_review"].update(unreviewed_claim="READY"),
            "unexpected evidence_review fields",
        ),
        (
            lambda payload: payload["evidence_review"].update(known_limitations="none"),
            "known_limitations must be a list",
        ),
        (
            lambda payload: payload["evidence_review"].update(
                reviewer="reviewer-1", reviewed_at="2026-10-08T12:00:00"
            ),
            "reviewed_at must include a timezone",
        ),
        (
            lambda payload: payload["evidence_review"].update(reviewer="reviewer-1"),
            "reviewer and reviewed_at must be provided together",
        ),
    ],
)
def test_preflight_validates_companion_review_structure(
    tmp_path: Path, mutate, message: str
) -> None:
    payload = deepcopy(_valid_worksheet())
    mutate(payload)
    worksheet_path = tmp_path / "invalid-review.yaml"
    _write_yaml(worksheet_path, payload)

    with pytest.raises(TargetLabelWorksheetError, match=message):
        validate_target_label_worksheet(worksheet_path)


def test_preflight_rejects_non_utf8_worksheet_without_traceback(tmp_path: Path) -> None:
    worksheet_path = tmp_path / "invalid-encoding.yaml"
    worksheet_path.write_bytes(b"worksheet_version: \xff")

    with pytest.raises(TargetLabelWorksheetError, match="invalid YAML or encoding"):
        validate_target_label_worksheet(worksheet_path)


def test_preflight_rejects_unfilled_blank_template(tmp_path: Path) -> None:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "templates"
        / "target-label-provenance.yaml"
    )

    with pytest.raises(TargetLabelWorksheetError, match="contract validation failed"):
        validate_target_label_worksheet(template_path)

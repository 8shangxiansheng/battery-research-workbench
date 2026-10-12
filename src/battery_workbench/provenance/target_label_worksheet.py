"""Read-only structural preflight for target-label provenance worksheets.

Passing validates the worksheet shape against the dormant target-dataset
request contract. It does not verify source bytes, label meaning, readiness,
or authorize dataset materialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from battery_workbench.api.future_contracts import TargetDatasetRequest

WORKSHEET_VERSION = "target-label-provenance-worksheet/1.0"
_COMPANION_FIELDS = {"worksheet_version", "evidence_review"}
_EVIDENCE_REVIEW_FIELDS = {
    "protocol_reference",
    "measurement_grain_rationale",
    "known_limitations",
    "reviewer",
    "reviewed_at",
}


class TargetLabelWorksheetError(ValueError):
    """A worksheet is malformed or inconsistent with the target contract."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing worksheet mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


def _validate_evidence_review(value: Any) -> None:
    """Validate only the companion review-note shape, not its truth or authority."""
    if not isinstance(value, dict):
        raise TargetLabelWorksheetError("evidence_review must be a mapping")
    observed_fields = set(value)
    unexpected = sorted(observed_fields - _EVIDENCE_REVIEW_FIELDS)
    missing = sorted(_EVIDENCE_REVIEW_FIELDS - observed_fields)
    if unexpected:
        raise TargetLabelWorksheetError(
            f"unexpected evidence_review fields: {', '.join(unexpected)}"
        )
    if missing:
        raise TargetLabelWorksheetError(
            f"missing evidence_review fields: {', '.join(missing)}"
        )

    for field in ("protocol_reference", "measurement_grain_rationale", "reviewer"):
        field_value = value[field]
        if field_value is not None and (
            not isinstance(field_value, str) or not field_value.strip()
        ):
            raise TargetLabelWorksheetError(
                f"evidence_review.{field} must be null or non-blank text"
            )

    limitations = value["known_limitations"]
    if not isinstance(limitations, list):
        raise TargetLabelWorksheetError("evidence_review.known_limitations must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in limitations):
        raise TargetLabelWorksheetError(
            "evidence_review.known_limitations must contain non-blank text items"
        )

    reviewer = value["reviewer"]
    reviewed_at = value["reviewed_at"]
    if (reviewer is None) != (reviewed_at is None):
        raise TargetLabelWorksheetError(
            "evidence_review.reviewer and reviewed_at must be provided together"
        )
    if reviewed_at is not None:
        if not isinstance(reviewed_at, str) or not reviewed_at.strip():
            raise TargetLabelWorksheetError(
                "evidence_review.reviewed_at must be null or timezone-aware ISO-8601 text"
            )
        try:
            parsed = datetime.fromisoformat(reviewed_at.strip())
        except ValueError as exc:
            raise TargetLabelWorksheetError(
                "evidence_review.reviewed_at must be valid ISO-8601 text"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise TargetLabelWorksheetError(
                "evidence_review.reviewed_at must include a timezone"
            )


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def validate_target_label_worksheet(worksheet_path: str | Path) -> dict[str, Any]:
    """Validate a completed worksheet's contract shape without changing it."""
    path = Path(worksheet_path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise TargetLabelWorksheetError("worksheet is missing or unreadable") from exc

    try:
        worksheet = yaml.load(raw_bytes, Loader=_UniqueKeySafeLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise TargetLabelWorksheetError(
            "worksheet has invalid YAML or encoding, or contains duplicate mapping keys"
        ) from exc
    if not isinstance(worksheet, dict):
        raise TargetLabelWorksheetError("worksheet root must be a mapping")
    if worksheet.get("worksheet_version") != WORKSHEET_VERSION:
        raise TargetLabelWorksheetError(
            f"worksheet_version must be {WORKSHEET_VERSION}"
        )
    _validate_evidence_review(worksheet.get("evidence_review"))

    expected_fields = set(TargetDatasetRequest.model_fields) | _COMPANION_FIELDS
    observed_fields = set(worksheet)
    unexpected = sorted(observed_fields - expected_fields)
    missing = sorted(expected_fields - observed_fields)
    if unexpected:
        raise TargetLabelWorksheetError(
            f"unexpected worksheet fields: {', '.join(unexpected)}"
        )
    if missing:
        raise TargetLabelWorksheetError(
            f"missing worksheet fields: {', '.join(missing)}"
        )

    request_payload = {
        key: value for key, value in worksheet.items() if key not in _COMPANION_FIELDS
    }
    try:
        request = TargetDatasetRequest.model_validate(request_payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        )
        raise TargetLabelWorksheetError(
            f"contract validation failed: {details}"
        ) from exc

    return {
        "status": "TARGET_LABEL_WORKSHEET_CONTRACT_VALIDATED",
        "worksheet_version": WORKSHEET_VERSION,
        "contract_version": request.contract_version,
        "worksheet_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "target_id": request.target_id,
        "identity_pair_count": len(request.battery_ids),
        "feature_locator_count": len(request.feature_locators),
        "label_source_reference_count": len(request.label_provenance.source_references),
        "source_integrity_status": "NOT_CHECKED",
        "label_semantics_status": "NOT_ASSESSED",
        "target_readiness": "NOT_ASSESSED",
        "materialization_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only target-label worksheet contract check; does not verify "
            "scientific evidence or materialize a dataset."
        )
    )
    parser.add_argument("worksheet", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_target_label_worksheet(args.worksheet)
    except TargetLabelWorksheetError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

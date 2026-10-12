"""Append-only operator review registry for absolute-time evidence.

This registry records submissions and operator attestations. An accepted review
does not itself rewrite time_anchors.json or claim validated electrical/acoustic
synchronization; the synchronization pipeline must be recomputed and separately
verified before ``validated_sync`` can change.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from battery_workbench.api.future_contracts import TimebaseReviewRequest, TimebaseValidationRequest
from battery_workbench.synchronization.schemas import TimeAnchorOverride
from battery_workbench.synchronization.timebase_evidence import (
    TimebaseEvidenceError,
    verify_timebase_evidence_files,
)


class TimebaseRegistryError(ValueError):
    """A validation/review request is inconsistent with its audit record."""


class TimebaseRegistryIntegrityError(TimebaseRegistryError):
    """A persisted submission or audit event is corrupt or inconsistent."""


def _source_integrity_state(
    *,
    processed_root: Path,
    raw_root: Path,
    battery_id: str,
    experiment_id: str,
    asset_ids: list[str],
) -> tuple[str, list[str]]:
    """Assess whether the anchor DataAssets still match their parser inputs."""
    from battery_workbench.io.experiment.manifest_loader import (
        data_asset_matches,
        load_data_assets,
    )
    from battery_workbench.provenance.parser_manifest import (
        invalid_parser_manifest_modalities,
        parser_manifest_raw_source_mismatches,
    )

    manifest_path = Path(raw_root) / "manifests" / "data_assets.csv"
    try:
        assets = [
            asset
            for asset in load_data_assets(manifest_path)
            if data_asset_matches(asset, battery_id, experiment_id)
        ]
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        return "STALE_SOURCE", ["DATA_ASSET_MANIFEST_INVALID"]

    asset_by_id = {asset.asset_id: asset for asset in assets}
    if any(asset_id not in asset_by_id for asset_id in asset_ids):
        return "STALE_SOURCE", ["ANCHORED_DATA_ASSET_MISSING"]

    anchored_modalities = {asset_by_id[asset_id].modality for asset_id in asset_ids}
    parsed_modalities = {
        modality
        for modality in anchored_modalities
        if (
            Path(processed_root) / modality / battery_id / experiment_id / "parser_manifest.json"
        ).exists()
        or (
            Path(processed_root) / modality / battery_id / experiment_id / "parser_manifest.json"
        ).is_symlink()
    }
    structurally_invalid = set(
        invalid_parser_manifest_modalities(processed_root, battery_id, experiment_id)
    )
    raw_mismatches = set(
        parser_manifest_raw_source_mismatches(
            processed_root, raw_root, battery_id, experiment_id
        )
    )
    invalid_modalities = (structurally_invalid | raw_mismatches).intersection(parsed_modalities)
    affected_modalities = sorted(anchored_modalities.intersection(invalid_modalities))
    if affected_modalities:
        return "STALE_SOURCE", [f"SOURCE_PROVENANCE_INVALID:{item}" for item in affected_modalities]

    if parsed_modalities == anchored_modalities:
        return "CURRENT", []
    return "NOT_ASSESSED", ["PARSER_PROVENANCE_NOT_AVAILABLE"]


def _effective_validation_status(
    source_status: str, evidence_status: str, audit_status: str
) -> str:
    if evidence_status in {"INVALID_RECORD", "STALE_EVIDENCE"}:
        return evidence_status
    if source_status == "STALE_SOURCE":
        return "STALE_SOURCE"
    if evidence_status == "NOT_VERIFIED":
        return "NOT_VERIFIED"
    if source_status == "NOT_ASSESSED":
        return "NOT_ASSESSED"
    return audit_status


def _evidence_integrity_status(
    raw_root: Path, submission: dict[str, Any], events: list[dict[str, Any]]
) -> str:
    """Recheck proposal and review evidence against their recorded hashes."""
    evidence_sets = [submission.get("verified_evidence")]
    evidence_sets.extend(
        event.get("verified_evidence")
        for event in events
        if event.get("event_type") == "REVIEWED" and event.get("decision") == "ACCEPT"
    )
    if not any(isinstance(item, dict) and item for item in evidence_sets):
        return "NOT_VERIFIED"
    expected: dict[str, str] = {}
    for evidence_set in evidence_sets:
        if not isinstance(evidence_set, dict) or not evidence_set:
            return "NOT_VERIFIED"
        for reference, details in evidence_set.items():
            if not isinstance(reference, str) or not isinstance(details, dict):
                return "INVALID_RECORD"
            digest = details.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                return "INVALID_RECORD"
            prior = expected.setdefault(reference, digest)
            if prior.lower() != digest.lower():
                return "INVALID_RECORD"
    try:
        verify_timebase_evidence_files(
            raw_root, list(expected), expected_sha256=expected
        )
    except TimebaseEvidenceError:
        return "STALE_EVIDENCE"
    return "CURRENT"


def _base_dir(processed_root: Path, battery_id: str, experiment_id: str) -> Path:
    return (
        Path(processed_root)
        / "synchronization"
        / battery_id
        / experiment_id
        / "timebase_validations"
    )


def submit_timebase_validation(
    request: TimebaseValidationRequest,
    *,
    processed_root: Path,
    verified_evidence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation_id = f"TBV::{uuid.uuid4().hex}"
    directory = _base_dir(processed_root, request.battery_id, request.experiment_id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "validation_id": validation_id,
            "submitted_at": datetime.now(UTC).isoformat(),
            "status": "PROVISIONAL",
            "validated_sync": False,
            "identity_trust": "OPERATOR_ASSERTED_UNAUTHENTICATED",
            "evidence_integrity": "VERIFIED" if verified_evidence is not None else "NOT_VERIFIED",
            "verified_evidence": verified_evidence or {},
        }
    )
    (directory / f"{validation_id.replace(':', '_')}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _append_event(
        directory,
        validation_id,
        {
            "event_type": "SUBMITTED",
            "occurred_at": datetime.now(UTC).isoformat(),
            "status": "PROVISIONAL",
            "validated_sync": False,
        },
    )
    return payload


def list_timebase_validations(
    *, processed_root: Path, battery_id: str, experiment_id: str, raw_root: Path | None = None
) -> list[dict[str, Any]]:
    directory = _base_dir(processed_root, battery_id, experiment_id)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("TBV__*.json")):
        validation_id = path.stem.replace("TBV__", "TBV::", 1)
        submission = _load_submission(path, expected_validation_id=validation_id)
        validation_id = submission.get("validation_id")
        latest = _latest_event(directory, validation_id)
        if latest is None:
            raise TimebaseRegistryIntegrityError(
                "timebase audit event log is missing its submission event"
            )
        records.append(
            {
                "validation_id": validation_id,
                "status": latest["status"] if latest else "PROVISIONAL",
                "submitted_at": submission.get("submitted_at"),
                "asset_ids": [item["asset_id"] for item in submission.get("anchors", [])],
                "validated_sync": False,
            }
        )
        if raw_root is not None:
            audit_events = _events(directory, validation_id)
            evidence_status = _evidence_integrity_status(raw_root, submission, audit_events)
            records[-1]["evidence_integrity_status"] = evidence_status
        if raw_root is not None:
            source_status, source_reasons = _source_integrity_state(
                processed_root=processed_root,
                raw_root=raw_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
                asset_ids=[item["asset_id"] for item in submission.get("anchors", [])],
            )
            records[-1].update(
                {
                    "source_integrity_status": source_status,
                    "effective_status": _effective_validation_status(
                        source_status,
                        evidence_status,
                        str(latest["status"] if latest else "PROVISIONAL"),
                    ),
                    "source_integrity_reasons": source_reasons,
                }
            )
    return records


def accepted_timebase_overrides(
    *,
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    validation_id: str | None = None,
    raw_root: Path | None = None,
) -> dict[str, TimeAnchorOverride]:
    """Return operator-accepted anchors for recomputation, never as sync proof.

    Multiple active acceptances for one DataAsset are rejected rather than
    selecting a latest value implicitly. Revoked/rejected proposals do not
    affect the canonical time-anchor assessment.
    """
    directory = _base_dir(processed_root, battery_id, experiment_id)
    overrides: dict[str, TimeAnchorOverride] = {}
    for path in sorted(directory.glob("TBV__*.json")) if directory.is_dir() else []:
        filename_id = path.stem.replace("TBV__", "TBV::", 1)
        submission = _load_submission(path, expected_validation_id=filename_id)
        record_id = submission.get("validation_id")
        if validation_id and record_id != validation_id:
            continue
        latest = _latest_event(directory, record_id)
        if latest is None:
            raise TimebaseRegistryIntegrityError(
                "timebase audit event log is missing its submission event"
            )
        if latest is None or latest.get("status") not in {
            "ACCEPTED_PENDING_RECOMPUTE",
            "RECOMPUTED_PROVISIONAL",
        }:
            continue
        if raw_root is not None:
            evidence_status = _evidence_integrity_status(
                raw_root, submission, _events(directory, record_id)
            )
            if evidence_status == "STALE_EVIDENCE":
                raise TimebaseRegistryError(
                    "timebase evidence changed or is no longer available; submit and review new evidence"
                )
            if evidence_status == "INVALID_RECORD":
                raise TimebaseRegistryIntegrityError(
                    "timebase evidence audit record is malformed or inconsistent"
                )
            source_status, source_reasons = _source_integrity_state(
                processed_root=processed_root,
                raw_root=raw_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
                asset_ids=[item["asset_id"] for item in submission.get("anchors", [])],
            )
            if source_status == "STALE_SOURCE":
                raise TimebaseRegistryError(
                    "anchored DataAsset source changed; submit and review a new timebase validation: "
                    + ", ".join(source_reasons)
                )
            acceptance = next(
                (
                    event
                    for event in reversed(_events(directory, record_id))
                    if event.get("decision") == "ACCEPT"
                ),
                None,
            )
            submitted_evidence = submission.get("verified_evidence")
            reviewed_evidence = acceptance.get("verified_evidence") if acceptance else None
            if (
                submission.get("evidence_integrity") != "VERIFIED"
                or not isinstance(submitted_evidence, dict)
                or not isinstance(reviewed_evidence, dict)
                or acceptance is None
                or acceptance.get("evidence_integrity") != "VERIFIED"
            ):
                raise TimebaseRegistryError(
                    "accepted timebase validation is missing verified evidence file hashes"
                )
            expected_evidence: dict[str, str] = {}
            for verified_set in (submitted_evidence, reviewed_evidence):
                for reference, details in verified_set.items():
                    if not isinstance(details, dict) or not isinstance(details.get("sha256"), str):
                        raise TimebaseRegistryError("timebase evidence audit record is malformed")
                    digest = details["sha256"]
                    previous_digest = expected_evidence.setdefault(reference, digest)
                    if previous_digest.lower() != digest.lower():
                        raise TimebaseRegistryError(
                            "timebase evidence changed between proposal and review"
                        )
            try:
                verify_timebase_evidence_files(
                    raw_root,
                    list(expected_evidence),
                    expected_sha256=expected_evidence,
                )
            except TimebaseEvidenceError as exc:
                raise TimebaseRegistryError(
                    "timebase evidence changed or is no longer available; submit a new validation"
                ) from exc
        for anchor in submission.get("anchors", []):
            asset_id = anchor["asset_id"]
            if asset_id in overrides:
                raise TimebaseRegistryError(
                    f"multiple active accepted timebase validations for asset {asset_id}; revoke the stale proposal"
                )
            overrides[asset_id] = TimeAnchorOverride(
                anchor_datetime=anchor["absolute_start_time"],
                elapsed_time_s_at_anchor=0.0,
                reason=(
                    f"operator-accepted validation {record_id}; pending recomputation; "
                    f"operator-reported error_s={latest.get('error_by_asset_s', {}).get(asset_id)}; "
                    f"declared tolerance_s={submission['maximum_allowed_error_s']}; "
                    f"review evidence: {', '.join(latest.get('evidence_refs', []))}"
                ),
                timezone_known=True,
                timezone_name=submission["timezone"],
                source_reference=anchor["source_reference"],
                source_sha256=anchor["source_sha256"],
            )
    return overrides


def mark_timebase_validation_applied(
    *, processed_root: Path, battery_id: str, experiment_id: str, validation_id: str
) -> None:
    """Record that the accepted anchor was used to rebuild provisional state."""
    directory = _base_dir(processed_root, battery_id, experiment_id)
    latest = _latest_event(directory, validation_id)
    if latest is None or latest.get("status") not in {
        "ACCEPTED_PENDING_RECOMPUTE",
        "RECOMPUTED_PROVISIONAL",
    }:
        raise TimebaseRegistryError("validation is not accepted for recomputation")
    if latest.get("status") == "RECOMPUTED_PROVISIONAL":
        return
    _append_event(
        directory,
        validation_id,
        {
            "event_type": "ANCHOR_RECOMPUTED",
            "occurred_at": datetime.now(UTC).isoformat(),
            "status": "RECOMPUTED_PROVISIONAL",
            "validated_sync": False,
        },
    )


def timebase_validation_status(
    *, processed_root: Path, battery_id: str, experiment_id: str, validation_id: str
) -> str | None:
    latest = _latest_event(_base_dir(processed_root, battery_id, experiment_id), validation_id)
    return latest.get("status") if latest else None


def get_timebase_validation_record(
    *,
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    validation_id: str,
    raw_root: Path | None = None,
) -> dict[str, Any] | None:
    """Read one submission and its append-only events with integrity checks."""
    if not validation_id.startswith("TBV::") or "/" in validation_id or ".." in validation_id:
        raise TimebaseRegistryError("invalid validation_id")
    directory = _base_dir(processed_root, battery_id, experiment_id)
    path = directory / f"{validation_id.replace(':', '_')}.json"
    if not path.is_file():
        return None
    submission = _load_submission(path, expected_validation_id=validation_id)
    events = _events(directory, validation_id)
    if not events or events[0].get("event_type") != "SUBMITTED":
        raise TimebaseRegistryIntegrityError(
            "timebase audit event log is missing its submission event"
        )
    latest_review = next(
        (event for event in reversed(events) if event.get("event_type") == "REVIEWED"),
        None,
    )
    result = {
        **submission,
        "status": events[-1]["status"],
        "events": events,
        "latest_review_evidence_integrity": (
            latest_review.get("evidence_integrity") if latest_review else None
        ),
        "latest_review_verified_evidence": (
            latest_review.get("verified_evidence", {}) if latest_review else {}
        ),
    }
    if raw_root is not None:
        evidence_status = _evidence_integrity_status(raw_root, submission, events)
        result["evidence_integrity_status"] = evidence_status
        source_status, source_reasons = _source_integrity_state(
            processed_root=processed_root,
            raw_root=raw_root,
            battery_id=battery_id,
            experiment_id=experiment_id,
            asset_ids=[item["asset_id"] for item in submission.get("anchors", [])],
        )
        result.update(
            {
                "source_integrity_status": source_status,
                "effective_status": _effective_validation_status(
                    source_status, evidence_status, str(events[-1]["status"])
                ),
                "source_integrity_reasons": source_reasons,
            }
        )
    return result


def mark_timebase_validation_reverted(
    *, processed_root: Path, battery_id: str, experiment_id: str, validation_id: str
) -> None:
    directory = _base_dir(processed_root, battery_id, experiment_id)
    latest = _latest_event(directory, validation_id)
    if latest is None or latest.get("status") != "REVOKED_PENDING_RECOMPUTE":
        raise TimebaseRegistryError("validation is not revoked for provisional recomputation")
    _append_event(
        directory,
        validation_id,
        {
            "event_type": "ANCHOR_REVERTED",
            "occurred_at": datetime.now(UTC).isoformat(),
            "status": "REVOKED_PROVISIONAL",
            "validated_sync": False,
        },
    )


def review_timebase_validation(
    battery_id: str,
    experiment_id: str,
    validation_id: str,
    review: TimebaseReviewRequest,
    *,
    processed_root: Path,
    verified_evidence: dict[str, dict[str, Any]] | None = None,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    directory = _base_dir(processed_root, battery_id, experiment_id)
    safe_id = validation_id.replace(":", "_")
    if not validation_id.startswith("TBV::") or "/" in validation_id or ".." in validation_id:
        raise TimebaseRegistryError("invalid validation_id")
    path = directory / f"{safe_id}.json"
    if not path.is_file():
        raise TimebaseRegistryError("timebase validation not found")
    submission = _load_submission(path, expected_validation_id=validation_id)
    latest = _latest_event(directory, validation_id)
    latest_status = latest["status"] if latest else "PROVISIONAL"
    allowed_decisions = {
        "PROVISIONAL": {"ACCEPT", "REJECT"},
        "ACCEPTED_PENDING_RECOMPUTE": {"REVOKE"},
        "RECOMPUTED_PROVISIONAL": {"REVOKE"},
    }
    if review.decision not in allowed_decisions.get(latest_status, set()):
        raise TimebaseRegistryError(
            "review decision is not valid for the current validation status"
        )
    if review.decision == "ACCEPT":
        if raw_root is not None:
            evidence_status = _evidence_integrity_status(
                raw_root, submission, _events(directory, validation_id)
            )
            if evidence_status == "STALE_EVIDENCE":
                raise TimebaseRegistryError(
                    "proposal evidence changed or is no longer available; submit a new validation"
                )
            if evidence_status == "INVALID_RECORD":
                raise TimebaseRegistryIntegrityError(
                    "timebase evidence audit record is malformed or inconsistent"
                )
            source_status, source_reasons = _source_integrity_state(
                processed_root=processed_root,
                raw_root=raw_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
                asset_ids=[item["asset_id"] for item in submission.get("anchors", [])],
            )
            if source_status == "STALE_SOURCE":
                raise TimebaseRegistryError(
                    "anchored DataAsset source changed; stale validation cannot be accepted: "
                    + ", ".join(source_reasons)
                )
        if not isinstance(verified_evidence, dict) or not verified_evidence:
            raise TimebaseRegistryError(
                "acceptance requires verified review evidence file hashes"
            )
        proposal_refs = set(submission.get("evidence_refs", []))
        review_refs = set(verified_evidence)
        if proposal_refs & review_refs:
            raise TimebaseRegistryError(
                "review evidence must use files distinct from proposal evidence"
            )
        proposal_evidence = submission.get("verified_evidence")
        if not isinstance(proposal_evidence, dict) or not proposal_evidence:
            raise TimebaseRegistryError(
                "proposal evidence must have verified file hashes before acceptance"
            )
        proposal_hashes = {
            str(item.get("sha256", "")).lower()
            for item in proposal_evidence.values()
            if isinstance(item, dict)
        }
        review_hashes = {
            str(item.get("sha256", "")).lower()
            for item in verified_evidence.values()
            if isinstance(item, dict)
        }
        if not proposal_hashes or not review_hashes or proposal_hashes & review_hashes:
            raise TimebaseRegistryError(
                "review evidence must have checksums distinct from proposal evidence"
            )
        if set(review.evidence_refs) != review_refs:
            raise TimebaseRegistryError(
                "verified review evidence must match the review evidence_refs"
            )
        assets = {item["asset_id"] for item in submission["anchors"]}
        if set(review.error_by_asset_s) != assets:
            raise TimebaseRegistryError(
                "acceptance must report error for exactly every anchored asset"
            )
        if set(review.ambiguity_free_assets) != assets:
            raise TimebaseRegistryError(
                "acceptance must explicitly clear ambiguity for every asset"
            )
        if any(
            abs(error) > submission["maximum_allowed_error_s"]
            for error in review.error_by_asset_s.values()
        ):
            raise TimebaseRegistryError("measured timebase error exceeds the declared tolerance")
        if not review.evidence_refs:
            raise TimebaseRegistryError("acceptance requires independent review evidence")
        status = "ACCEPTED_PENDING_RECOMPUTE"
    elif review.decision == "REJECT":
        status = "REJECTED"
    else:
        status = (
            "REVOKED_PENDING_RECOMPUTE"
            if latest_status == "RECOMPUTED_PROVISIONAL"
            else "REVOKED_PROVISIONAL"
        )

    event = {
        "event_type": "REVIEWED",
        "occurred_at": datetime.now(UTC).isoformat(),
        "decision": review.decision,
        "status": status,
        "operator_identity": review.operator_identity,
        "identity_trust": "OPERATOR_ASSERTED_UNAUTHENTICATED",
        "rationale": review.rationale,
        "evidence_refs": review.evidence_refs,
        "evidence_integrity": "VERIFIED" if verified_evidence is not None else "NOT_VERIFIED",
        "verified_evidence": verified_evidence or {},
        "review_evidence_separation": (
            "VERIFIED_DISTINCT_REFERENCES_AND_CHECKSUMS"
            if review.decision == "ACCEPT"
            else "NOT_APPLICABLE"
        ),
        "error_by_asset_s": review.error_by_asset_s,
        "maximum_allowed_error_s": submission["maximum_allowed_error_s"],
        "ambiguity_free_assets": review.ambiguity_free_assets,
        "validated_sync": False,
    }
    _append_event(directory, validation_id, event)
    return {
        "validation_id": validation_id,
        "status": status,
        "validated_sync": False,
        "event": event,
    }


def _append_event(directory: Path, validation_id: str, event: dict[str, Any]) -> None:
    with (directory / f"{validation_id.replace(':', '_')}.events.jsonl").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _latest_event(directory: Path, validation_id: str) -> dict[str, Any] | None:
    events = _events(directory, validation_id)
    return events[-1] if events else None


def _events(directory: Path, validation_id: str) -> list[dict[str, Any]]:
    path = directory / f"{validation_id.replace(':', '_')}.events.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TimebaseRegistryIntegrityError("timebase audit event log is invalid") from exc
    if any(
        not isinstance(event, dict)
        or not isinstance(event.get("event_type"), str)
        or not isinstance(event.get("status"), str)
        or not isinstance(event.get("occurred_at"), str)
        for event in events
    ):
        raise TimebaseRegistryIntegrityError("timebase audit event log is invalid")
    return events


def _load_submission(path: Path, *, expected_validation_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TimebaseRegistryIntegrityError("timebase submission record is invalid") from exc
    if not isinstance(payload, dict) or payload.get("validation_id") != expected_validation_id:
        raise TimebaseRegistryIntegrityError("timebase submission record is invalid")
    try:
        TimebaseValidationRequest.model_validate(
            {
                key: payload[key]
                for key in (
                    "contract_version",
                    "battery_id",
                    "experiment_id",
                    "timezone",
                    "anchors",
                    "evidence_refs",
                    "maximum_allowed_error_s",
                )
                if key in payload
            }
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise TimebaseRegistryIntegrityError("timebase submission record is invalid") from exc
    return payload

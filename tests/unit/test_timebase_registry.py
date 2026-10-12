from __future__ import annotations

import json

import pytest

from battery_workbench.api.future_contracts import (
    TimebaseAnchor,
    TimebaseReviewRequest,
    TimebaseValidationRequest,
)
from battery_workbench.synchronization.timebase_registry import (
    TimebaseRegistryError,
    accepted_timebase_overrides,
    get_timebase_validation_record,
    list_timebase_validations,
    review_timebase_validation,
    submit_timebase_validation,
)


def _submission() -> TimebaseValidationRequest:
    return TimebaseValidationRequest(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        timezone="Asia/Shanghai",
        anchors=[
            TimebaseAnchor(
                asset_id="U001",
                absolute_start_time="2024-01-06T21:03:01+08:00",
                source_reference="batteries/CELL_001/EXP_001/timebase_evidence/calibration-log.txt",
                source_sha256="a" * 64,
            )
        ],
        evidence_refs=["batteries/CELL_001/EXP_001/timebase_evidence/calibration-log.txt"],
        maximum_allowed_error_s=0.5,
    )


def _review(decision: str = "ACCEPT", *, error: float = 0.2) -> TimebaseReviewRequest:
    return TimebaseReviewRequest(
        decision=decision,
        operator_identity="operator@example.org",
        rationale="Compared against recorded synchronization pulse.",
        evidence_refs=["pulse-audit.csv"],
        error_by_asset_s={"U001": error} if decision == "ACCEPT" else {},
        ambiguity_free_assets=["U001"] if decision == "ACCEPT" else [],
    )


def _verified_submission_evidence() -> dict[str, dict[str, object]]:
    return {
        "batteries/CELL_001/EXP_001/timebase_evidence/calibration-log.txt": {
            "sha256": "a" * 64,
            "size_bytes": 10,
        }
    }


def _verified_review_evidence(
    reference: str = "pulse-audit.csv", *, digest: str = "b" * 64
) -> dict[str, dict[str, object]]:
    return {reference: {"sha256": digest, "size_bytes": 12}}


def test_acceptance_is_audited_but_does_not_claim_validated_sync(tmp_path) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    reviewed = review_timebase_validation(
        "CELL_001",
        "EXP_001",
        submitted["validation_id"],
        _review(),
        processed_root=tmp_path,
        verified_evidence=_verified_review_evidence(),
    )

    assert submitted["status"] == "PROVISIONAL"
    assert reviewed["status"] == "ACCEPTED_PENDING_RECOMPUTE"
    assert reviewed["validated_sync"] is False
    audit_path = next(tmp_path.rglob("*.events.jsonl"))
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == ["SUBMITTED", "REVIEWED"]
    assert events[-1]["identity_trust"] == "OPERATOR_ASSERTED_UNAUTHENTICATED"
    assert events[-1]["review_evidence_separation"] == "VERIFIED_DISTINCT_REFERENCES_AND_CHECKSUMS"
    overrides = accepted_timebase_overrides(
        processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
    )
    assert overrides["U001"].timezone_known is True
    assert overrides["U001"].timezone_name == "Asia/Shanghai"
    assert overrides["U001"].source_reference == "batteries/CELL_001/EXP_001/timebase_evidence/calibration-log.txt"
    assert overrides["U001"].source_sha256 == "a" * 64
    assert "error_s=0.2" in overrides["U001"].reason
    assert "tolerance_s=0.5" in overrides["U001"].reason


@pytest.mark.parametrize(
    ("error", "ambiguity_free_assets"),
    [(0.6, ["U001"]), (0.2, [])],
)
def test_acceptance_rejects_excess_error_or_unresolved_ambiguity(
    tmp_path, error: float, ambiguity_free_assets: list[str]
) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    review = TimebaseReviewRequest(
        decision="ACCEPT",
        operator_identity="operator@example.org",
        rationale="Review attempted.",
        evidence_refs=["pulse-audit.csv"],
        error_by_asset_s={"U001": error},
        ambiguity_free_assets=ambiguity_free_assets,
    )
    with pytest.raises(TimebaseRegistryError):
        review_timebase_validation(
            "CELL_001", "EXP_001", submitted["validation_id"], review,
            processed_root=tmp_path,
            verified_evidence=_verified_review_evidence(),
        )


def test_revocation_returns_to_provisional_without_mutating_submission(tmp_path) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    submission_path = next(tmp_path.rglob("*.json"))
    before = submission_path.read_bytes()
    review_timebase_validation(
        "CELL_001", "EXP_001", submitted["validation_id"], _review(),
        processed_root=tmp_path,
        verified_evidence=_verified_review_evidence(),
    )
    revoked = review_timebase_validation(
        "CELL_001",
        "EXP_001",
        submitted["validation_id"],
        TimebaseReviewRequest(
            decision="REVOKE",
            operator_identity="operator@example.org",
            rationale="Clock source was later found to be incorrect.",
        ),
        processed_root=tmp_path,
    )
    assert revoked["status"] == "REVOKED_PROVISIONAL"
    assert revoked["validated_sync"] is False
    assert submission_path.read_bytes() == before
    assert accepted_timebase_overrides(
        processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
    ) == {}


def test_multiple_active_acceptances_for_same_asset_are_rejected(tmp_path) -> None:
    for _ in range(2):
        submitted = submit_timebase_validation(
            _submission(), processed_root=tmp_path,
            verified_evidence=_verified_submission_evidence(),
        )
        review_timebase_validation(
            "CELL_001", "EXP_001", submitted["validation_id"], _review(),
            processed_root=tmp_path,
            verified_evidence=_verified_review_evidence(),
        )
    with pytest.raises(TimebaseRegistryError, match="multiple active accepted"):
        accepted_timebase_overrides(
            processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
        )


def test_corrupt_submission_is_reported_instead_of_hidden(tmp_path) -> None:
    submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    submission_path = next(tmp_path.rglob("TBV__*.json"))
    submission_path.write_text("{truncated", encoding="utf-8")

    with pytest.raises(TimebaseRegistryError, match="submission record is invalid"):
        list_timebase_validations(
            processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
        )
    with pytest.raises(TimebaseRegistryError, match="submission record is invalid"):
        accepted_timebase_overrides(
            processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
        )


def test_corrupt_audit_event_is_reported_and_never_used_for_override(tmp_path) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    audit_path = next(tmp_path.rglob("*.events.jsonl"))
    audit_path.write_text('{"event_type":"SUBMITTED"}\n{broken\n', encoding="utf-8")

    with pytest.raises(TimebaseRegistryError, match="audit event log is invalid"):
        list_timebase_validations(
            processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
        )
    with pytest.raises(TimebaseRegistryError, match="audit event log is invalid"):
        accepted_timebase_overrides(
            processed_root=tmp_path, battery_id="CELL_001", experiment_id="EXP_001"
        )
    assert submitted["status"] == "PROVISIONAL"


@pytest.mark.parametrize(
    ("reference", "digest", "message"),
    [
        (
            "batteries/CELL_001/EXP_001/timebase_evidence/calibration-log.txt",
            "b" * 64,
            "distinct from proposal evidence",
        ),
        ("pulse-copy.csv", "a" * 64, "checksums distinct"),
    ],
)
def test_acceptance_requires_distinct_review_file_and_content(
    tmp_path, reference: str, digest: str, message: str
) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    review = TimebaseReviewRequest(
        decision="ACCEPT",
        operator_identity="operator@example.org",
        rationale="Compared against an independently recorded pulse audit.",
        evidence_refs=[reference],
        error_by_asset_s={"U001": 0.2},
        ambiguity_free_assets=["U001"],
    )
    with pytest.raises(TimebaseRegistryError, match=message):
        review_timebase_validation(
            "CELL_001", "EXP_001", submitted["validation_id"], review,
            processed_root=tmp_path,
            verified_evidence=_verified_review_evidence(reference, digest=digest),
        )


@pytest.mark.parametrize("integrity_status", ["INVALID_RECORD", "NOT_VERIFIED"])
def test_effective_status_blocks_unusable_review_evidence(
    tmp_path, monkeypatch, integrity_status: str
) -> None:
    submitted = submit_timebase_validation(
        _submission(), processed_root=tmp_path,
        verified_evidence=_verified_submission_evidence(),
    )
    review_timebase_validation(
        "CELL_001", "EXP_001", submitted["validation_id"], _review(),
        processed_root=tmp_path,
        verified_evidence=_verified_review_evidence(),
    )
    audit_path = next(tmp_path.rglob("*.events.jsonl"))
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    if integrity_status == "INVALID_RECORD":
        events[-1]["verified_evidence"]["pulse-audit.csv"]["sha256"] = "bad"
    else:
        events[-1]["verified_evidence"] = {}
    audit_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "battery_workbench.synchronization.timebase_registry._source_integrity_state",
        lambda **_kwargs: ("CURRENT", []),
    )

    listed = list_timebase_validations(
        processed_root=tmp_path,
        raw_root=tmp_path,
        battery_id="CELL_001",
        experiment_id="EXP_001",
    )[0]
    detailed = get_timebase_validation_record(
        processed_root=tmp_path,
        raw_root=tmp_path,
        battery_id="CELL_001",
        experiment_id="EXP_001",
        validation_id=submitted["validation_id"],
    )

    assert listed["status"] == "ACCEPTED_PENDING_RECOMPUTE"
    assert listed["evidence_integrity_status"] == integrity_status
    assert listed["effective_status"] == integrity_status
    assert detailed is not None
    assert detailed["evidence_integrity_status"] == integrity_status
    assert detailed["effective_status"] == integrity_status

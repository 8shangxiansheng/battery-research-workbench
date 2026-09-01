"""Deterministic source & verification priority for BRW-015.

Verification is the PRIMARY resolution key (VERIFIED beats UNVERIFIED at any
scope); source priority is a tiebreaker within the same verification class.
Both orderings are explicit, frozen, and deterministic.
"""

from __future__ import annotations

from battery_workbench.parameters.schemas import SourceType, VerificationStatus

# Higher value = stronger source within the same verification class.
SOURCE_PRIORITY: dict[str, int] = {
    SourceType.CALIBRATION_RECORD.value: 70,
    SourceType.INSTRUMENT_SETTING.value: 60,
    SourceType.DERIVED_FROM_VERIFIED_PARAMETERS.value: 50,
    SourceType.EXPERIMENT_LOG.value: 40,
    SourceType.MANIFEST_REPORTED.value: 30,
    SourceType.FILE_REPORTED.value: 20,
    SourceType.USER_SUPPLIED.value: 10,
    SourceType.UNKNOWN.value: 0,
}

# Verification is the primary key: VERIFIED records always outrank UNVERIFIED.
VERIFICATION_PRIORITY: dict[str, int] = {
    VerificationStatus.VERIFIED.value: 2,
    VerificationStatus.UNVERIFIED.value: 1,
    VerificationStatus.UNKNOWN.value: 0,
    VerificationStatus.CONFLICT.value: -1,
}


def source_priority(source_type: str | SourceType) -> int:
    return SOURCE_PRIORITY.get(str(source_type), 0)


def verification_priority(verification_status: str | VerificationStatus) -> int:
    return VERIFICATION_PRIORITY.get(str(verification_status), 0)

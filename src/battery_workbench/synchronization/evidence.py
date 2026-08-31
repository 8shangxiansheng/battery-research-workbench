"""Evidence collection & candidate construction for BRW-008 anchors.

An *evidence* records a raw observation (e.g. ``file_start_time`` from the
manifest, a manual override, or a time-like filename token). A *candidate* is
a resolved anchor for one asset's elapsed clock. Evidence and candidates are
distinct: evidence always survives, candidates are selected by priority.

Filename time tokens are recorded as hints only and are never promoted to an
authoritative anchor (BRW-008 §9/§11).
"""

from __future__ import annotations

from datetime import datetime

from battery_workbench.synchronization.schemas import (
    TimeAnchorCandidate,
    TimeAnchorEvidence,
    TimeAnchorOverride,
)


def collect_candidates(
    asset_id: str,
    modality: str,
    file_start_time: datetime | None,
    overrides: dict[str, TimeAnchorOverride] | None = None,
) -> tuple[list[TimeAnchorCandidate], list[TimeAnchorEvidence]]:
    """Build candidate anchors and their evidence for a single asset.

    Deterministic source order for evidence: manual override (if any), then
    manifest ``file_start_time`` (if any). A filename hint is intentionally
    not constructed here; callers that detect a hint add it as evidence via
    ``filename_hint_evidence`` without promoting it.
    """
    overrides = overrides or {}
    candidates: list[TimeAnchorCandidate] = []
    evidence: list[TimeAnchorEvidence] = []

    override = overrides.get(asset_id)
    if override is not None:
        evidence.append(
            TimeAnchorEvidence(
                evidence_id=f"{asset_id}-override",
                asset_id=asset_id,
                source_type="MANUAL_OVERRIDE",
                source_ref="time_anchor_overrides",
                raw_value=override.anchor_datetime,
                parsed_value=override.anchor_datetime,
                message=override.reason or "manual override",
            )
        )
        candidates.append(
            TimeAnchorCandidate(
                anchor_id=f"{asset_id}-override",
                asset_id=asset_id,
                anchor_datetime=override.anchor_datetime,
                elapsed_time_s_at_anchor=override.elapsed_time_s_at_anchor,
                source_type="MANUAL_OVERRIDE",
                source_ref="time_anchor_overrides",
                status="MANUALLY_ACCEPTED",
                notes=override.reason,
            )
        )

    if file_start_time is not None:
        evidence.append(
            TimeAnchorEvidence(
                evidence_id=f"{asset_id}-manifest",
                asset_id=asset_id,
                source_type="MANIFEST_FILE_START",
                source_ref="data_assets.csv",
                raw_value=file_start_time,
                parsed_value=file_start_time,
                message="manifest file_start_time",
            )
        )
        candidates.append(
            TimeAnchorCandidate(
                anchor_id=f"{asset_id}-manifest",
                asset_id=asset_id,
                anchor_datetime=file_start_time,
                elapsed_time_s_at_anchor=0.0,
                source_type="MANIFEST_FILE_START",
                source_ref="data_assets.csv",
                status="PROVISIONAL",
            )
        )

    return candidates, evidence


def filename_hint_evidence(asset_id: str, filename: str) -> TimeAnchorEvidence:
    """Record a filename time-like token as raw evidence only.

    Never promotes to a candidate/authoritative anchor. The meaning of any
    time token in the filename is UNKNOWN (BRW-008 §28).
    """
    return TimeAnchorEvidence(
        evidence_id=f"{asset_id}-filename-hint",
        asset_id=asset_id,
        source_type="FILENAME_HINT",
        source_ref=filename,
        raw_value=filename,
        parsed_value=None,
        supports_candidate=False,
        conflicts_with_candidate=False,
        message="filename time token recorded as hint; meaning UNKNOWN",
    )


def experiment_start_hint_evidence(
    asset_id: str, experiment_start_time: datetime | None
) -> TimeAnchorEvidence | None:
    """Record experiment start as a plausibility hint if present (not an anchor)."""
    if experiment_start_time is None:
        return None
    return TimeAnchorEvidence(
        evidence_id=f"{asset_id}-experiment-start-hint",
        asset_id=asset_id,
        source_type="EXPERIMENT_START_HINT",
        source_ref="experiments.csv",
        raw_value=experiment_start_time,
        parsed_value=experiment_start_time,
        supports_candidate=False,
        message="experiment start recorded as plausibility hint only",
    )

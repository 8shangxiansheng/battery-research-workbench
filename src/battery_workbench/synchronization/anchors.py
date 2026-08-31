"""Anchor selection & conflict detection for BRW-008.

Selection is deterministic by priority:

    MANUAL_OVERRIDE > MANIFEST_FILE_START > (no anchor)

Never falls back to ``experiment.start_time`` as a substitute anchor: a
missing anchor stays missing (``anchor_status == UNVERIFIED``). Conflicts are
recorded, never silently dropped.
"""

from __future__ import annotations

from datetime import datetime

from battery_workbench.domain.asset import DataAsset
from battery_workbench.synchronization.evidence import collect_candidates
from battery_workbench.synchronization.schemas import (
    AssetAnchorAssessment,
    TimeAnchorCandidate,
    TimeAnchorEvidence,
    TimeAnchorOverride,
)

# Re-export so callers use a single anchor API surface.
__all__ = ["collect_candidates"]

_RESOLUTION_PRIORITY = ("MANUAL_OVERRIDE", "MANIFEST_FILE_START")


class MissingTimeAnchorError(ValueError):
    """Raised when no file_start_time or accepted override is available.

    BRW-008 explicitly will NOT substitute ``experiment.start_time`` for a
    missing per-asset anchor; callers that need a loose fallback should handle
    the fact that no anchor exists rather than inventing one.
    """


def resolve_file_start_time(asset: DataAsset, experiment_start: datetime | None) -> datetime:
    """Prefer the per-file anchor. A missing anchor raises, never guesses.

    ``experiment_start`` is accepted only when ``asset.file_start_time`` is
    present (as a cross-check hint), and is never returned alone. This keeps
    the BRW-008 contract: missing anchor stays missing.

    .. deprecated::
        This legacy helper is retained for compatibility; BRW-008 uses
        :func:`select_anchor` which is deliberately strict about fallback.
    """
    if asset.file_start_time is not None:
        return asset.file_start_time
    raise MissingTimeAnchorError(
        f"No file_start_time available for asset {asset.asset_id}; will not fall back to "
        f"experiment_start ({experiment_start!r})"
    )


def select_anchor(candidates: list[TimeAnchorCandidate]) -> TimeAnchorCandidate | None:
    """Pick the highest-priority candidate. Returns ``None`` when none exist."""
    if not candidates:
        return None
    for source_type in _RESOLUTION_PRIORITY:
        for candidate in candidates:
            if candidate.source_type == source_type and candidate.status != "REJECTED":
                return candidate
    # Fall through to any accepted candidate not covered by priority (defensive).
    return next((c for c in candidates if c.status != "REJECTED"), None)


def _conflicting_evidence(
    candidates: list[TimeAnchorCandidate],
    evidence: list[TimeAnchorEvidence],
) -> list[TimeAnchorEvidence]:
    """Identify evidence that conflicts with the selected anchor.

    A conflict exists when a manual override differs from the manifest anchor.
    The non-selected candidate source is surfaced as conflicting evidence so
    nothing is hidden.
    """
    selected = select_anchor(candidates)
    if selected is None:
        return []
    conflicts: list[TimeAnchorEvidence] = []
    for candidate in candidates:
        if candidate is selected or candidate.status == "REJECTED":
            continue
        if candidate.anchor_datetime != selected.anchor_datetime:
            conflicts.append(
                TimeAnchorEvidence(
                    evidence_id=f"{candidate.asset_id}-conflict-{candidate.source_type}",
                    asset_id=candidate.asset_id,
                    source_type=candidate.source_type,
                    source_ref=candidate.source_ref,
                    raw_value=candidate.anchor_datetime,
                    parsed_value=candidate.anchor_datetime,
                    supports_candidate=False,
                    conflicts_with_candidate=True,
                    message=(
                        f"candidate {candidate.source_type} at "
                        f"{candidate.anchor_datetime.isoformat()} conflicts with selected "
                        f"{selected.source_type} at {selected.anchor_datetime.isoformat()}"
                    ),
                )
            )
    # Preserve any explicit conflict evidence already carried in the input.
    for ev in evidence:
        if ev.conflicts_with_candidate:
            conflicts.append(ev)
    return conflicts


def build_assessment(
    asset_id: str,
    modality: str,
    elapsed_min_s: float,
    elapsed_max_s: float,
    candidates: list[TimeAnchorCandidate],
    evidence: list[TimeAnchorEvidence],
    overrides: dict[str, TimeAnchorOverride] | None = None,
) -> AssetAnchorAssessment:
    """Assemble a per-asset assessment from candidates and evidence."""
    selected = select_anchor(candidates)
    conflicts = _conflicting_evidence(candidates, evidence)
    anchor_status = selected.status if selected is not None else None
    return AssetAnchorAssessment(
        asset_id=asset_id,
        modality=modality,
        elapsed_min_s=elapsed_min_s,
        elapsed_max_s=elapsed_max_s,
        candidates=candidates,
        selected_anchor_id=selected.anchor_id if selected is not None else None,
        anchor_status=anchor_status,
        coverage=None,  # filled by validation.assess_coverage
        conflicts=conflicts,
        validated_sync=False,
    )

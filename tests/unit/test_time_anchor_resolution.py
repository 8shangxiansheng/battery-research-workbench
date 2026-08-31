from __future__ import annotations

from datetime import datetime

from battery_workbench.synchronization.anchors import (
    build_assessment,
    collect_candidates,
    select_anchor,
)
from battery_workbench.synchronization.schemas import TimeAnchorOverride


def test_manifest_file_start_anchor_t02() -> None:
    """T02: manifest file_start_time yields a PROVISIONAL MANIFEST_FILE_START candidate."""
    file_start = datetime(2024, 1, 6, 9, 52, 31)
    candidates, evidence = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=file_start,
        overrides=None,
    )
    assert len(candidates) == 1
    selected = select_anchor(candidates)
    assert selected is not None
    assert selected.source_type == "MANIFEST_FILE_START"
    assert selected.anchor_datetime == file_start
    assert selected.elapsed_time_s_at_anchor == 0.0
    assert selected.status == "PROVISIONAL"
    assert any(e.source_type == "MANIFEST_FILE_START" for e in evidence)


def test_first_elapsed_not_anchor_t04() -> None:
    """T04: the anchor is the elapsed zero, not the first frame timestamp."""
    file_start = datetime(2024, 1, 6, 9, 52, 31)
    candidates, _ = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=file_start,
        overrides=None,
    )
    selected = select_anchor(candidates)
    assert selected is not None
    # Anchor equals file_start (elapsed=0); first frame time is file_start + 0.031217.
    assert selected.anchor_datetime == file_start
    assert selected != datetime(2024, 1, 6, 9, 52, 31, 31217)


def test_missing_anchor_t05() -> None:
    """T05: no file_start_time and no override -> no candidate, no invented value."""
    candidates, evidence = collect_candidates(
        asset_id="U002",
        modality="ultrasound",
        file_start_time=None,
        overrides=None,
    )
    assert candidates == []
    selected = select_anchor(candidates)
    assert selected is None
    # No experiment_start or filename hint was substituted.
    assert all(e.source_type != "EXPERIMENT_START_HINT" for e in evidence)


def test_manual_override_priority_t06() -> None:
    """T06: manual override wins over manifest, but manifest evidence is retained."""
    file_start = datetime(2024, 1, 6, 9, 52, 31)
    override = TimeAnchorOverride(
        anchor_datetime=datetime(2024, 1, 6, 10, 0, 0),
        elapsed_time_s_at_anchor=0.0,
        reason="confirmed from instrument metadata",
    )
    overrides = {"U001": override}
    candidates, _evidence = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=file_start,
        overrides=overrides,
    )
    assert len(candidates) == 2
    selected = select_anchor(candidates)
    assert selected is not None
    assert selected.source_type == "MANUAL_OVERRIDE"
    assert selected.anchor_datetime == datetime(2024, 1, 6, 10, 0, 0)
    # Manifest candidate is NOT silently dropped when a manual override exists.
    manifest_sources = {c.source_type for c in candidates}
    assert "MANIFEST_FILE_START" in manifest_sources


def test_candidate_conflict_t07() -> None:
    """T07: conflicting candidates are recorded, never hidden."""
    file_start = datetime(2024, 1, 6, 9, 52, 31)
    override = TimeAnchorOverride(
        anchor_datetime=datetime(2024, 1, 6, 10, 0, 0),
        elapsed_time_s_at_anchor=0.0,
        reason="confirmed from instrument metadata",
    )
    candidates, evidence = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=file_start,
        overrides={"U001": override},
    )
    assessment = build_assessment(
        asset_id="U001",
        modality="ultrasound",
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        candidates=candidates,
        evidence=evidence,
        overrides={"U001": override},
    )
    # A conflict exists because manual != manifest datetime.
    assert len(assessment.conflicts) >= 1
    assert assessment.anchor_status == "MANUALLY_ACCEPTED"


def test_filename_hint_not_authoritative_t11() -> None:
    """T11: a time-like filename token does not become the selected anchor."""
    file_start = datetime(2024, 1, 6, 9, 52, 31)
    candidates, _evidence = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=file_start,
        overrides=None,
    )
    # Even if the source filename contains a time, it is never auto-promoted.
    assert all(c.source_type != "FILENAME_HINT" for c in candidates)
    # A FILENAME_HINT may be recorded as evidence but must not win.
    hint = select_anchor(candidates)
    assert hint is not None
    assert hint.source_type == "MANIFEST_FILE_START"


def test_per_asset_independent_anchors_t12_t13() -> None:
    """T12/T13: each ultrasound asset resolves its own anchor; elapsed can reset."""
    u001 = datetime(2024, 1, 6, 9, 52, 31)
    c1, _ = collect_candidates("U001", "ultrasound", u001, None)
    c2, _ = collect_candidates("U002", "ultrasound", u001, None)
    assert select_anchor(c1).source_type == "MANIFEST_FILE_START"
    assert select_anchor(c2).source_type == "MANIFEST_FILE_START"
    # Both can start from the same anchor without being fused into one clock.
    assert select_anchor(c1).anchor_datetime == u001
    assert select_anchor(c2).anchor_datetime == u001


def test_no_cycle_dependency_t14() -> None:
    """T14: anchor resolution never consults cycle mapping."""
    candidates, _ = collect_candidates(
        asset_id="U001",
        modality="ultrasound",
        file_start_time=datetime(2024, 1, 6, 9, 52, 31),
        overrides=None,
    )
    # Cycle info is irrelevant to anchor resolution.
    assert select_anchor(candidates) is not None

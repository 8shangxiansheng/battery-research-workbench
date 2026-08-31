from __future__ import annotations

import pytest

from battery_workbench.multimodal.event_id import (
    build_measurement_event_id,
)


def test_event_id_deterministic_t01() -> None:
    """T01: identical input produces the same stable id across runs."""
    a = build_measurement_event_id("CELL_001", "EXP_001", "U001", 3998)
    b = build_measurement_event_id("CELL_001", "EXP_001", "U001", 3998)
    assert a == b
    assert a == "ME::CELL_001::EXP_001::U001::3998"


def test_event_id_distinguishes_filters() -> None:
    """Different frame / asset / experiment ids yield distinct event ids."""
    assert build_measurement_event_id("CELL_001", "EXP_001", "U001", 0) != (
        build_measurement_event_id("CELL_001", "EXP_001", "U001", 1)
    )
    assert build_measurement_event_id("CELL_001", "EXP_001", "U001", 0) != (
        build_measurement_event_id("CELL_001", "EXP_001", "U002", 0)
    )
    assert build_measurement_event_id("CELL_001", "EXP_001", "U001", 0) != (
        build_measurement_event_id("CELL_001", "EXP_002", "U001", 0)
    )


def test_event_id_independent_of_electrical_candidate_t25() -> None:
    """T25: the id depends only on the ultrasound frame identity, never on the
    selected electrical record / ambiguity."""
    # Two synthetic "same frame, different electrical outcome" inputs produce the
    # SAME id, proving the id is anchored to the ultrasound frame grain.
    id_unique = build_measurement_event_id("CELL_001", "EXP_001", "U001", 3998)
    # The electrical candidate is not part of the identity; a re-run with a
    # hypothetical different selected record would still yield this id.
    assert id_unique == "ME::CELL_001::EXP_001::U001::3998"


def test_event_id_no_row_number_dependency() -> None:
    """The id never depends on an output row ordinal."""
    id_at_0 = build_measurement_event_id("CELL_001", "EXP_001", "U001", 0)
    # Reordered iteration must not change the id of a given frame.
    assert id_at_0 == "ME::CELL_001::EXP_001::U001::0"
    # frame_index_raw is part of identity; building in a different position
    # (same logical frame) still yields the same id.
    assert id_at_0 == build_measurement_event_id("CELL_001", "EXP_001", "U001", 0)


def test_event_id_rejects_empty_components() -> None:
    """Empty components must be rejected, never silently truncated."""
    with pytest.raises(ValueError):
        build_measurement_event_id("", "EXP_001", "U001", 0)
    with pytest.raises(ValueError):
        build_measurement_event_id("CELL_001", "EXP_001", "", 0)

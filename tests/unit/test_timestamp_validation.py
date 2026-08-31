from __future__ import annotations

from datetime import datetime

import pytest

from battery_workbench.synchronization.timestamp_validation import (
    compare_legacy_timestamp,
)


def test_legacy_exact_match_t16() -> None:
    """T16: identical datetimes give delta≈0 and match=True."""
    derived = datetime(2024, 1, 6, 9, 52, 31, 31217)
    legacy = datetime(2024, 1, 6, 9, 52, 31, 31217)
    delta_s, match = compare_legacy_timestamp(derived, legacy, tolerance_s=1e-6)
    assert delta_s == 0.0
    assert match is True


def test_legacy_within_tolerance_t16b() -> None:
    """A 1us difference is a match under a 1e-6 tolerance."""
    derived = datetime(2024, 1, 6, 9, 52, 31, 31217)
    legacy = datetime(2024, 1, 6, 9, 52, 31, 31218)  # 1us later
    delta_s, match = compare_legacy_timestamp(derived, legacy, tolerance_s=1e-6)
    # derived is 1us EARLIER than legacy -> delta = -1e-6.
    assert delta_s == pytest.approx(-1e-6)
    assert match is True


def test_legacy_mismatch_warning_only_t17() -> None:
    """T17: a real mismatch reports delta and match=False; no value correction."""
    derived = datetime(2024, 1, 6, 9, 52, 31)
    legacy = datetime(2024, 1, 6, 9, 53, 0)  # 29s later
    delta_s, match = compare_legacy_timestamp(derived, legacy, tolerance_s=1e-6)
    # derived is 29s EARLIER than legacy -> delta = -29.0.
    assert delta_s == pytest.approx(-29.0)
    assert match is False
    # The derived/canonical value is never altered by the compare.
    assert derived == datetime(2024, 1, 6, 9, 52, 31)

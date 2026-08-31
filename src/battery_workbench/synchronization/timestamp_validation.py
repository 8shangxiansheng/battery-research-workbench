"""BRW-009 timestamp diagnostics & legacy comparison.

The parser-level ``absolute_timestamp`` (BRW-005) is compatibility evidence only.
It never decides the canonical BRW-009 timestamp; a mismatch produces a warning
and a delta, never a correction. Monotonicity/duplicate checks are diagnostic
only — inputs are never sorted, deduplicated, corrected, or shifted.
"""

from __future__ import annotations

from datetime import datetime


def compare_legacy_timestamp(
    derived: datetime,
    legacy: datetime,
    *,
    tolerance_s: float = 1e-6,
) -> tuple[float, bool]:
    """Compare a BRW-009 derived timestamp to a legacy parser timestamp.

    Returns ``(delta_s, match)`` where ``delta_s = derived - legacy`` and
    ``match`` is True iff ``abs(delta_s) <= tolerance_s``. The derived value is
    never mutated.
    """
    delta_s = (derived - legacy).total_seconds()
    match = abs(delta_s) <= tolerance_s
    return delta_s, match

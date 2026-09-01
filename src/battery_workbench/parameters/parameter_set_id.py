"""Deterministic parameter-set identity for BRW-015.

The id is computed over unit-normalized records, so 100 MHz and 1e8 Hz yield
the identical scientific identity. Verification-state or policy-version
changes produce a new id; historical sets are never silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_parameter_set_id(
    *,
    normalized_records: list[dict[str, Any]],
    resolution_policy_version: str,
    unit_policy_version: str,
    battery_id: str,
    experiment_id: str,
) -> str:
    """Build the deterministic ``PS::<hash>`` parameter-set id."""
    canonical = json.dumps(
        {
            "records": normalized_records,
            "resolution_policy_version": resolution_policy_version,
            "unit_policy_version": unit_policy_version,
            "battery_id": battery_id,
            "experiment_id": experiment_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "PS::" + digest[:24]

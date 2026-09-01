"""Deterministic label-set identity for BRW-014."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_label_set_id(
    *,
    input_checksum: str,
    normalized_config: dict[str, Any],
    label_definition_version: str,
    reference_capacity_ah: float | None,
) -> str:
    """Build the deterministic ``LB::<hash>`` label-set id. No random UUID."""
    canonical = json.dumps(
        {
            "input": input_checksum,
            "config": normalized_config,
            "def_version": label_definition_version,
            "q_ref": reference_capacity_ah,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "LB::" + digest[:24]

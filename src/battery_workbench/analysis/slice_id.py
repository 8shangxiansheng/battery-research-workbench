"""Deterministic analysis-slice identity.

The canonical slice id is a digest of the input measurement-events checksum and
the normalized ConditionSliceSpec. List values are sorted + deduplicated so the
id is stable regardless of request ordering; a different input checksum or a
different normalized spec yields a different id. No random UUID is used.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        try:
            return sorted(set(value))
        except TypeError:
            return list(value)
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    return value


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize a spec dict: sort + dedupe lists, recurse into nested dicts."""
    return {k: _normalize_value(v) for k, v in spec.items()}


def canonical_serialize(spec: dict[str, Any]) -> str:
    """Stable JSON serialization of a normalized spec."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_analysis_slice_id(
    input_checksum: str,
    normalized_spec: dict[str, Any],
) -> str:
    """Build the deterministic ``AS::<hash>`` slice id."""
    canonical = canonical_serialize(normalized_spec)
    digest = hashlib.sha256((input_checksum + "::" + canonical).encode("utf-8")).hexdigest()
    return "AS::" + digest[:24]

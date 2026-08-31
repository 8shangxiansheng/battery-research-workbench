"""Deterministic ultrasound feature-set identity.

The feature-set id is a digest of the analysis-slice checksum, the waveform
store provenance, the normalized feature config, and the feature-definition
version. Same inputs/config/version -> same id. No random UUID.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_serialize(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_feature_set_id(
    *,
    analysis_slice_checksum: str,
    waveform_store_provenance: str,
    normalized_config: dict[str, Any],
    feature_definition_version: str,
) -> str:
    """Build the deterministic ``FS::<hash>`` feature-set id."""
    canonical = canonical_serialize(
        {
            "slice": analysis_slice_checksum,
            "store": waveform_store_provenance,
            "config": normalized_config,
            "def_version": feature_definition_version,
        }
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "FS::" + digest[:24]

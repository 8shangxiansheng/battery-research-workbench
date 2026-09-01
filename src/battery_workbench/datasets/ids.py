"""Deterministic dataset identity for BRW-016."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_dataset_id(
    *,
    feature_set_id: str,
    label_set_id: str,
    parameter_set_id: str,
    target_name: str,
    config: Any,
    feature_checksum: str,
    label_checksum: str,
    selected_features: list[str] | None = None,
) -> str:
    """Build the deterministic ``DS::<hash>`` dataset id.

    SOC and SOH always get separate ids (target_name participates in the hash).
    ``selected_features`` (V2) participates in the hash when explicitly given;
    passing ``None`` reproduces the legacy BRW-016 id byte-for-byte.
    """
    canonical = json.dumps(
        {
            "feature_set_id": feature_set_id,
            "feature_checksum": feature_checksum,
            "label_set_id": label_set_id,
            "label_checksum": label_checksum,
            "parameter_set_id": parameter_set_id,
            "target_name": target_name,
            "predictor_policy": config.predictor_policy,
            "role_schema_version": config.role_schema_version,
            "leakage_policy_version": config.leakage_policy_version,
            "selected_features": selected_features,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "DS::" + digest[:24]

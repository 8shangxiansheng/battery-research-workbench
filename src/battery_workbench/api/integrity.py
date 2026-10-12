"""Shared fail-closed checks for filesystem-backed scientific API artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pyarrow.lib import ArrowException

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.provenance.processed_manifest import (
    verify_manifest_files,
    verify_manifest_inputs,
    verify_output_checksums_in_directory,
)


def assert_processed_artifact_integrity(
    processed_root: Path,
    manifest_path: Path,
    *,
    battery_id: str,
    experiment_id: str,
    required_outputs: set[str],
    required_inputs: set[str],
    required_manifest_fields: set[str] | None = None,
    recovery_action: str = "REBUILD_DERIVED_ARTIFACTS_FROM_VERIFIED_INPUTS",
) -> dict[str, Any]:
    """Validate manifest identity and declared file checksums before serving data."""
    try:
        manifest_path.resolve(strict=True).relative_to(Path(processed_root).resolve())
    except (OSError, RuntimeError, ValueError):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "processed artifact manifest is outside the configured data root",
            {
                "integrity_reasons": ["MANIFEST_PATH_INVALID"],
                "recovery_action": recovery_action,
            },
        ) from None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        reasons = ["MANIFEST_UNREADABLE"]
    else:
        reasons = verify_manifest_files(
            processed_root,
            manifest,
            battery_id=battery_id,
            experiment_id=experiment_id,
            required_outputs=required_outputs,
            required_inputs=required_inputs,
        )
        if isinstance(manifest, dict):
            reasons.extend(
                f"MANIFEST_FIELD_MISSING:{field}"
                for field in sorted(required_manifest_fields or set())
                if not isinstance(manifest.get(field), str) or not manifest[field].strip()
            )
        if (
            isinstance(manifest, dict)
            and manifest.get("label_engine_name") == "reference_label_engine"
            and "label_set_id" in (required_manifest_fields or set())
        ):
            from battery_workbench.labels.schemas import LabelConfig

            current_label_config = LabelConfig()
            if manifest.get("label_engine_version") != current_label_config.version:
                reasons.append("LABEL_ENGINE_VERSION_UNSUPPORTED")
            if manifest.get("label_definition_version") != current_label_config.label_definition_version:
                reasons.append("LABEL_DEFINITION_VERSION_UNSUPPORTED")
    if reasons:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "processed artifact integrity verification failed; derived data is blocked",
            {"integrity_reasons": reasons, "recovery_action": recovery_action},
        )
    if (
        isinstance(manifest, dict)
        and manifest.get("label_engine_name") == "reference_label_engine"
        and "label_set_id" in (required_manifest_fields or set())
    ):
        try:
            from battery_workbench.labels.builder import validate_reference_label_inputs

            validate_reference_label_inputs(
                measurement_events_path=(
                    Path(processed_root)
                    / "multimodal"
                    / battery_id
                    / experiment_id
                    / "measurement_events.parquet"
                ),
                records_path=(
                    Path(processed_root)
                    / "electrical"
                    / battery_id
                    / experiment_id
                    / "records.parquet"
                ),
                cycles_path=(
                    Path(processed_root)
                    / "electrical"
                    / battery_id
                    / experiment_id
                    / "cycles.parquet"
                ),
                steps_path=(
                    Path(processed_root)
                    / "electrical"
                    / battery_id
                    / experiment_id
                    / "steps.parquet"
                ),
                expected_battery_id=battery_id,
                expected_experiment_id=experiment_id,
            )
        except (OSError, ValueError, KeyError, TypeError, ArrowException) as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "reference label source semantics are invalid; derived label reads are blocked",
                {
                    "integrity_reasons": [f"LABEL_INPUT_SEMANTICS_INVALID:{exc}"],
                    "recovery_action": recovery_action,
                },
            ) from None
    return manifest


def assert_canonical_tof_integrity(
    processed_root: Path,
    *,
    battery_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    """Require current canonical TOF inputs, calibration, and outputs before reads."""
    from battery_workbench.features_physical.canonical_tof import (
        canonical_tof_integrity_reasons,
    )

    root = Path(processed_root)
    manifest_path = (
        root / "features_physical" / battery_id / experiment_id / "canonical_tof_manifest.json"
    )
    try:
        manifest_path.resolve(strict=True).relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "canonical TOF provenance is missing or outside the processed data root",
            {
                "integrity_reasons": ["CANONICAL_TOF_MANIFEST_MISSING_OR_INVALID"],
                "recovery_action": "REBUILD_CANONICAL_TOF_FROM_CURRENT_FEATURES_AND_PARAMETERS",
            },
        ) from None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        manifest = None
    reasons = canonical_tof_integrity_reasons(root, battery_id, experiment_id)
    if reasons:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "canonical TOF is stale or unverifiable; dependent reads are blocked",
            {
                "integrity_reasons": reasons,
                "recovery_action": "REBUILD_CANONICAL_TOF_FROM_CURRENT_FEATURES_AND_PARAMETERS",
            },
        )
    return manifest


def assert_current_timebase_chain(
    processed_root: Path,
    raw_root: Path,
    *,
    battery_id: str,
    experiment_id: str,
) -> None:
    """Block alignment reads unless TimeAnchor and Timestamp inputs/outputs are current."""
    from battery_workbench.provenance.time_anchor import (
        time_anchor_artifact_integrity_reasons,
    )

    root = Path(processed_root)
    anchor_reasons = time_anchor_artifact_integrity_reasons(
        raw_root=Path(raw_root),
        processed_root=root,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    reasons = list(anchor_reasons)
    sync_dir = root / "synchronization" / battery_id / experiment_id
    timestamp_manifest_path = sync_dir / "timestamp_engine_manifest.json"
    try:
        timestamp_manifest_path.resolve(strict=True).relative_to(root.resolve())
    except FileNotFoundError:
        reasons.append("TIMESTAMP_MANIFEST_MISSING")
        timestamp_manifest = None
    except (OSError, RuntimeError, ValueError):
        reasons.append("TIMESTAMP_MANIFEST_PATH_INVALID")
        timestamp_manifest = None
    else:
        try:
            timestamp_manifest = json.loads(timestamp_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            timestamp_manifest = None
            reasons.append("TIMESTAMP_MANIFEST_UNREADABLE")

    if isinstance(timestamp_manifest, dict):
        if (
            timestamp_manifest.get("battery_id") != battery_id
            or timestamp_manifest.get("experiment_id") != experiment_id
        ):
            reasons.append("TIMESTAMP_IDENTITY_MISMATCH")
        reasons.extend(
            verify_manifest_inputs(
                root,
                timestamp_manifest,
                required_inputs={"frames", "time_anchor_state"},
            )
        )
        ultrasound_dir = root / "ultrasound" / battery_id / experiment_id
        state_path = sync_dir / "time_anchors.json"
        for key, current_path in (
            ("frames", ultrasound_dir / "frames.parquet"),
            ("time_anchor_state", state_path),
        ):
            try:
                resolved_path = current_path.resolve(strict=True)
                resolved_path.relative_to(root.resolve())
                digest = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
            except (OSError, RuntimeError, ValueError):
                reasons.append(f"TIMESTAMP_CURRENT_INPUT_MISSING:{key}")
                continue
            input_checksums = timestamp_manifest.get("input_checksums")
            if not isinstance(input_checksums, dict) or input_checksums.get(key) != digest:
                reasons.append(f"TIMESTAMP_CURRENT_INPUT_MISMATCH:{key}")
        reasons.extend(
            verify_output_checksums_in_directory(
                root,
                sync_dir,
                {"timestamped_frames": timestamp_manifest.get("output_checksum")},
                {"timestamped_frames": "timestamped_ultrasound_frames.parquet"},
            )
        )
    if reasons:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "current TimeAnchor/Timestamp provenance is required before serving alignment data",
            {
                "integrity_reasons": list(dict.fromkeys(reasons)),
                "recovery_action": "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT",
            },
        )

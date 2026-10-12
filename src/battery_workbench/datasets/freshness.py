"""Integrity checks for materialized datasets and their declared sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow.lib import ArrowException

from battery_workbench.provenance.parser_manifest import (
    invalid_parser_manifest_modalities,
    parser_manifest_raw_source_mismatches,
)
from battery_workbench.provenance.processed_manifest import (
    content_sha256,
    feature_waveform_store_sha256,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_processed_path(processed_root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    root = Path(processed_root).resolve()
    value = Path(reference)
    candidate: Path
    if value.is_absolute():
        resolved_reference = value.resolve()
        try:
            resolved_reference.relative_to(root)
            candidate = resolved_reference
        except ValueError:
            # Historical manifests may contain paths from another machine/container.
            # Rebase only paths carrying the known data/processed anchor.
            parts = PurePosixPath(reference.replace("\\", "/")).parts
            anchor = next(
                (
                    index
                    for index in range(len(parts) - 1)
                    if parts[index : index + 2] == ("data", "processed")
                ),
                None,
            )
            if anchor is None:
                return None
            suffix = parts[anchor + 2 :]
            if not suffix or any(part in {"", ".", ".."} for part in suffix):
                return None
            candidate = root.joinpath(*suffix).resolve()
    else:
        parts = value.parts
        if any(part in {"..", ""} for part in parts):
            return None
        if parts[:2] == ("data", "processed"):
            parts = parts[2:]
        if not parts:
            return None
        candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _has_identity_path(
    path: Path,
    *,
    asset_kind: str,
    battery_id: str,
    experiment_id: str,
    source_id: str,
) -> bool:
    parts = path.parts
    if asset_kind == "feature":
        return (
            len(parts) >= 5
            and parts[0] == "features"
            and parts[1] == battery_id
            and parts[2] == experiment_id
            and source_id in parts
        )
    return any(
        parts[index : index + 3] == ("labels", battery_id, experiment_id)
        for index in range(len(parts) - 2)
    )


def dataset_freshness(
    processed_root: Path,
    manifest_path: Path,
    manifest: Any,
    *,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    """Return a fail-closed freshness assessment without exposing host paths."""
    if not isinstance(manifest, dict):
        return {
            "freshness_status": "STALE_SOURCE",
            "freshness_reasons": ["DATASET_MANIFEST_INVALID"],
            "availability": "STALE",
        }
    root = Path(processed_root).resolve()
    reasons: list[str] = []
    dataset_id = manifest.get("dataset_id")
    dataset_family = manifest.get("dataset_family")
    battery_id = manifest.get("battery_id")
    experiment_id = manifest.get("experiment_id")
    if (
        isinstance(dataset_id, str)
        and dataset_id.strip()
        and isinstance(dataset_family, str)
        and dataset_family.strip()
        and isinstance(battery_id, str)
        and battery_id.strip()
        and isinstance(experiment_id, str)
        and experiment_id.strip()
    ):
        expected_manifest_path = (
            root
            / "datasets"
            / battery_id
            / experiment_id
            / dataset_family
            / dataset_id
            / "dataset_manifest.json"
        ).resolve()
        if Path(manifest_path).resolve() != expected_manifest_path:
            reasons.append("DATASET_IDENTITY_PATH_MISMATCH")
    else:
        reasons.append("DATASET_IDENTITY_FIELDS_INVALID")
    dataset_path = Path(manifest_path).parent / "dataset.parquet"
    if Path(manifest_path).parent.name != dataset_id:
        reasons.append("DATASET_ID_MISMATCH")
    expected_output_checksum = manifest.get("output_checksum")
    try:
        dataset_path.resolve().relative_to(root)
    except ValueError:
        reasons.append("DATASET_PATH_OUTSIDE_PROCESSED_ROOT")
    if not dataset_path.is_file():
        reasons.append("DATASET_PARQUET_MISSING")
    elif "DATASET_PATH_OUTSIDE_PROCESSED_ROOT" in reasons:
        pass
    elif not _valid_checksum(expected_output_checksum):
        reasons.append("DATASET_CHECKSUM_MISSING_OR_INVALID")
    elif _sha256(dataset_path) != expected_output_checksum.lower():
        reasons.append("DATASET_CHECKSUM_MISMATCH")
    else:
        try:
            dataset_columns = set(pq.read_schema(dataset_path).names)
            identity_columns = ("battery_id", "experiment_id")
            predictor_columns = manifest.get("predictor_columns")
            target_column = manifest.get("target_column")
            if (
                not isinstance(predictor_columns, list)
                or any(
                    not isinstance(column, str) or not column.strip()
                    for column in predictor_columns
                )
                or len(predictor_columns) != len(set(predictor_columns))
                or not isinstance(target_column, str)
                or not target_column.strip()
                or target_column in predictor_columns
                or not set(identity_columns).issubset(dataset_columns)
                or target_column not in dataset_columns
                or not set(predictor_columns).issubset(dataset_columns)
            ):
                reasons.append("DATASET_COLUMN_CONTRACT_MISMATCH")
            else:
                identity_table = pq.read_table(dataset_path, columns=list(identity_columns))
                for column, expected_value in (
                    ("battery_id", battery_id),
                    ("experiment_id", experiment_id),
                ):
                    values = identity_table[column].to_pylist()
                    if not values or any(value != expected_value for value in values):
                        reasons.append("DATASET_ROW_IDENTITY_MISMATCH")
                        break
        except (OSError, ValueError, pa.ArrowException):
            reasons.append("DATASET_SCHEMA_UNREADABLE")

    if not isinstance(battery_id, str) or not battery_id.strip():
        reasons.append("DATASET_BATTERY_ID_MISSING")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        reasons.append("DATASET_EXPERIMENT_ID_MISSING")
    expected_targets = {
        "SOC": "soc_reference_percent",
        "SOH_CAPACITY": "soh_capacity_reference_percent",
    }
    expected_target = (
        expected_targets.get(dataset_family) if isinstance(dataset_family, str) else None
    )
    if (
        expected_target is None
        or manifest.get("target_name") != expected_target
        or manifest.get("target_column") != expected_target
    ):
        reasons.append("DATASET_TARGET_IDENTITY_MISMATCH")
    if (
        isinstance(battery_id, str)
        and battery_id.strip()
        and isinstance(experiment_id, str)
        and experiment_id.strip()
    ):
        reasons.extend(
            f"SOURCE_PROVENANCE_INVALID:{modality.upper()}"
            for modality in invalid_parser_manifest_modalities(root, battery_id, experiment_id)
        )
        if raw_root is not None:
            reasons.extend(
                f"SOURCE_RAW_MISMATCH:{modality.upper()}"
                for modality in parser_manifest_raw_source_mismatches(
                    root, raw_root, battery_id, experiment_id
                )
            )

    for kind, id_key, path_key, checksum_key in (
        ("feature", "feature_set_id", "feature_set_path", "feature_set_checksum"),
        ("label", "label_set_id", "label_set_path", "label_set_checksum"),
    ):
        source_id = manifest.get(id_key)
        source_path = _resolve_processed_path(root, manifest.get(path_key))
        expected_checksum = manifest.get(checksum_key)
        if not isinstance(source_id, str) or not source_id.strip():
            reasons.append(f"{kind.upper()}_SOURCE_ID_MISSING")
        if source_path is None:
            reasons.append(f"{kind.upper()}_SOURCE_PATH_INVALID")
            continue
        try:
            relative_path = source_path.relative_to(root)
        except ValueError:
            reasons.append(f"{kind.upper()}_SOURCE_PATH_OUTSIDE_PROCESSED_ROOT")
            continue
        if (
            isinstance(battery_id, str)
            and isinstance(experiment_id, str)
            and not _has_identity_path(
                relative_path,
                asset_kind=kind,
                battery_id=battery_id,
                experiment_id=experiment_id,
                source_id=source_id if isinstance(source_id, str) else "",
            )
        ):
            reasons.append(f"{kind.upper()}_SOURCE_IDENTITY_MISMATCH")
        if not source_path.is_file():
            reasons.append(f"{kind.upper()}_SOURCE_MISSING")
        elif not _valid_checksum(expected_checksum):
            reasons.append(f"{kind.upper()}_SOURCE_CHECKSUM_MISSING_OR_INVALID")
        elif _sha256(source_path) != expected_checksum.lower():
            reasons.append(f"{kind.upper()}_SOURCE_CHECKSUM_MISMATCH")

        if kind == "feature" and isinstance(battery_id, str) and isinstance(experiment_id, str):
            expected_manifest_path = source_path.parent / "feature_set_manifest.json"
            manifest_reference = _resolve_processed_path(
                root, manifest.get("feature_set_manifest_path")
            )
            manifest_checksum = manifest.get("feature_set_manifest_checksum")
            try:
                expected_manifest_path = expected_manifest_path.resolve(strict=True)
                expected_manifest_path.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                expected_manifest_path = None
                reasons.append("FEATURE_SET_MANIFEST_MISSING")
            if expected_manifest_path is not None and manifest_reference != expected_manifest_path:
                reasons.append("FEATURE_SET_MANIFEST_PROVENANCE_MISSING")
            elif not _valid_checksum(manifest_checksum):
                reasons.append("FEATURE_SET_MANIFEST_CHECKSUM_MISSING_OR_INVALID")
            elif (
                expected_manifest_path is not None
                and _sha256(expected_manifest_path) != manifest_checksum.lower()
            ):
                reasons.append("FEATURE_SET_MANIFEST_CHECKSUM_MISMATCH")
            if expected_manifest_path is not None and expected_manifest_path.is_file():
                try:
                    feature_payload = json.loads(expected_manifest_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    feature_payload = None
                if not isinstance(feature_payload, dict):
                    reasons.append("FEATURE_SET_MANIFEST_INVALID")
                else:
                    if any(
                        feature_payload.get(field) != value
                        for field, value in {
                            "battery_id": battery_id,
                            "experiment_id": experiment_id,
                            "feature_set_id": source_id,
                        }.items()
                    ):
                        reasons.append("FEATURE_SET_MANIFEST_IDENTITY_MISMATCH")
                    output_paths = feature_payload.get("output_paths")
                    output_checksums = feature_payload.get("output_checksums")
                    for output_name, expected_output in (
                        ("features", source_path),
                        ("definitions", expected_manifest_path.parent / "feature_definitions.json"),
                    ):
                        declared_output = (
                            _resolve_processed_path(root, output_paths.get(output_name))
                            if isinstance(output_paths, dict)
                            else None
                        )
                        declared_checksum = (
                            output_checksums.get(output_name)
                            if isinstance(output_checksums, dict)
                            else None
                        )
                        if (
                            declared_output != expected_output
                            or not _valid_checksum(declared_checksum)
                            or not expected_output.is_file()
                            or _sha256(expected_output) != str(declared_checksum).lower()
                        ):
                            reasons.append("FEATURE_SET_MANIFEST_OUTPUT_MISMATCH")
                            break
                    for path_key, checksum_key, input_name in (
                        ("analysis_slice_path", "analysis_slice_checksum", "ANALYSIS_SLICE"),
                        ("waveform_store_path", "waveform_store_checksum", "WAVEFORM_STORE"),
                    ):
                        input_path = _resolve_processed_path(root, feature_payload.get(path_key))
                        input_checksum = feature_payload.get(checksum_key)
                        if input_path is None:
                            reasons.append(f"FEATURE_SET_{input_name}_PATH_INVALID")
                        elif not _valid_checksum(input_checksum):
                            reasons.append(f"FEATURE_SET_{input_name}_CHECKSUM_MISSING_OR_INVALID")
                        elif not input_path.exists() or not (
                            input_path.is_file() or input_path.is_dir()
                        ):
                            reasons.append(f"FEATURE_SET_{input_name}_MISSING")
                        elif (
                            feature_waveform_store_sha256(input_path)
                            if input_name == "WAVEFORM_STORE"
                            else content_sha256(input_path)
                        ) != input_checksum.lower():
                            reasons.append(f"FEATURE_SET_{input_name}_CHECKSUM_MISMATCH")

        if kind == "label" and isinstance(battery_id, str) and isinstance(experiment_id, str):
            expected_manifest_reference = (
                root / "labels" / battery_id / experiment_id / "label_manifest.json"
            )
            try:
                expected_manifest_path = expected_manifest_reference.resolve(strict=True)
                expected_manifest_path.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                expected_manifest_path = None
                reasons.append("LABEL_SET_MANIFEST_MISSING")
            manifest_reference = manifest.get("label_set_manifest_path")
            label_manifest_path = _resolve_processed_path(root, manifest_reference)
            manifest_checksum = manifest.get("label_set_manifest_checksum")
            if expected_manifest_path is not None and (
                label_manifest_path is None or label_manifest_path != expected_manifest_path
            ):
                reasons.append("LABEL_SET_MANIFEST_PROVENANCE_MISSING")
            elif not _valid_checksum(manifest_checksum):
                reasons.append("LABEL_SET_MANIFEST_CHECKSUM_MISSING_OR_INVALID")
            elif expected_manifest_path is not None and not expected_manifest_path.is_file():
                reasons.append("LABEL_SET_MANIFEST_MISSING")
            elif (
                expected_manifest_path is not None
                and _sha256(expected_manifest_path) != manifest_checksum.lower()
            ):
                reasons.append("LABEL_SET_MANIFEST_CHECKSUM_MISMATCH")
            if expected_manifest_path is not None and expected_manifest_path.is_file():
                try:
                    label_payload = json.loads(expected_manifest_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    label_payload = None
                if not isinstance(label_payload, dict):
                    reasons.append("LABEL_SET_MANIFEST_INVALID")
                else:
                    if any(
                        label_payload.get(field) != value
                        for field, value in {
                            "battery_id": battery_id,
                            "experiment_id": experiment_id,
                            "label_set_id": source_id,
                        }.items()
                    ):
                        reasons.append("LABEL_SET_MANIFEST_IDENTITY_MISMATCH")
                    if label_payload.get("label_engine_name") == "reference_label_engine":
                        from battery_workbench.labels.schemas import LabelConfig

                        current_label_config = LabelConfig()
                        if label_payload.get("label_engine_version") != current_label_config.version:
                            reasons.append("LABEL_SET_ENGINE_VERSION_UNSUPPORTED")
                        if (
                            label_payload.get("label_definition_version")
                            != current_label_config.label_definition_version
                        ):
                            reasons.append("LABEL_SET_DEFINITION_VERSION_UNSUPPORTED")
                        try:
                            from battery_workbench.labels.builder import (
                                validate_reference_label_inputs,
                            )

                            validate_reference_label_inputs(
                                measurement_events_path=(
                                    root
                                    / "multimodal"
                                    / str(battery_id)
                                    / str(experiment_id)
                                    / "measurement_events.parquet"
                                ),
                                records_path=(
                                    root
                                    / "electrical"
                                    / str(battery_id)
                                    / str(experiment_id)
                                    / "records.parquet"
                                ),
                                cycles_path=(
                                    root
                                    / "electrical"
                                    / str(battery_id)
                                    / str(experiment_id)
                                    / "cycles.parquet"
                                ),
                                steps_path=(
                                    root
                                    / "electrical"
                                    / str(battery_id)
                                    / str(experiment_id)
                                    / "steps.parquet"
                                ),
                                expected_battery_id=str(battery_id),
                                expected_experiment_id=str(experiment_id),
                            )
                        except (OSError, ValueError, KeyError, TypeError, ArrowException):
                            reasons.append("LABEL_INPUT_SEMANTICS_INVALID")
                    output_paths = label_payload.get("output_paths")
                    output_checksums = label_payload.get("output_checksums")
                    for output_name, expected_output in (
                        ("event_labels", source_path),
                        ("cycle_labels", source_path.parent / "cycle_labels.parquet"),
                    ):
                        declared_output = (
                            _resolve_processed_path(root, output_paths.get(output_name))
                            if isinstance(output_paths, dict)
                            else None
                        )
                        declared_checksum = (
                            output_checksums.get(output_name)
                            if isinstance(output_checksums, dict)
                            else None
                        )
                        if (
                            declared_output != expected_output
                            or not _valid_checksum(declared_checksum)
                            or not expected_output.is_file()
                            or _sha256(expected_output) != str(declared_checksum).lower()
                        ):
                            reasons.append("LABEL_SET_MANIFEST_OUTPUT_MISMATCH")
                            break

    selected_features = manifest.get("selected_features") or []
    if isinstance(selected_features, list) and "tof_us" in selected_features:
        expected_tof_manifest = (
            root
            / "features_physical"
            / str(battery_id)
            / str(experiment_id)
            / "canonical_tof_manifest.json"
        ).resolve()
        expected_tof_data = expected_tof_manifest.parent / "canonical_tof.parquet"
        tof_manifest = _resolve_processed_path(root, manifest.get("canonical_tof_manifest_path"))
        tof_checksum = manifest.get("canonical_tof_manifest_checksum")
        tof_data = _resolve_processed_path(root, manifest.get("canonical_tof_path"))
        tof_data_checksum = manifest.get("canonical_tof_checksum")
        if tof_manifest is None or tof_data is None or not _valid_checksum(tof_checksum):
            reasons.append("CANONICAL_TOF_PROVENANCE_MISSING")
        elif tof_manifest != expected_tof_manifest or tof_data != expected_tof_data.resolve():
            reasons.append("CANONICAL_TOF_PATH_NONCANONICAL")
        elif not tof_manifest.is_file() or _sha256(tof_manifest) != tof_checksum.lower():
            reasons.append("CANONICAL_TOF_MANIFEST_CHECKSUM_MISMATCH")
        elif (
            not tof_data.is_file()
            or not _valid_checksum(tof_data_checksum)
            or _sha256(tof_data) != tof_data_checksum.lower()
        ):
            reasons.append("CANONICAL_TOF_CHECKSUM_MISMATCH")
        else:
            try:
                tof_manifest_payload = json.loads(tof_manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                tof_manifest_payload = {}
            if not isinstance(tof_manifest_payload, dict):
                tof_manifest_payload = {}
            if tof_manifest_payload.get("feature_set_id") != manifest.get("feature_set_id"):
                reasons.append("CANONICAL_TOF_FEATURE_SET_MISMATCH")
            if tof_manifest_payload.get("parameter_set_id") != manifest.get("parameter_set_id"):
                reasons.append("CANONICAL_TOF_PARAMETER_SET_MISMATCH")
            if tof_manifest_payload.get("tof_method_id") != manifest.get("tof_method_id"):
                reasons.append("CANONICAL_TOF_METHOD_MISMATCH")
            from battery_workbench.features_physical.canonical_tof import (
                canonical_tof_integrity_reasons,
            )

            reasons.extend(
                "CANONICAL_TOF_INTEGRITY_INVALID:" + reason
                for reason in canonical_tof_integrity_reasons(
                    root, str(battery_id), str(experiment_id)
                )
            )

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "freshness_status": "FRESH" if not unique_reasons else "STALE_SOURCE",
        "freshness_reasons": unique_reasons,
        "availability": "AVAILABLE" if not unique_reasons else "STALE",
    }


def _valid_checksum(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value.lower())
    )

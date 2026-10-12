"""Immutable, manifest-driven harmonized cohort dataset materialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from battery_workbench.datasets.cohort_schemas import (
    COHORT_RESERVED_COLUMNS,
    CohortDatasetRequest,
)
from battery_workbench.datasets.freshness import dataset_freshness


class CohortMaterializationError(ValueError):
    """Source datasets cannot be safely combined under the requested mapping."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _feature_definition_payload_for_id(processed_root: Path, feature_set_id: str) -> dict[str, Any]:
    paths = [
        path
        for path in (processed_root / "features").rglob("feature_definitions.json")
        if path.parent.name == feature_set_id
    ]
    if not paths:
        return {}
    try:
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    except (OSError, json.JSONDecodeError) as exc:
        raise CohortMaterializationError(
            f"feature set {feature_set_id!r} has an unreadable or invalid definition manifest"
        ) from exc
    for payload in payloads:
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
            for item in features
        ):
            raise CohortMaterializationError(
                f"feature set {feature_set_id!r} has an invalid definition structure"
            )
    if len({_canonical_json(payload) for payload in payloads}) != 1:
        raise CohortMaterializationError(
            f"feature set {feature_set_id!r} resolves to conflicting definitions"
        )
    return payloads[0]


def _feature_definitions_for_id(processed_root: Path, feature_set_id: str) -> dict[str, Any]:
    payload = _feature_definition_payload_for_id(processed_root, feature_set_id)
    return {item.get("name"): item for item in payload.get("features", []) if item.get("name")}


def _feature_semantics(definition: dict[str, Any]) -> dict[str, Any]:
    """Return the scientific definition fields used for cross-source equivalence."""
    return {
        key: value
        for key, value in definition.items()
        if key not in {"name", "description", "display_name", "display_name_en", "display_name_zh"}
    }


def _feature_semantics_signature(definition: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_feature_semantics(definition)).encode()).hexdigest()


def list_dataset_catalogue(
    processed_root: Path, *, raw_root: Path | None = None
) -> list[dict[str, Any]]:
    """Return sanitized source-dataset metadata suitable for cohort selection."""
    root = Path(processed_root) / "datasets"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("dataset_manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                continue
            feature_set_id = str(manifest.get("feature_set_id", ""))
            freshness = dataset_freshness(
                Path(processed_root), path, manifest, raw_root=raw_root
            )
            source_integrity_invalid = any(
                reason.startswith(("SOURCE_PROVENANCE_INVALID:", "SOURCE_RAW_MISMATCH:"))
                for reason in freshness["freshness_reasons"]
            )
            definitions = (
                _feature_definitions_for_id(Path(processed_root), feature_set_id)
                if feature_set_id
                else {}
            )
            items.append(
                {
                    "dataset_id": manifest.get("dataset_id", path.parent.name),
                    "dataset_family": manifest.get("dataset_family", ""),
                    "dataset_status": (
                        manifest.get("dataset_status", "")
                        if freshness["freshness_status"] == "FRESH"
                        else "STALE_SOURCE"
                    ),
                    "freshness_status": freshness["freshness_status"],
                    "freshness_reasons": freshness["freshness_reasons"],
                    "source_integrity_status": (
                        "INTEGRITY_BLOCKED" if source_integrity_invalid else None
                    ),
                    "battery_id": manifest.get("battery_id", ""),
                    "experiment_id": manifest.get("experiment_id", ""),
                    "target_column": manifest.get("target_column", ""),
                    "target_method_version": manifest.get("target_method_version", ""),
                    "soc_label_temporality": manifest.get("soc_label_temporality"),
                    "predictor_columns": manifest.get("predictor_columns", []),
                    "feature_definitions": [
                        {
                            "name": name,
                            "version": definition.get("version", ""),
                            "unit": definition.get("unit", ""),
                            "definition_signature": _feature_semantics_signature(definition),
                        }
                        for name, definition in sorted(definitions.items())
                    ],
                    "eligible_rows": (
                        None if source_integrity_invalid else manifest.get("eligible_rows", 0)
                    ),
                }
            )
        except (OSError, json.JSONDecodeError, CohortMaterializationError):
            continue
    return items


def cohort_version_id(
    request: CohortDatasetRequest, source_artifacts: dict[str, dict[str, str]]
) -> str:
    """Derive immutable identity from mappings and exact source fingerprints."""
    request_payload = request.model_dump(mode="json")
    request_payload["source_datasets"] = sorted(
        request_payload["source_datasets"], key=lambda item: item["source_dataset_id"]
    )
    request_payload["feature_mappings"] = sorted(
        request_payload["feature_mappings"], key=lambda item: item["canonical_feature_id"]
    )
    request_payload["evidence_refs"] = sorted(request_payload["evidence_refs"])
    canonical = {"request": request_payload, "source_artifacts": source_artifacts}
    digest = hashlib.sha256(_canonical_json(canonical).encode()).hexdigest()
    return f"COHORT::{digest[:24]}"


def _load_source(
    processed_root: Path, source_id: str, *, raw_root: Path | None = None
) -> tuple[dict[str, Any], Path, pd.DataFrame]:
    matches = [
        path
        for path in (processed_root / "datasets").rglob("dataset_manifest.json")
        if path.parent.name == source_id
    ]
    if len(matches) != 1:
        raise CohortMaterializationError(
            f"source dataset {source_id!r} must resolve to exactly one manifest"
        )
    manifest_path = matches[0]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CohortMaterializationError(
            f"source dataset {source_id!r} has an unreadable or invalid manifest"
        ) from exc
    if not isinstance(manifest, dict):
        raise CohortMaterializationError(f"source dataset {source_id!r} manifest is not an object")
    freshness = dataset_freshness(
        processed_root, manifest_path, manifest, raw_root=raw_root
    )
    if freshness["freshness_status"] != "FRESH":
        raise CohortMaterializationError(
            f"source dataset {source_id!r} is stale: {', '.join(freshness['freshness_reasons'])}"
        )
    manifest["_source_manifest_checksum"] = _sha256(manifest_path)
    feature_set_id = manifest.get("feature_set_id")
    if feature_set_id:
        definitions_payload = _feature_definition_payload_for_id(processed_root, feature_set_id)
        definitions = {
            item.get("name"): item
            for item in definitions_payload.get("features", [])
            if item.get("name")
        }
        if definitions_payload:
            manifest["_feature_definitions_checksum"] = hashlib.sha256(
                _canonical_json(definitions_payload).encode()
            ).hexdigest()
            manifest["_feature_definitions"] = definitions
    parquet_path = manifest_path.parent / "dataset.parquet"
    if not parquet_path.is_file():
        raise CohortMaterializationError(
            f"source dataset {source_id!r} has no materialized Parquet"
        )
    expected_checksum = manifest.get("output_checksum")
    if (
        not isinstance(expected_checksum, str)
        or len(expected_checksum) != 64
        or any(char not in "0123456789abcdef" for char in expected_checksum.lower())
    ):
        raise CohortMaterializationError(
            f"source dataset {source_id!r} has no valid output checksum"
        )
    if _sha256(parquet_path) != expected_checksum.lower():
        raise CohortMaterializationError(f"source dataset {source_id!r} checksum mismatch")
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:
        raise CohortMaterializationError(
            f"source dataset {source_id!r} Parquet cannot be read"
        ) from exc
    return manifest, parquet_path, frame


def _validate_source_identity(source: Any, manifest: dict[str, Any], frame: pd.DataFrame) -> None:
    for key in ("dataset_id", "battery_id", "experiment_id"):
        requested = getattr(source, "source_dataset_id" if key == "dataset_id" else key)
        if manifest.get(key) != requested:
            raise CohortMaterializationError(
                f"source {source.source_dataset_id!r} {key} does not match its manifest"
            )
    if manifest.get("dataset_family") != "SOC":
        raise CohortMaterializationError("only SOC source datasets are currently supported")
    if manifest.get("dataset_status") not in ("READY_FOR_SPLIT", "READY_WITH_LIMITATIONS"):
        raise CohortMaterializationError(
            f"source {source.source_dataset_id!r} is not ready for split"
        )
    if "measurement_event_id" not in frame or frame["measurement_event_id"].isna().any():
        raise CohortMaterializationError("source rows require non-null measurement_event_id")
    if frame["measurement_event_id"].astype(str).duplicated().any():
        raise CohortMaterializationError("source measurement_event_id values must be unique")
    for key in ("battery_id", "experiment_id"):
        if (
            key not in frame
            or frame[key].isna().any()
            or set(frame[key].astype(str)) != {getattr(source, key)}
        ):
            raise CohortMaterializationError(f"source rows have inconsistent {key}")


def build_cohort_frame(
    request: CohortDatasetRequest,
    sources: dict[str, tuple[dict[str, Any], pd.DataFrame]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate source metadata and combine rows using only declared mappings."""
    reserved_columns = COHORT_RESERVED_COLUMNS | {request.target_mapping.canonical_target_id}
    collisions = sorted(
        mapping.canonical_feature_id
        for mapping in request.feature_mappings
        if mapping.canonical_feature_id in reserved_columns
    )
    if collisions:
        raise CohortMaterializationError(
            f"canonical feature ids cannot replace cohort identity or target columns: {collisions}"
        )
    if set(sources) != {source.source_dataset_id for source in request.source_datasets}:
        raise CohortMaterializationError("resolved source set differs from request")
    target_methods: set[tuple[str, str | None]] = set()
    feature_signatures: dict[str, set[str]] = {}
    frames: list[pd.DataFrame] = []
    source_checksums: dict[str, str] = {}
    for source in sorted(request.source_datasets, key=lambda item: item.source_dataset_id):
        manifest, source_frame = sources[source.source_dataset_id]
        _validate_source_identity(source, manifest, source_frame)
        target_methods.add(
            (str(manifest.get("target_method_version", "")), manifest.get("soc_label_temporality"))
        )
        if request.target_mapping.method_version != str(manifest.get("target_method_version", "")):
            raise CohortMaterializationError(
                "declared target method version does not match source SOC provenance"
            )
        source_target = request.target_mapping.source_target_ids[source.source_dataset_id]
        target_column = manifest.get("target_column") or source_target
        if target_column != "soc_reference_percent" or source_target not in (
            target_column,
            "reference_soc_percent",
        ):
            raise CohortMaterializationError(
                "V1 cohorts require the manifest-backed retrospective reference SOC target"
            )
        if target_column not in source_frame:
            raise CohortMaterializationError(f"source target column {target_column!r} is missing")
        renamed = pd.DataFrame(
            {
                "measurement_event_id": source_frame["measurement_event_id"].map(
                    lambda value, item=source: (
                        f"COHORT_EVENT::{item.battery_id}::{item.experiment_id}::"
                        f"{item.source_dataset_id}::{value}"
                    )
                ),
                "source_measurement_event_id": source_frame["measurement_event_id"].astype(str),
                "battery_id": source.battery_id,
                "experiment_id": source.experiment_id,
                "source_dataset_id": source.source_dataset_id,
                request.target_mapping.canonical_target_id: source_frame[target_column],
            }
        )
        for mapping in sorted(request.feature_mappings, key=lambda item: item.canonical_feature_id):
            feature_id = mapping.source_feature_ids[source.source_dataset_id]
            canonical_unit = request.unit_mapping[mapping.canonical_feature_id]
            definition = manifest.get("_feature_definitions", {}).get(feature_id)
            if not definition:
                raise CohortMaterializationError(
                    f"source feature {feature_id!r} has no trusted unit/version definition"
                )
            declared_source_unit = canonical_unit.source_units[source.source_dataset_id]
            actual_unit = str(definition.get("unit", ""))
            actual_version = str(definition.get("version", ""))
            if not actual_unit or declared_source_unit != actual_unit:
                raise CohortMaterializationError(
                    f"declared unit for {feature_id!r} does not match its definition"
                )
            if canonical_unit.canonical_unit != actual_unit:
                raise CohortMaterializationError(
                    "unit conversion is not implemented; all source units must exactly match the canonical unit"
                )
            if not actual_version or mapping.method_version != actual_version:
                raise CohortMaterializationError(
                    f"declared feature method version for {feature_id!r} does not match its definition"
                )
            feature_signatures.setdefault(mapping.canonical_feature_id, set()).add(
                _feature_semantics_signature(definition)
            )
            if feature_id not in source_frame:
                raise CohortMaterializationError(
                    f"source feature {feature_id!r} is absent from {source.source_dataset_id!r}"
                )
            if feature_id not in manifest.get("predictor_columns", []):
                raise CohortMaterializationError(
                    f"source feature {feature_id!r} is not an approved predictor"
                )
            renamed[mapping.canonical_feature_id] = source_frame[feature_id]
        if renamed.isna().any().any():
            raise CohortMaterializationError(
                f"source {source.source_dataset_id!r} has null cohort target/features"
            )
        numeric_columns = [
            request.target_mapping.canonical_target_id,
            *sorted(mapping.canonical_feature_id for mapping in request.feature_mappings),
        ]
        for column in numeric_columns:
            try:
                values = pd.to_numeric(renamed[column], errors="raise").to_numpy(dtype="float64")
            except (TypeError, ValueError, OverflowError) as exc:
                raise CohortMaterializationError(
                    f"source {source.source_dataset_id!r} cohort column {column!r} must be numeric"
                ) from exc
            if not np.isfinite(values).all():
                raise CohortMaterializationError(
                    f"source {source.source_dataset_id!r} cohort column {column!r} "
                    "must contain only finite values"
                )
        frames.append(renamed)
        source_checksums[source.source_dataset_id] = str(manifest.get("output_checksum", ""))

    if len(target_methods) != 1 or not next(iter(target_methods))[0]:
        raise CohortMaterializationError(
            "SOC formula version and label temporality must be present and identical"
        )
    incompatible_features = sorted(
        feature_id for feature_id, signatures in feature_signatures.items() if len(signatures) != 1
    )
    if incompatible_features:
        raise CohortMaterializationError(
            "source feature definitions are not semantically equivalent for canonical feature(s): "
            f"{incompatible_features}"
        )
    cohort_frame = pd.concat(frames, ignore_index=True)
    if cohort_frame["measurement_event_id"].duplicated().any():
        raise CohortMaterializationError("cohort measurement_event_id values must be unique")
    provenance = {
        "source_checksums": source_checksums,
        "target_method_version": next(iter(target_methods))[0],
        "soc_label_temporality": next(iter(target_methods))[1],
        "row_count": len(cohort_frame),
        "battery_count": cohort_frame["battery_id"].nunique(),
        "predictor_columns": sorted(
            mapping.canonical_feature_id for mapping in request.feature_mappings
        ),
        "target_column": request.target_mapping.canonical_target_id,
    }
    return cohort_frame, provenance


def materialize_cohort_dataset(
    *, request: CohortDatasetRequest, processed_root: Path, raw_root: Path | None = None
) -> dict[str, Any]:
    """Resolve immutable source datasets and persist a versioned cohort artifact."""
    processed_root = Path(processed_root)
    loaded: dict[str, tuple[dict[str, Any], pd.DataFrame]] = {}
    source_artifacts: dict[str, dict[str, str]] = {}
    for source in request.source_datasets:
        manifest, parquet_path, frame = _load_source(
            processed_root, source.source_dataset_id, raw_root=raw_root
        )
        loaded[source.source_dataset_id] = (manifest, frame)
        source_artifacts[source.source_dataset_id] = {
            "dataset_checksum": _sha256(parquet_path),
            "source_manifest_checksum": str(manifest.get("_source_manifest_checksum", "")),
            "feature_definitions_checksum": str(manifest.get("_feature_definitions_checksum", "")),
        }
    cohort_frame, provenance = build_cohort_frame(request, loaded)
    cohort_dataset_id = cohort_version_id(request, source_artifacts)
    output_dir = processed_root / "cohorts" / request.cohort_id / cohort_dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "cohort_dataset.parquet"
    manifest_path = output_dir / "cohort_manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("cohort_dataset_id") != cohort_dataset_id:
            raise CohortMaterializationError("existing cohort artifact identity mismatch")
        return existing
    cohort_frame.to_parquet(parquet_path, index=False)
    manifest = {
        "contract_version": request.contract_version,
        "artifact_type": "COHORT_DATASET",
        "cohort_id": request.cohort_id,
        "cohort_dataset_id": cohort_dataset_id,
        "cohort_version": cohort_dataset_id,
        "status": "READY_FOR_BATTERY_SPLIT",
        # Battery IDs are declarations from source dataset manifests. V1 has no
        # reviewed entity-identity evidence registry, so this must not unlock
        # scientific cross-battery generalization readiness.
        "identity_verification_status": "NOT_ASSESSED",
        "scientific_generalization_eligible": False,
        "group_column": request.group_column,
        "source_datasets": [
            item.model_dump(mode="json")
            for item in sorted(request.source_datasets, key=lambda item: item.source_dataset_id)
        ],
        "source_artifacts": source_artifacts,
        "target_mapping": request.target_mapping.model_dump(mode="json"),
        "feature_mappings": [
            item.model_dump(mode="json")
            for item in sorted(request.feature_mappings, key=lambda item: item.canonical_feature_id)
        ],
        "unit_mapping": {
            key: value.model_dump(mode="json") for key, value in request.unit_mapping.items()
        },
        "harmonization_method_version": request.harmonization_method_version,
        "harmonization_policy_id": request.harmonization_policy_id,
        "evidence_refs": request.evidence_refs,
        **provenance,
        "output_path": str(parquet_path.relative_to(processed_root)),
        "output_checksum": _sha256(parquet_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def eligible_cohort_for_experiment(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    *,
    raw_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return only cohorts with independently reviewed physical identity evidence.

    The current V1 materializer only carries operator-declared Battery IDs. No
    trusted review registry exists yet, so ordinary materialized cohorts are
    intentionally excluded from scientific readiness.
    """
    for path in sorted((Path(processed_root) / "cohorts").rglob("cohort_manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            parquet_path = path.parent / "cohort_dataset.parquet"
            sources = manifest.get("source_datasets", [])
            contains_experiment = any(
                item.get("battery_id") == battery_id and item.get("experiment_id") == experiment_id
                for item in sources
            )
            if (
                contains_experiment
                and manifest.get("status") == "READY_FOR_BATTERY_SPLIT"
                and manifest.get("identity_verification_status") == "VERIFIED"
                and manifest.get("scientific_generalization_eligible") is True
                and manifest.get("battery_count", 0) >= 2
                and parquet_path.is_file()
                and _sha256(parquet_path) == manifest.get("output_checksum")
                and cohort_sources_current(Path(processed_root), manifest, raw_root=raw_root)
            ):
                return manifest
        except (OSError, json.JSONDecodeError):
            continue
    return None


def cohort_sources_current(
    processed_root: Path,
    cohort_manifest: dict[str, Any],
    *,
    raw_root: Path | None = None,
) -> bool:
    """Check captured source checksums; changed sources make the cohort stale."""
    if not isinstance(cohort_manifest, dict):
        return False
    sources = cohort_manifest.get("source_datasets")
    source_artifacts = cohort_manifest.get("source_artifacts")
    if not isinstance(sources, list) or not isinstance(source_artifacts, dict):
        return False
    source_ids = [
        item.get("source_dataset_id")
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("source_dataset_id"), str)
    ]
    battery_ids = [
        item.get("battery_id")
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("battery_id"), str)
    ]
    experiment_ids = [
        item.get("experiment_id")
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("experiment_id"), str)
    ]
    battery_experiment_pairs = list(zip(battery_ids, experiment_ids, strict=False))
    if (
        len(source_ids) < 2
        or len(source_ids) != len(sources)
        or len(set(source_ids)) != len(source_ids)
        or len(battery_ids) != len(sources)
        or len(experiment_ids) != len(sources)
        or any(not isinstance(source_id, str) or not source_id.strip() for source_id in source_ids)
        or any(
            not isinstance(battery_id, str) or not battery_id.strip() for battery_id in battery_ids
        )
        or any(not isinstance(experiment_id, str) or not experiment_id.strip() for experiment_id in experiment_ids)
        or len(set(battery_experiment_pairs)) != len(sources)
        or len(set(battery_ids)) < 2
        or set(source_artifacts) != set(source_ids)
        or cohort_manifest.get("battery_count") != len(set(battery_ids))
        or cohort_manifest.get("group_column") != "battery_id"
    ):
        return False
    for expected in source_artifacts.values():
        if not isinstance(expected, dict):
            return False
        for checksum_key in ("dataset_checksum", "source_manifest_checksum"):
            checksum = expected.get(checksum_key)
            if (
                not isinstance(checksum, str)
                or len(checksum) != 64
                or any(char not in "0123456789abcdef" for char in checksum.lower())
            ):
                return False
        feature_checksum = expected.get("feature_definitions_checksum", "")
        if feature_checksum and (
            not isinstance(feature_checksum, str)
            or len(feature_checksum) != 64
            or any(char not in "0123456789abcdef" for char in feature_checksum.lower())
        ):
            return False
    output_reference = cohort_manifest.get("output_path")
    if not isinstance(output_reference, str):
        return False
    output_rel = Path(output_reference)
    if output_rel.is_absolute() or ".." in output_rel.parts:
        return False
    try:
        request = CohortDatasetRequest.model_validate(
            {
                "contract_version": cohort_manifest.get("contract_version"),
                "cohort_id": cohort_manifest.get("cohort_id"),
                "source_datasets": sources,
                "target_mapping": cohort_manifest.get("target_mapping"),
                "feature_mappings": cohort_manifest.get("feature_mappings"),
                "unit_mapping": cohort_manifest.get("unit_mapping"),
                "harmonization_method_version": cohort_manifest.get("harmonization_method_version"),
                "harmonization_policy_id": cohort_manifest.get("harmonization_policy_id"),
                "evidence_refs": cohort_manifest.get("evidence_refs"),
                "group_column": cohort_manifest.get("group_column"),
            }
        )
    except (TypeError, ValueError):
        return False
    version_id = cohort_version_id(request, source_artifacts)
    if (
        cohort_manifest.get("cohort_dataset_id") != version_id
        or cohort_manifest.get("cohort_version") != version_id
        or cohort_manifest.get("cohort_id") != request.cohort_id
        or output_rel != Path("cohorts") / request.cohort_id / version_id / "cohort_dataset.parquet"
        or cohort_manifest.get("identity_verification_status") != "NOT_ASSESSED"
        or cohort_manifest.get("scientific_generalization_eligible") is not False
    ):
        return False
    output_path = (Path(processed_root) / output_rel).resolve()
    if (
        Path(processed_root).resolve() not in output_path.parents
        or not output_path.is_file()
        or _sha256(output_path) != cohort_manifest.get("output_checksum")
    ):
        return False
    for source_id, expected in source_artifacts.items():
        matches = [
            path
            for path in (Path(processed_root) / "datasets").rglob("dataset_manifest.json")
            if path.parent.name == source_id
        ]
        if len(matches) != 1:
            return False
        manifest_path = matches[0]
        try:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(source_manifest, dict):
                return False
            parquet_path = manifest_path.parent / "dataset.parquet"
            if (
                dataset_freshness(
                    Path(processed_root), manifest_path, source_manifest, raw_root=raw_root
                )[
                    "freshness_status"
                ]
                != "FRESH"
                or not parquet_path.is_file()
                or _sha256(parquet_path) != expected.get("dataset_checksum")
                or _sha256(manifest_path) != expected.get("source_manifest_checksum")
            ):
                return False
            feature_set_id = source_manifest.get("feature_set_id")
            if expected.get("feature_definitions_checksum"):
                payload = _feature_definition_payload_for_id(Path(processed_root), feature_set_id)
                if not payload:
                    return False
                actual = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
                if actual != expected.get("feature_definitions_checksum"):
                    return False
        except (OSError, json.JSONDecodeError):
            return False
    return bool(source_artifacts)


def cohort_source_integrity_reasons(
    processed_root: Path,
    cohort_manifest: dict[str, Any],
    *,
    raw_root: Path | None = None,
) -> list[str]:
    """Return parser-provenance failures inherited from source datasets."""
    if not isinstance(cohort_manifest, dict):
        return []
    sources = cohort_manifest.get("source_datasets")
    if not isinstance(sources, list):
        return []
    root = Path(processed_root)
    reasons: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_dataset_id")
        if not isinstance(source_id, str):
            continue
        manifests = [
            path
            for path in (root / "datasets").rglob("dataset_manifest.json")
            if path.parent.name == source_id
        ]
        if len(manifests) != 1:
            continue
        try:
            dataset_manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        freshness = dataset_freshness(
            root, manifests[0], dataset_manifest, raw_root=raw_root
        )
        reasons.update(
            f"{source_id}:{reason}"
            for reason in freshness["freshness_reasons"]
            if reason.startswith(("SOURCE_PROVENANCE_INVALID:", "SOURCE_RAW_MISMATCH:"))
        )
    return sorted(reasons)

"""Immutable, manifest-driven harmonized cohort dataset materialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.datasets.cohort_schemas import (
    COHORT_RESERVED_COLUMNS,
    CohortDatasetRequest,
)


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
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
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


def list_dataset_catalogue(processed_root: Path) -> list[dict[str, Any]]:
    """Return sanitized source-dataset metadata suitable for cohort selection."""
    root = Path(processed_root) / "datasets"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("dataset_manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            feature_set_id = str(manifest.get("feature_set_id", ""))
            definitions = (
                _feature_definitions_for_id(Path(processed_root), feature_set_id)
                if feature_set_id
                else {}
            )
            items.append(
                {
                    "dataset_id": manifest.get("dataset_id", path.parent.name),
                    "dataset_family": manifest.get("dataset_family", ""),
                    "dataset_status": manifest.get("dataset_status", ""),
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
                    "eligible_rows": manifest.get("eligible_rows", 0),
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


def _load_source(processed_root: Path, source_id: str) -> tuple[dict[str, Any], Path, pd.DataFrame]:
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    if expected_checksum and _sha256(parquet_path) != expected_checksum:
        raise CohortMaterializationError(f"source dataset {source_id!r} checksum mismatch")
    return manifest, parquet_path, pd.read_parquet(parquet_path)


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
                    lambda value, battery_id=source.battery_id: (
                        f"COHORT_EVENT::{battery_id}::{value}"
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
    *, request: CohortDatasetRequest, processed_root: Path
) -> dict[str, Any]:
    """Resolve immutable source datasets and persist a versioned cohort artifact."""
    processed_root = Path(processed_root)
    loaded: dict[str, tuple[dict[str, Any], pd.DataFrame]] = {}
    source_artifacts: dict[str, dict[str, str]] = {}
    for source in request.source_datasets:
        manifest, parquet_path, frame = _load_source(processed_root, source.source_dataset_id)
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
    processed_root: Path, battery_id: str, experiment_id: str
) -> dict[str, Any] | None:
    """Return a checksum-verified cohort containing this exact experiment source."""
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
                and manifest.get("battery_count", 0) >= 2
                and parquet_path.is_file()
                and _sha256(parquet_path) == manifest.get("output_checksum")
                and cohort_sources_current(Path(processed_root), manifest)
            ):
                return manifest
        except (OSError, json.JSONDecodeError):
            continue
    return None


def cohort_sources_current(processed_root: Path, cohort_manifest: dict[str, Any]) -> bool:
    """Check captured source checksums; changed sources make the cohort stale."""
    output_rel = Path(cohort_manifest.get("output_path", ""))
    if output_rel.is_absolute() or ".." in output_rel.parts:
        return False
    output_path = (Path(processed_root) / output_rel).resolve()
    if (
        Path(processed_root).resolve() not in output_path.parents
        or not output_path.is_file()
        or _sha256(output_path) != cohort_manifest.get("output_checksum")
    ):
        return False
    source_artifacts = cohort_manifest.get("source_artifacts", {})
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
            parquet_path = manifest_path.parent / "dataset.parquet"
            if (
                not parquet_path.is_file()
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

"""Fail-closed discovery of materialized independent validation evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

_READY_DATASET_STATUSES = {"READY_FOR_SPLIT", "READY_WITH_LIMITATIONS"}
_REQUIRED_ROLES = {"TRAIN", "VALIDATION", "HELD_OUT"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            return False
        current = current.parent
    return path.is_file() and not path.is_symlink()


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("manifest is not a JSON object")
    return value


def _validate_assignments(
    assignments: pd.DataFrame, dataset: pd.DataFrame, group_column: str
) -> dict[str, int]:
    required = {"measurement_event_id", "fold", "role", group_column}
    if not required.issubset(assignments.columns):
        raise ValueError("split assignments are missing required columns")
    if assignments[list(required)].isna().any().any():
        raise ValueError("split assignments contain null identity or role values")
    roles = set(assignments["role"].astype(str))
    if roles != _REQUIRED_ROLES:
        raise ValueError("split does not contain exactly TRAIN, VALIDATION, HELD_OUT")
    if assignments["fold"].nunique() != 1:
        raise ValueError("nested tuning evidence requires one fixed outer fold")
    if assignments["measurement_event_id"].duplicated().any():
        raise ValueError("split assignments contain duplicate event ids")
    if "measurement_event_id" not in dataset.columns:
        raise ValueError("dataset is missing measurement_event_id")
    if dataset["measurement_event_id"].isna().any() or dataset["measurement_event_id"].duplicated().any():
        raise ValueError("source dataset contains null or duplicate event ids")
    dataset_ids = set(dataset["measurement_event_id"].astype(str))
    assignment_ids = set(assignments["measurement_event_id"].astype(str))
    if not dataset_ids or dataset_ids != assignment_ids:
        raise ValueError("split event ids do not exactly match the source dataset")
    role_groups: dict[str, set[str]] = {}
    for role, frame in assignments.groupby("role"):
        role_groups[str(role)] = set(frame[group_column].astype(str))
    if any(role_groups[a] & role_groups[b] for a, b in (("TRAIN", "VALIDATION"), ("TRAIN", "HELD_OUT"), ("VALIDATION", "HELD_OUT"))):
        raise ValueError("group identity overlaps across split roles")
    counts = {role: len(groups) for role, groups in role_groups.items()}
    if counts.get("TRAIN", 0) < 3 or counts.get("VALIDATION", 0) < 1 or counts.get("HELD_OUT", 0) < 1:
        raise ValueError("requires >=3 TRAIN groups, >=1 VALIDATION group, and >=1 HELD_OUT group")
    if dataset[group_column].isna().any():
        raise ValueError("source dataset contains null group ids")
    source_groups = dict(zip(dataset["measurement_event_id"].astype(str), dataset[group_column].astype(str)))
    for row in assignments.itertuples(index=False):
        if source_groups.get(str(row.measurement_event_id)) != str(getattr(row, group_column)):
            raise ValueError("assignment group ids do not match the source dataset")
    return counts


def inspect_independent_validation_evidence(
    processed_root: Path, *, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Return only checksum- and identity-verified split evidence; never mutates data."""
    root = Path(processed_root)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    split_root = root / "splits" / battery_id / experiment_id
    if not split_root.is_dir():
        return {"available": False, "verified_split_ids": [], "rejected_count": 0, "reason": "no split artifacts found"}

    dataset_manifests = list((root / "datasets").rglob("dataset_manifest.json")) if (root / "datasets").is_dir() else []
    for manifest_path in sorted(split_root.rglob("split_manifest.json")):
        candidate_id = manifest_path.parent.name
        try:
            if not _safe_file(manifest_path, root):
                raise ValueError("split manifest is outside processed root or is a symlink")
            manifest = _json_object(manifest_path)
            split_id = str(manifest.get("split_id", ""))
            dataset_id = str(manifest.get("dataset_id", ""))
            if split_id != candidate_id or manifest.get("battery_id") != battery_id or manifest.get("experiment_id") != experiment_id:
                raise ValueError("split manifest identity does not match its location or request")
            if manifest_path.parent.parent.name != dataset_id:
                raise ValueError("split dataset identity does not match its directory")
            if manifest.get("strategy") != "GROUP_HOLDOUT":
                raise ValueError("only materialized GROUP_HOLDOUT evidence is eligible")
            matches = []
            for ds_path in dataset_manifests:
                if ds_path.parent.name != dataset_id or not _safe_file(ds_path, root):
                    continue
                try:
                    ds_manifest = _json_object(ds_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if ds_manifest.get("dataset_id") == dataset_id and ds_manifest.get("battery_id") == battery_id and ds_manifest.get("experiment_id") == experiment_id:
                    matches.append((ds_path, ds_manifest))
            if len(matches) != 1:
                raise ValueError("source dataset manifest is missing or ambiguous")
            ds_path, ds_manifest = matches[0]
            if ds_manifest.get("dataset_status") not in _READY_DATASET_STATUSES:
                raise ValueError("source dataset is not ready for splitting")
            dataset_path = ds_path.parent / "dataset.parquet"
            if not _safe_file(dataset_path, root) or not ds_manifest.get("output_checksum") or _sha256(dataset_path) != ds_manifest["output_checksum"]:
                raise ValueError("source dataset parquet is missing, unsafe, or checksum-mismatched")
            assignments_path = manifest_path.parent / "split_assignments.parquet"
            expected = manifest.get("output_checksums", {}).get("split_assignments")
            if not _safe_file(assignments_path, root) or not expected or _sha256(assignments_path) != expected:
                raise ValueError("split assignments are missing, unsafe, or checksum-mismatched")
            assignments = pd.read_parquet(assignments_path)
            dataset = pd.read_parquet(dataset_path)
            group_column = str(manifest.get("group_column", ""))
            group_counts = _validate_assignments(assignments, dataset, group_column)
            accepted.append({"split_id": split_id, "dataset_id": dataset_id, "group_counts": group_counts})
        except Exception as exc:  # noqa: BLE001 - corrupt artifacts fail closed per candidate
            rejected.append({"candidate": candidate_id, "reason": str(exc)[:240]})

    return {
        "available": bool(accepted),
        "verified_split_ids": [entry["split_id"] for entry in accepted],
        "evidence": accepted,
        "rejected_count": len(rejected),
        "rejected": rejected,
        "reason": "verified independent validation and untouched held-out groups found" if accepted else "no valid materialized independent validation evidence",
    }

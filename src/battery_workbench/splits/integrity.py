"""Split source freshness checks shared by scientific consumers and read models."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pandas as pd


def split_dataset_source_reasons(
    processed_root: Path,
    split_manifest: dict[str, Any],
    *,
    dataset_path: Path,
    dataset_manifest_path: Path,
) -> list[str]:
    """Compare a Split's generation-time Dataset fingerprints with current files."""
    sources = {
        "dataset_parquet": Path(dataset_path),
        "dataset_manifest": Path(dataset_manifest_path),
    }
    declared = split_manifest.get("source_checksums")
    if not isinstance(declared, dict) or set(declared) != set(sources):
        return ["SPLIT_SOURCE_CHECKSUMS_MISSING_OR_INVALID"]

    root = Path(processed_root).resolve()
    reasons: list[str] = []
    for key, path in sources.items():
        expected = declared.get(key)
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(char not in "0123456789abcdef" for char in expected.lower())
        ):
            reasons.append(f"SPLIT_SOURCE_CHECKSUM_INVALID:{key}")
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"SPLIT_SOURCE_PATH_INVALID:{key}")
            continue
        digest = hashlib.sha256()
        try:
            with resolved.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            reasons.append(f"SPLIT_SOURCE_UNREADABLE:{key}")
            continue
        if digest.hexdigest() != expected.lower():
            reasons.append(f"SPLIT_SOURCE_DATASET_CHANGED:{key}")
    return reasons


def split_assignment_reasons(
    processed_root: Path,
    split_manifest: dict[str, Any],
    *,
    assignments_path: Path,
    dataset_path: Path,
) -> list[str]:
    """Verify each fold assigns exactly the current Dataset's event identities."""
    root = Path(processed_root).resolve()
    paths: dict[str, Path] = {}
    for name, path in (("assignments", assignments_path), ("dataset", dataset_path)):
        try:
            resolved = Path(path).resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return [f"SPLIT_ASSIGNMENT_PATH_INVALID:{name}"]
        paths[name] = resolved

    group_column = split_manifest.get("group_column")
    if not isinstance(group_column, str) or not group_column:
        return ["SPLIT_ASSIGNMENT_GROUP_COLUMN_INVALID"]
    try:
        dataset_frame = pd.read_parquet(
            paths["dataset"], columns=["measurement_event_id", group_column]
        )
        assignments = pd.read_parquet(paths["assignments"])
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return ["SPLIT_ASSIGNMENTS_UNREADABLE"]

    if dataset_frame.empty or dataset_frame["measurement_event_id"].isna().any() or not dataset_frame[
        "measurement_event_id"
    ].is_unique:
        return ["SPLIT_DATASET_EVENT_IDENTITIES_INVALID"]
    dataset_ids = dataset_frame["measurement_event_id"]
    if any(not isinstance(value, str) or not value or value != value.strip() for value in dataset_ids):
        return ["SPLIT_DATASET_EVENT_IDENTITIES_INVALID"]
    dataset_groups = dataset_frame[group_column]
    if dataset_groups.isna().any() or any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in dataset_groups
    ):
        return ["SPLIT_DATASET_GROUP_IDENTITIES_INVALID"]
    required = {
        "measurement_event_id",
        "fold",
        "role",
        group_column,
        "strategy",
        "dataset_id",
        "split_id",
    }
    if not required.issubset(assignments.columns):
        return ["SPLIT_ASSIGNMENT_COLUMNS_INVALID"]
    if assignments.empty:
        return ["SPLIT_ASSIGNMENTS_EMPTY"]
    if assignments["measurement_event_id"].isna().any():
        return ["SPLIT_ASSIGNMENT_EVENT_IDENTITIES_INVALID"]
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in assignments["measurement_event_id"]
    ):
        return ["SPLIT_ASSIGNMENT_EVENT_IDENTITIES_INVALID"]
    if assignments[["fold", "role"]].isna().any().any():
        return ["SPLIT_ASSIGNMENT_FOLD_OR_ROLE_INVALID"]
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for column in ("fold", "role")
        for value in assignments[column]
    ):
        return ["SPLIT_ASSIGNMENT_FOLD_OR_ROLE_INVALID"]

    reasons: list[str] = []
    expected_ids = set(dataset_ids.tolist())
    expected_group_counts = {
        str(group): int(count)
        for group, count in dataset_frame.groupby(group_column, sort=True).size().items()
    }
    declared_group_counts = split_manifest.get("group_counts")
    if declared_group_counts != expected_group_counts:
        reasons.append("SPLIT_GROUP_COUNTS_MISMATCH")
    group_count = split_manifest.get("group_count")
    if not isinstance(group_count, int) or isinstance(group_count, bool) or group_count != len(
        expected_group_counts
    ):
        reasons.append("SPLIT_GROUP_COUNT_MISMATCH")
    split_unit_to_column = {
        "CYCLE": "cycle_group_id",
        "BATTERY": "battery_id",
        "EXPERIMENT": "experiment_id",
    }
    split_unit = split_manifest.get("split_unit")
    if split_unit_to_column.get(split_unit) != group_column:
        reasons.append("SPLIT_GROUP_COLUMN_UNIT_MISMATCH")
    folds = sorted(set(assignments["fold"].tolist()))
    if any(re.fullmatch(r"fold[1-9][0-9]*", fold) is None for fold in folds):
        reasons.append("SPLIT_ASSIGNMENT_FOLD_INVENTORY_INVALID")
    if not folds:
        reasons.append("SPLIT_ASSIGNMENT_FOLD_INVENTORY_INVALID")
    else:
        expected_folds = [f"fold{index}" for index in range(1, len(folds) + 1)]
        if folds != expected_folds:
            reasons.append("SPLIT_ASSIGNMENT_FOLD_INVENTORY_INVALID")

    allowed_roles = {"TRAIN", "VALIDATION", "TEST", "HELD_OUT"}
    if not set(assignments["role"].tolist()).issubset(allowed_roles):
        reasons.append("SPLIT_ASSIGNMENT_ROLE_INVALID")

    for fold in folds:
        fold_rows = assignments[assignments["fold"] == fold]
        ids = fold_rows["measurement_event_id"]
        if ids.duplicated().any():
            reasons.append(f"SPLIT_ASSIGNMENT_DUPLICATE_EVENT:{fold}")
            continue
        if set(ids.tolist()) != expected_ids:
            reasons.append(f"SPLIT_ASSIGNMENT_EVENT_SET_MISMATCH:{fold}")
        expected_groups = dataset_frame.set_index("measurement_event_id")[group_column]
        actual_groups = fold_rows.set_index("measurement_event_id")[group_column]
        if set(ids.tolist()) == expected_ids and not actual_groups.reindex(expected_groups.index).equals(
            expected_groups
        ):
            reasons.append(f"SPLIT_ASSIGNMENT_GROUP_MAPPING_MISMATCH:{fold}")
        if group_column in assignments.columns:
            group_values = fold_rows[group_column]
            if group_values.isna().any() or any(
                not isinstance(value, str) or not value or value != value.strip()
                for value in group_values
            ):
                reasons.append(f"SPLIT_ASSIGNMENT_GROUP_INVALID:{fold}")
            elif fold_rows.groupby(group_column)["role"].nunique().gt(1).any():
                reasons.append(f"SPLIT_ASSIGNMENT_GROUP_ROLE_OVERLAP:{fold}")

    strategy = split_manifest.get("strategy")
    role_by_fold = {
        fold: assignments.loc[assignments["fold"] == fold]
        for fold in folds
    }
    if strategy in {"TRAIN_ONLY", "NO_VALID_SPLIT"}:
        if folds != ["fold1"] or set(assignments["role"]) != {"TRAIN"}:
            reasons.append("SPLIT_TRAIN_ONLY_ROLE_SEMANTICS_INVALID")
    elif strategy == "LEAVE_ONE_GROUP_OUT":
        held_groups: list[str] = []
        for fold, fold_rows in role_by_fold.items():
            held = fold_rows.loc[fold_rows["role"] == "HELD_OUT", group_column].unique()
            if len(held) != 1 or set(fold_rows["role"]) != {"TRAIN", "HELD_OUT"}:
                reasons.append(f"SPLIT_LOO_ROLE_SEMANTICS_INVALID:{fold}")
            else:
                held_groups.append(str(held[0]))
        if sorted(held_groups) != sorted(expected_group_counts) or len(folds) != len(
            expected_group_counts
        ):
            reasons.append("SPLIT_LOO_HELD_OUT_GROUP_COVERAGE_INVALID")
    elif strategy == "K_FOLD_GROUPED":
        declared_k = split_manifest.get("k")
        if (
            not isinstance(declared_k, int)
            or isinstance(declared_k, bool)
            or declared_k != len(folds)
            or declared_k < 2
        ):
            reasons.append("SPLIT_K_FOLD_COUNT_MISMATCH")
        validation_groups: list[str] = []
        for fold, fold_rows in role_by_fold.items():
            validation = fold_rows.loc[fold_rows["role"] == "VALIDATION", group_column].unique()
            if len(validation) != 1 or set(fold_rows["role"]) != {"TRAIN", "VALIDATION"}:
                reasons.append(f"SPLIT_K_FOLD_ROLE_SEMANTICS_INVALID:{fold}")
            else:
                validation_groups.append(str(validation[0]))
        if len(set(validation_groups)) != len(validation_groups):
            reasons.append("SPLIT_K_FOLD_VALIDATION_GROUP_REUSED")
    elif strategy == "GROUP_HOLDOUT":
        if folds != ["fold1"] or "TRAIN" not in set(assignments["role"]) or not (
            {"VALIDATION", "HELD_OUT"} & set(assignments["role"])
        ):
            reasons.append("SPLIT_GROUP_HOLDOUT_ROLE_SEMANTICS_INVALID")
        holdout_groups = split_manifest.get("explicit_holdout_groups")
        required_roles = split_manifest.get("require_roles")
        if (
            not isinstance(holdout_groups, list)
            or not holdout_groups
            or any(
                not isinstance(group, str) or not group or group != group.strip()
                for group in holdout_groups
            )
            or len(set(holdout_groups)) != len(holdout_groups)
            or not set(holdout_groups).issubset(expected_group_counts)
            or not isinstance(required_roles, list)
            or len(required_roles) < 2
            or any(not isinstance(role, str) for role in required_roles)
        ):
            reasons.append("SPLIT_GROUP_HOLDOUT_SPEC_INVALID")
        else:
            holdout_role = required_roles[1]
            fold_rows = role_by_fold.get("fold1", pd.DataFrame())
            actual_holdout_roles = fold_rows.loc[
                fold_rows[group_column].isin(holdout_groups)
            ].groupby(group_column)["role"].unique()
            if (
                set(actual_holdout_roles.index) != set(holdout_groups)
                or any(
                    set(role_values) != {holdout_role}
                    for role_values in actual_holdout_roles.tolist()
                )
            ):
                reasons.append("SPLIT_EXPLICIT_HOLDOUT_ROLE_MISMATCH")
    else:
        reasons.append("SPLIT_STRATEGY_INVALID")

    declared_strategy = split_manifest.get("strategy")
    for column, expected in (
        ("dataset_id", split_manifest.get("dataset_id")),
        ("split_id", split_manifest.get("split_id")),
        ("strategy", declared_strategy),
    ):
        if (
            not isinstance(expected, str)
            or not assignments[column].map(lambda value: isinstance(value, str)).all()
            or not assignments[column].eq(expected).all()
        ):
            reasons.append(f"SPLIT_ASSIGNMENT_{column.upper()}_MISMATCH")

    roles = set(assignments["role"].tolist())
    has_held_out = "HELD_OUT" in roles
    expected_role_semantics = {
        "held_out_role": "HELD_OUT" if has_held_out else "",
        "independent_validation_groups": 0 if has_held_out else None,
        "independent_test_groups": 0 if has_held_out else None,
        "three_way_structure_present": "VALIDATION" in roles and "TEST" in roles,
        "held_out_target_usage": (
            "FORBIDDEN_FOR_MODEL_SELECTION" if has_held_out else "NOT_APPLICABLE"
        ),
        "note": (
            "independent cycles only; no simultaneous independent validation + test groups exist"
            if has_held_out
            else ""
        ),
    }
    if split_manifest.get("role_semantics") != expected_role_semantics:
        reasons.append("SPLIT_ROLE_SEMANTICS_MISMATCH")

    row_count = split_manifest.get("row_count")
    fold_count = split_manifest.get("fold_count")
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count != len(assignments):
        reasons.append("SPLIT_ASSIGNMENT_ROW_COUNT_MISMATCH")
    if not isinstance(fold_count, int) or isinstance(fold_count, bool) or fold_count != len(folds):
        reasons.append("SPLIT_ASSIGNMENT_FOLD_COUNT_MISMATCH")
    return reasons

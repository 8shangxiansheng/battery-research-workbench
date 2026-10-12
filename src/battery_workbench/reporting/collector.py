"""BRW-023 evidence/result/limitation collector.

Aggregates existing BRW-003–022 artifacts into tracking registries without
recomputing any scientific values.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.datasets.freshness import dataset_freshness
from battery_workbench.provenance.parser_manifest import (
    invalid_parser_manifest_modalities,
    invalid_parser_source_modalities,
)
from battery_workbench.reporting.schemas import (
    EvidenceType,
    ExperimentRecord,
    ScientificResultRecord,
)

DEFAULT_LIMITATIONS: list[dict[str, str]] = [
    {
        "code": "ONE_BATTERY_ONLY",
        "severity": "BLOCKING_FOR_CLAIM",
        "description": "only 1 battery in dataset — no cross-battery evaluation possible",
    },
    {
        "code": "TWO_CYCLES_ONLY",
        "severity": "BLOCKING_FOR_CLAIM",
        "description": "only 2 cycle groups — leave-one-group-out limited evaluation",
    },
    {
        "code": "NO_CROSS_BATTERY_EVALUATION",
        "severity": "BLOCKING_FOR_CLAIM",
        "description": "no cross-battery generalization claim is supported",
    },
    {
        "code": "NO_INDEPENDENT_VALIDATION_GROUP",
        "severity": "LIMITATION",
        "description": "no independent validation group exists",
    },
    {
        "code": "NO_HYPERPARAMETER_TUNING",
        "severity": "LIMITATION",
        "description": "no hyperparameter tuning run is present in the evaluated artifact chain",
    },
    {
        "code": "SOH_INDEPENDENT_STATES_TOO_FEW",
        "severity": "BLOCKING_FOR_MODELING",
        "description": "SOH dataset is below its independent-state readiness threshold; event rows are not independent",
    },
    {
        "code": "TOF_UNAVAILABLE_OR_BLOCKED",
        "severity": "LIMITATION",
        "description": "no active canonical TOF is available for the evaluated dataset",
    },
    {
        "code": "ABSOLUTE_ARRIVAL_TOF_BLOCKED",
        "severity": "LIMITATION",
        "description": "absolute-arrival TOF is nonphysical because the acquisition window starts after the burst begins",
    },
    {
        "code": "FEATURE_SELECTION_STABILITY_LIMITED",
        "severity": "LIMITATION",
        "description": "fold-specific selections differ across folds",
    },
    {
        "code": "LIMITED_CROSS_CYCLE_GENERALIZATION",
        "severity": "LIMITATION",
        "description": "within-battery cross-cycle evaluation only",
    },
    {
        "code": "PROVISIONAL_TIMEBASE",
        "severity": "LIMITATION",
        "description": "sync timebase is provisional (not validated)",
    },
    {
        "code": "RETROSPECTIVE_SOC_REFERENCE",
        "severity": "LIMITATION",
        "description": "SOC is derived/protocol-anchored, not true SOC",
    },
    {
        "code": "SOURCE_PROVENANCE_INVALID",
        "severity": "BLOCKING_FOR_CLAIM",
        "description": "a parser source manifest is unreadable or structurally invalid; raw asset lineage is incomplete",
    },
]

EVIDENCE_DIRECT = "DIRECT_CURRENT_ARTIFACT"


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _load_json_object(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def _model_fold_coverage_status(model_set: dict[str, Any] | None) -> tuple[str, list[str]]:
    coverage = model_set.get("fold_coverage", {}) if isinstance(model_set, dict) else {}
    if coverage.get("complete") is True:
        return "READY_FOR_LIMITED_EVALUATION", []
    return "PARTIAL_FOLD_COVERAGE", [
        "PARTIAL_FOLD_COVERAGE",
        "DO_NOT_INTERPRET_AS_COMPLETE_SPLIT_EVALUATION",
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_chain_outputs(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    dataset_id: str,
    split_id: str,
    dataset_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
) -> tuple[list[str], set[str]]:
    """Verify split, model, and comparison bytes before reporting metrics."""
    root = Path(processed_root).resolve()
    reasons: list[str] = []
    split_dir = root / "splits" / battery_id / experiment_id / dataset_id / split_id
    split_manifest_path = split_dir / "split_manifest.json"
    try:
        resolved_split_dir = split_dir.resolve(strict=True)
        resolved_split_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        resolved_split_dir = None
        reasons.append("SPLIT_PATH_INVALID")
    split_manifest = None
    if resolved_split_dir is not None:
        try:
            resolved_split_manifest = split_manifest_path.resolve(strict=True)
            resolved_split_manifest.relative_to(resolved_split_dir)
        except (OSError, RuntimeError, ValueError):
            reasons.append("SPLIT_MANIFEST_PATH_INVALID")
        else:
            split_manifest = _load_json_object(resolved_split_manifest)
    split_outputs = {
        "split_assignments": "split_assignments.parquet",
        "leakage_audit": "leakage_audit.json",
        "evaluation_readiness": "evaluation_readiness.json",
    }
    expected_fold_indices: list[int] | None = None
    if split_manifest is None:
        reasons.append("SPLIT_MANIFEST_MISSING_OR_INVALID")
    else:
        if (
            split_manifest.get("battery_id") != battery_id
            or split_manifest.get("experiment_id") != experiment_id
            or split_manifest.get("dataset_id") != dataset_id
            or split_manifest.get("split_id") != split_id
        ):
            reasons.append("SPLIT_IDENTITY_MISMATCH")
        checksums = split_manifest.get("output_checksums")
        if not isinstance(checksums, dict) or set(checksums) != set(split_outputs):
            reasons.append("SPLIT_OUTPUT_CHECKSUMS_MISSING_OR_INVALID")
        else:
            for key, filename in split_outputs.items():
                output = split_dir / filename
                expected = checksums.get(key)
                try:
                    resolved = output.resolve(strict=True)
                    resolved.relative_to(split_dir.resolve(strict=True))
                    actual = _sha256(resolved)
                except (OSError, RuntimeError, ValueError):
                    reasons.append(f"SPLIT_OUTPUT_MISSING_OR_INVALID:{key}")
                    continue
                if not isinstance(expected, str) or actual != expected.lower():
                    reasons.append(f"SPLIT_OUTPUT_CHECKSUM_MISMATCH:{key}")
        if dataset_path is not None or dataset_manifest_path is not None:
            if dataset_path is None or dataset_manifest_path is None:
                reasons.append("SPLIT_DATASET_SOURCE_PATH_MISSING")
            else:
                from battery_workbench.splits.integrity import split_dataset_source_reasons

                reasons.extend(
                    split_dataset_source_reasons(
                        root,
                        split_manifest,
                        dataset_path=dataset_path,
                        dataset_manifest_path=dataset_manifest_path,
                    )
                )
                from battery_workbench.splits.integrity import split_assignment_reasons

                reasons.extend(
                    split_assignment_reasons(
                        root,
                        split_manifest,
                        assignments_path=split_dir / "split_assignments.parquet",
                        dataset_path=dataset_path,
                    )
                )
        assignments_path = split_dir / "split_assignments.parquet"
        try:
            assignments = pd.read_parquet(assignments_path, columns=["fold"])
            raw_folds = sorted({str(value) for value in assignments["fold"].dropna().tolist()})
            expected_fold_indices = sorted(
                int(value.removeprefix("fold")) for value in raw_folds
            )
            if not expected_fold_indices:
                raise ValueError("split assignments contain no folds")
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            reasons.append("SPLIT_ASSIGNMENTS_FOLD_INVENTORY_INVALID")

    model_root = root / "models" / battery_id / experiment_id / dataset_id / split_id
    try:
        resolved_model_root = model_root.resolve(strict=True)
        resolved_model_root.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        resolved_model_root = None
        reasons.append("MODEL_PATH_INVALID")
    model_ids: set[str] = set()
    model_manifest_checksums: dict[str, str] = {}
    model_fold_pairs: set[tuple[int, str]] = set()
    model_manifest_payloads: list[dict[str, Any]] = []
    model_manifests = (
        list(model_root.glob("*/model_manifest.json"))
        if resolved_model_root is not None
        else []
    )
    if not model_manifests:
        reasons.append("MODEL_MANIFESTS_MISSING")
    for manifest_path in model_manifests:
        try:
            resolved_manifest_path = manifest_path.resolve(strict=True)
            resolved_manifest_path.relative_to(resolved_model_root)
        except (OSError, RuntimeError, ValueError):
            reasons.append("MODEL_MANIFEST_PATH_INVALID")
            continue
        manifest = _load_json_object(manifest_path)
        if manifest is None:
            reasons.append("MODEL_MANIFEST_INVALID")
            continue
        model_id = manifest.get("model_id")
        if (
            not isinstance(model_id, str)
            or manifest_path.parent.name != model_id
            or manifest.get("dataset_id") != dataset_id
            or manifest.get("split_id") != split_id
        ):
            reasons.append("MODEL_IDENTITY_MISMATCH")
            continue
        if model_id in model_ids:
            reasons.append("MODEL_ID_AMBIGUOUS")
        model_ids.add(model_id)
        model_manifest_checksums[model_id] = _sha256(resolved_manifest_path)
        try:
            fold_index = int(manifest.get("fold_index"))
            strategy = str(manifest.get("strategy"))
            if not strategy:
                raise ValueError("missing model strategy")
            model_fold_pairs.add((fold_index, strategy))
            model_manifest_payloads.append(manifest)
        except (TypeError, ValueError):
            reasons.append(f"MODEL_FOLD_IDENTITY_INVALID:{model_id}")
        outputs = {
            "model": "model.joblib",
            "held_out_predictions": "held_out_predictions.parquet",
        }
        checksums = manifest.get("output_checksums")
        if not isinstance(checksums, dict):
            reasons.append(f"MODEL_OUTPUT_CHECKSUMS_MISSING:{model_id}")
            continue
        for key, filename in outputs.items():
            output = manifest_path.parent / filename
            expected = checksums.get(key)
            try:
                resolved = output.resolve(strict=True)
                resolved.relative_to(manifest_path.parent.resolve(strict=True))
                actual = _sha256(resolved)
            except (OSError, RuntimeError, ValueError):
                reasons.append(f"MODEL_OUTPUT_MISSING_OR_INVALID:{model_id}:{key}")
                continue
            if not isinstance(expected, str) or actual != expected.lower():
                reasons.append(f"MODEL_OUTPUT_CHECKSUM_MISMATCH:{model_id}:{key}")

    comparison_dir = root / "models" / battery_id / experiment_id / dataset_id / split_id
    comparison_manifest_path = comparison_dir / "model_comparison_manifest.json"
    try:
        resolved_comparison_dir = comparison_dir.resolve(strict=True)
        resolved_comparison_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        resolved_comparison_dir = None
        reasons.append("MODEL_COMPARISON_PATH_INVALID")
    comparison_manifest = None
    if resolved_comparison_dir is not None:
        try:
            resolved_comparison_manifest = comparison_manifest_path.resolve(strict=True)
            resolved_comparison_manifest.relative_to(resolved_comparison_dir)
        except (OSError, RuntimeError, ValueError):
            reasons.append("MODEL_COMPARISON_MANIFEST_PATH_INVALID")
        else:
            comparison_manifest = _load_json_object(resolved_comparison_manifest)
    if comparison_manifest is None:
        reasons.append("MODEL_COMPARISON_MANIFEST_MISSING_OR_INVALID")
    else:
        if any(
            comparison_manifest.get(key) != value
            for key, value in {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "dataset_id": dataset_id,
                "split_id": split_id,
            }.items()
        ):
            reasons.append("MODEL_COMPARISON_IDENTITY_MISMATCH")
        checksums = comparison_manifest.get("output_checksums")
        comparison_outputs = {
            "model_comparison_parquet": "model_comparison.parquet",
            "model_comparison_json": "model_comparison.json",
        }
        if not isinstance(checksums, dict) or set(checksums) != set(comparison_outputs):
            reasons.append("MODEL_COMPARISON_CHECKSUMS_MISSING_OR_INVALID")
        else:
            for key, filename in comparison_outputs.items():
                output = comparison_dir / filename
                expected = checksums.get(key)
                try:
                    resolved = output.resolve(strict=True)
                    resolved.relative_to(comparison_dir.resolve(strict=True))
                    actual = _sha256(resolved)
                except (OSError, RuntimeError, ValueError):
                    reasons.append(f"MODEL_COMPARISON_OUTPUT_MISSING_OR_INVALID:{key}")
                    continue
                if not isinstance(expected, str) or actual != expected.lower():
                    reasons.append(f"MODEL_COMPARISON_CHECKSUM_MISMATCH:{key}")
    if not (comparison_dir / "model_comparison.parquet").is_file():
        reasons.append("MODEL_COMPARISON_PARQUET_MISSING")
    comparison_fold_pairs: set[tuple[int, str]] = set()
    comparison_model_ids: set[str] = set()
    try:
        comparison_frame = pd.read_parquet(
            comparison_dir / "model_comparison.parquet",
            columns=["fold_index", "strategy", "model_id"],
        )
        comparison_fold_pairs = {
            (int(row.fold_index), str(row.strategy))
            for row in comparison_frame.itertuples(index=False)
        }
        comparison_model_ids = set(comparison_frame["model_id"].astype(str))
        if len(comparison_frame) != len(comparison_fold_pairs):
            reasons.append("MODEL_COMPARISON_FOLD_STRATEGY_DUPLICATED")
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        reasons.append("MODEL_COMPARISON_FOLD_INVENTORY_INVALID")

    model_set_path = comparison_dir / "model_set_manifest.json"
    model_set = None
    if resolved_comparison_dir is not None:
        try:
            resolved_model_set = model_set_path.resolve(strict=True)
            resolved_model_set.relative_to(resolved_comparison_dir)
        except (OSError, RuntimeError, ValueError):
            reasons.append("MODEL_SET_MANIFEST_PATH_INVALID")
        else:
            model_set = _load_json_object(resolved_model_set)
    if model_set is None:
        reasons.append("MODEL_SET_MANIFEST_MISSING_OR_INVALID")
    else:
        if any(
            model_set.get(key) != value
            for key, value in {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "dataset_id": dataset_id,
                "split_id": split_id,
            }.items()
        ):
            reasons.append("MODEL_SET_IDENTITY_MISMATCH")
        members = model_set.get("model_artifacts")
        if not isinstance(members, list):
            reasons.append("MODEL_SET_MEMBERS_INVALID")
        else:
            declared_members: dict[str, str] = {}
            for member in members:
                if not isinstance(member, dict):
                    reasons.append("MODEL_SET_MEMBERS_INVALID")
                    continue
                model_id = member.get("model_id")
                checksum = member.get("manifest_sha256")
                if (
                    not isinstance(model_id, str)
                    or not isinstance(checksum, str)
                    or len(checksum) != 64
                    or model_id in declared_members
                ):
                    reasons.append("MODEL_SET_MEMBERS_INVALID")
                    continue
                declared_members[model_id] = checksum.lower()
            if declared_members != model_manifest_checksums:
                reasons.append("MODEL_SET_MEMBER_MANIFEST_MISMATCH")
        set_checksums = model_set.get("output_checksums")
        comparison_checksums = (
            comparison_manifest.get("output_checksums")
            if isinstance(comparison_manifest, dict)
            else None
        )
        if not isinstance(set_checksums, dict) or not isinstance(comparison_checksums, dict):
            reasons.append("MODEL_SET_OUTPUT_CHECKSUMS_INVALID")
        elif any(
            set_checksums.get(key) != comparison_checksums.get(key)
            for key in ("model_comparison_parquet", "model_comparison_json")
        ):
            reasons.append("MODEL_SET_OUTPUT_CHECKSUM_MISMATCH")
        if comparison_model_ids != model_ids or comparison_fold_pairs != model_fold_pairs:
            reasons.append("MODEL_COMPARISON_MODEL_FOLD_MEMBERSHIP_MISMATCH")
        if expected_fold_indices is not None:
            try:
                from battery_workbench.modeling.persistence import fold_coverage

                actual_coverage = fold_coverage(
                    expected_fold_indices,
                    [fold_index for fold_index, _strategy in model_fold_pairs],
                )
            except (TypeError, ValueError):
                actual_coverage = None
            declared_coverage = model_set.get("fold_coverage")
            if actual_coverage is None or declared_coverage != actual_coverage:
                reasons.append("MODEL_SET_FOLD_COVERAGE_MISMATCH")
            elif model_set.get("readiness") != actual_coverage["readiness"]:
                reasons.append("MODEL_SET_FOLD_READINESS_MISMATCH")
            if actual_coverage is not None:
                for model_manifest in model_manifest_payloads:
                    claims = model_manifest.get("scientific_claims")
                    if (
                        not isinstance(claims, dict)
                        or claims.get("fold_coverage") != actual_coverage
                        or claims.get("readiness") != actual_coverage["readiness"]
                    ):
                        reasons.append("MODEL_MANIFEST_FOLD_COVERAGE_MISMATCH")
                        break
            strategies = model_set.get("strategies")
            evaluated_folds = (actual_coverage or {}).get("evaluated_fold_indices", [])
            if isinstance(strategies, list) and actual_coverage is not None:
                expected_model_pairs = {
                    (fold_index, str(strategy))
                    for fold_index in evaluated_folds
                    for strategy in strategies
                }
                if model_fold_pairs != expected_model_pairs:
                    reasons.append("MODEL_SET_STRATEGY_FOLD_COVERAGE_MISMATCH")
    return list(dict.fromkeys(reasons)), model_ids


def _latest_manifest_value(base: Path, pattern: str, key: str) -> str:
    candidates = [path for path in base.rglob(pattern) if path.is_file()]
    if not candidates:
        return ""
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return str((_load_json_object(latest) or {}).get(key, ""))


def _source_asset_ids(processed_root: Path, battery_id: str, experiment_id: str) -> list[str]:
    assets: list[str] = []
    for modality in ("electrical", "ultrasound"):
        manifest = _load_json_object(
            processed_root / modality / battery_id / experiment_id / "parser_manifest.json"
        ) or {}
        source_assets = manifest.get("source_assets", [])
        if not isinstance(source_assets, list):
            continue
        for asset in source_assets:
            asset_id = asset.get("data_asset_id") if isinstance(asset, dict) else asset
            if asset_id and str(asset_id) not in assets:
                assets.append(str(asset_id))
    return assets


def _has_invalid_parser_manifest(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    raw_root: Path | None = None,
) -> bool:
    invalid = (
        invalid_parser_manifest_modalities(processed_root, battery_id, experiment_id)
        if raw_root is None
        else invalid_parser_source_modalities(
            processed_root, raw_root, battery_id, experiment_id
        )
    )
    return bool(invalid)


def latest_evaluated_chain(
    processed_root: Path, battery_id: str, experiment_id: str
) -> tuple[str, str]:
    """Dataset/split identities actually consumed by the most recent model run."""
    models_dir = processed_root / "models" / battery_id / experiment_id
    best: tuple[float, str, str] | None = None
    if models_dir.is_dir():
        for comp in models_dir.glob("DS::*/*/model_comparison.json"):
            ds, sp = comp.parent.parent.name, comp.parent.name
            if not any(
                (processed_root / "datasets" / battery_id / experiment_id).rglob(
                    f"{ds}/dataset_manifest.json"
                )
            ):
                continue
            mtime = comp.stat().st_mtime
            if best is None or mtime > best[0]:
                best = (mtime, ds, sp)
    return (best[1], best[2]) if best else ("", "")


def _dataset_manifest_for_chain(
    processed_root: Path, battery_id: str, experiment_id: str, dataset_id: str
) -> Path | None:
    if not dataset_id:
        return None
    base = processed_root / "datasets" / battery_id / experiment_id
    return next(base.rglob(f"{dataset_id}/dataset_manifest.json"), None)


def _canonical_tof_active(processed_root: Path, battery_id: str, experiment_id: str) -> bool:
    from battery_workbench.features_physical.canonical_tof import (
        canonical_tof_integrity_reasons,
    )

    if canonical_tof_integrity_reasons(processed_root, battery_id, experiment_id):
        return False
    canon = (
        _load_json_object(
            processed_root
            / "features_physical" / battery_id / experiment_id / "canonical_tof_manifest.json"
        )
        or {}
    )
    return bool(canon.get("sampling_rate_verified")) and bool(canon.get("canonical_tof_valid"))


def collect_experiment_record(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    *,
    raw_root: Path | None = None,
) -> ExperimentRecord:
    b, e = battery_id, experiment_id
    invalid_modalities = (
        invalid_parser_manifest_modalities(processed_root, b, e)
        if raw_root is None
        else invalid_parser_source_modalities(processed_root, raw_root, b, e)
    )
    ps_ids = sorted(
        p.name for p in (processed_root / "parameters" / b / e).glob("PS::*") if p.is_dir()
    )
    label_manifest = _load_json_object(
        processed_root / "labels" / b / e / "label_manifest.json"
    ) or {}

    runs_dir = processed_root.parent / "artifacts" / "runs"
    run_ids = (
        sorted(p.parent.name for p in runs_dir.glob("*/run_manifest.json"))
        if runs_dir.exists()
        else []
    )

    latest_ds, latest_split = latest_evaluated_chain(processed_root, b, e)
    limitations = [
        item["code"]
        for item in collect_limitation_registry(processed_root, b, e, raw_root=raw_root)
    ]
    source_integrity_blocked = bool(invalid_modalities)
    scientific_status = "INTEGRITY_BLOCKED" if source_integrity_blocked else "READY_FOR_LIMITED_EVALUATION"
    latest_canonical_artifacts = {
        "dataset_id": latest_ds,
        "label_set_id": label_manifest.get("label_set_id", ""),
        "split_id": latest_split,
        "gate_set_id": _latest_manifest_value(
            processed_root / "gated_features" / b / e,
            "gated_feature_manifest.json",
            "gate_set_id",
        ),
        "feature_set_id": _latest_manifest_value(
            processed_root / "features" / b / e,
            "feature_set_manifest.json",
            "feature_set_id",
        ),
    }
    if source_integrity_blocked:
        # These are downstream of the parser source chain. Returning their
        # historic identities in a current experiment summary invites stale
        # artifacts to be mistaken for current evidence.
        latest_canonical_artifacts = {key: "" for key in latest_canonical_artifacts}
    return ExperimentRecord(
        battery_id=b,
        experiment_id=e,
        raw_assets=[] if source_integrity_blocked else _source_asset_ids(processed_root, b, e),
        parameter_set_ids=ps_ids,
        latest_canonical_artifacts=latest_canonical_artifacts,
        run_ids=run_ids,
        scientific_status=scientific_status,
        limitations=limitations,
    )


def collect_results(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    *,
    raw_root: Path | None = None,
) -> list[ScientificResultRecord]:
    """Aggregate results from existing artifacts (read-only, no recomputation)."""
    results: list[ScientificResultRecord] = []
    b, e = battery_id, experiment_id
    invalid_modalities = (
        invalid_parser_manifest_modalities(processed_root, b, e)
        if raw_root is None
        else invalid_parser_source_modalities(processed_root, raw_root, b, e)
    )
    if invalid_modalities:
        modality = invalid_modalities[0]
        return [
            ScientificResultRecord(
                result_id="R::source_provenance_integrity",
                result_type="DATA_QUALITY",
                name="Raw source provenance integrity",
                value={"status": "INTEGRITY_BLOCKED", "invalid_modalities": invalid_modalities},
                scope="experiment",
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref=f"{modality}/parser_manifest.json",
                scientific_status="INTEGRITY_BLOCKED",
                limitations=["SOURCE_PROVENANCE_INVALID"],
            )
        ]
    dataset_id, split_id = latest_evaluated_chain(processed_root, b, e)
    dataset_manifest_path = _dataset_manifest_for_chain(processed_root, b, e, dataset_id)
    dataset_manifest = _load_json_object(dataset_manifest_path) if dataset_manifest_path else None
    freshness = (
        dataset_freshness(
            processed_root, dataset_manifest_path, dataset_manifest, raw_root=raw_root
        )
        if dataset_manifest_path and dataset_manifest
        else {"freshness_status": "STALE_SOURCE", "freshness_reasons": ["DATASET_MANIFEST_MISSING"]}
    )
    chain_integrity_reasons: list[str] = []
    split_source_stale_reasons: list[str] = []
    if dataset_id and split_id and freshness["freshness_status"] == "FRESH":
        chain_integrity_reasons, _verified_model_ids = _verify_chain_outputs(
            processed_root,
            b,
            e,
            dataset_id,
            split_id,
            dataset_path=(dataset_manifest_path.parent / "dataset.parquet")
            if dataset_manifest_path
            else None,
            dataset_manifest_path=dataset_manifest_path,
        )
        split_source_stale_reasons = [
            reason
            for reason in chain_integrity_reasons
            if reason.startswith("SPLIT_SOURCE_DATASET_CHANGED:")
        ]
        chain_integrity_reasons = [
            reason for reason in chain_integrity_reasons if reason not in split_source_stale_reasons
        ]

    runs_dir = processed_root.parent / "artifacts" / "runs"
    latest_run_id = (
        max(p.parent.name for p in runs_dir.glob("*/run_manifest.json"))
        if runs_dir.exists()
        else None
    )

    # synchronization
    sync = _load_json_object(
        processed_root / "synchronization" / b / e / "synchronization_manifest.json"
    )
    if sync:
        results.append(
            ScientificResultRecord(
                result_id="R::sync_aligned",
                result_type="SYNCHRONIZATION",
                name="aligned ultrasound frames",
                value=sync.get("matches_frames"),
                units="rows",
                scope="experiment",
                dataset_id=dataset_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="synchronization_manifest.json",
                scientific_status="PROVISIONAL",
                limitations=["PROVISIONAL_TIMEBASE"],
            )
        )

    # labels
    label_manifest = _load_json_object(
        processed_root / "labels" / b / e / "label_manifest.json"
    )
    if label_manifest:
        results.append(
            ScientificResultRecord(
                result_id="R::label_soc_method",
                result_type="LABEL",
                name="SOC method",
                value=label_manifest.get("soc_method"),
                scope="experiment",
                dataset_id=dataset_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="label_manifest.json",
                scientific_status="RETROSPECTIVE",
                limitations=["RETROSPECTIVE_SOC_REFERENCE"],
            )
        )

    # dataset
    ds_manifest = dataset_manifest
    if ds_manifest:
        results.append(
            ScientificResultRecord(
                result_id="R::dataset_status",
                result_type="DATA_QUALITY",
                name="SOC dataset status",
                value=(ds_manifest.get("dataset_status") if freshness["freshness_status"] == "FRESH" else "STALE_SOURCE"),
                scope="experiment",
                dataset_id=dataset_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="dataset_manifest.json",
                scientific_status=freshness["freshness_status"],
                limitations=list(freshness["freshness_reasons"]),
            )
        )

    # split
    split_dir = processed_root / "splits" / b / e / dataset_id / split_id
    split_manifest = _load_json_object(split_dir / "split_manifest.json")
    if split_manifest:
        split_integrity_reasons = [
            reason for reason in chain_integrity_reasons if reason.startswith("SPLIT_")
        ]
        split_current = (
            freshness["freshness_status"] == "FRESH"
            and not split_integrity_reasons
            and not split_source_stale_reasons
        )
        results.append(
            ScientificResultRecord(
                result_id="R::split_readiness",
                result_type="READINESS",
                name="split evaluation readiness",
                value=(
                    split_manifest.get("readiness_status")
                    if split_current
                    else "INTEGRITY_BLOCKED"
                    if split_integrity_reasons
                    else "STALE_SOURCE"
                ),
                scope="experiment",
                dataset_id=dataset_id,
                split_id=split_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="split_manifest.json",
                scientific_status=(
                    split_manifest.get("readiness_status", "")
                    if split_current
                    else "INTEGRITY_BLOCKED"
                    if split_integrity_reasons
                    else "STALE_SOURCE"
                ),
                limitations=(
                    ["LIMITED_CROSS_CYCLE_GENERALIZATION"]
                    if split_current
                    else split_integrity_reasons
                    if split_integrity_reasons
                    else split_source_stale_reasons
                    if split_source_stale_reasons
                    else list(freshness["freshness_reasons"])
                ),
            )
        )

    if chain_integrity_reasons:
        results.append(
            ScientificResultRecord(
                result_id="R::model_chain_integrity",
                result_type="DATA_QUALITY",
                name="Model evaluation artifact integrity",
                value={"status": "INTEGRITY_BLOCKED", "reasons": chain_integrity_reasons},
                scope="experiment",
                dataset_id=dataset_id,
                split_id=split_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="model_comparison_manifest.json",
                scientific_status="INTEGRITY_BLOCKED",
                limitations=chain_integrity_reasons,
            )
        )

    # model comparison per fold per strategy
    comp_path = (
        processed_root / "models" / b / e / dataset_id / split_id / "model_comparison.parquet"
    )
    if (
        comp_path.exists()
        and freshness["freshness_status"] == "FRESH"
        and not chain_integrity_reasons
        and not split_source_stale_reasons
    ):
        comp = pd.read_parquet(comp_path)
        model_set = _load_json(comp_path.parent / "model_set_manifest.json")
        model_readiness, fold_coverage_limitations = _model_fold_coverage_status(model_set)
        for _, row in comp.iterrows():
            for metric in ("MAE", "RMSE", "R2"):
                results.append(
                    ScientificResultRecord(
                        result_id=f"R::model_{row['strategy']}_f{row['fold_index']}_{metric}",
                        result_type="MODEL_METRIC",
                        name=f"{row['strategy']} fold{row['fold_index']} {metric}",
                        value=float(row[metric]) if pd.notna(row[metric]) else None,
                        units="percent" if metric == "MAE" else "",
                        scope=f"fold:{row['fold_index']}",
                        source_artifact_id=row["model_id"],
                        dataset_id=dataset_id,
                        split_id=split_id,
                        model_id=row["model_id"],
                        model_family=str(row["strategy"]),
                        evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                        evidence_ref="model_comparison.parquet",
                        fold_index=int(row["fold_index"]),
                        strategy=str(row["strategy"]),
                        scientific_status=model_readiness,
                        limitations=[
                            "LIMITED_CROSS_CYCLE_GENERALIZATION",
                            *fold_coverage_limitations,
                        ],
                        pooled_rows_usage="POOLED_ROW_DIAGNOSTIC" if metric != "MAE" else "",
                    )
                )
        # macro comparison
        mcomp = _load_json(comp_path.parent / "model_comparison.json")
        for c in mcomp if isinstance(mcomp, list) else []:
            if not isinstance(c, dict) or not c.get("strategy"):
                continue
            results.append(
                ScientificResultRecord(
                    result_id=f"R::macro_{c['strategy']}_MAE",
                    result_type="MODEL_COMPARISON",
                    name=f"{c['strategy']} macro MAE",
                    value=c.get("macro_MAE"),
                    units="percent",
                    scope="experiment",
                    dataset_id=dataset_id,
                    split_id=split_id,
                    source_run_id=latest_run_id,
                    model_family=c["strategy"],
                    evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                    evidence_ref="model_comparison.json",
                    strategy=c["strategy"],
                    scientific_status=model_readiness,
                    limitations=[
                        "LIMITED_CROSS_CYCLE_GENERALIZATION",
                        "TWO_CYCLES_ONLY",
                        *fold_coverage_limitations,
                    ],
                )
            )

    # tof readiness
    tof = _load_json_object(
        processed_root / "features_physical" / b / e / "tof_activation_manifest.json"
    )
    if tof:
        results.append(
            ScientificResultRecord(
                result_id="R::tof_status",
                result_type="READINESS",
                name="TOF status",
                value=tof.get("tof_status"),
                scope="experiment",
                dataset_id=dataset_id,
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="tof_activation_manifest.json",
                scientific_status="BLOCKED",
                limitations=["TOF_UNAVAILABLE_OR_BLOCKED"],
            )
        )

    # BRW-017R2 canonical envelope-peak TOF (surface→bottom) — independent
    # result record; evidence chain names the full task-pack provenance.
    canonical_tof = _read_canonical_tof_summary(processed_root, b, e)
    if canonical_tof is not None:
        results.append(canonical_tof)

    return results


def _read_canonical_tof_summary(
    processed_root: Path, battery_id: str, experiment_id: str
) -> ScientificResultRecord | None:
    """R::canonical_tof_status — provenance trace per the 13_REPORT spec."""
    audit_root = processed_root / "features_physical" / battery_id / experiment_id
    canonical_path = audit_root / "canonical_tof_audit.json"
    if not canonical_path.is_file():
        return None
    payload = _load_json_object(canonical_path)
    if payload is None:
        return None
    audit = payload.get("audit") or payload
    if not isinstance(audit, dict):
        return None
    try:
        valid = int(audit.get("canonical_tof_valid", 0))
        total = int(audit.get("total_frames", 0))
    except (TypeError, ValueError):
        return None
    status = "AVAILABLE" if valid > 0 and payload.get("sampling_rate_verified") else "BLOCKED"
    return ScientificResultRecord(
        result_id="R::canonical_tof_status",
        result_type="READINESS",
        name="Canonical TOF (envelope peak surface→bottom)",
        value={
            "tof_method_id": payload.get("tof_method_id"),
            "tof_definition_version": payload.get("tof_definition_version"),
            "surface_gate_id": payload.get("surface_gate_id"),
            "bottom_gate_id": payload.get("bottom_gate_id"),
            "parameter_set_id": payload.get("parameter_set_id"),
            "sampling_rate_hz": payload.get("sampling_rate_hz"),
            "canonical_tof_valid": valid,
            "total_frames": total,
            "tof_us_stats": audit.get("tof_us_stats"),
        },
        scope="experiment",
        dataset_id=latest_evaluated_chain(processed_root, battery_id, experiment_id)[0] or None,
        evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
        evidence_ref="features_physical/canonical_tof_audit.json",
        scientific_status=status,
        limitations=[] if status == "AVAILABLE" else ["CANONICAL_TOF_NOT_ACTIVATED"],
    )


def collect_evidence_registry(
    results: list[ScientificResultRecord],
) -> list[dict[str, Any]]:
    """Evidence entries derived from the result registry."""
    seen: set[str] = set()
    entries = []
    for r in results:
        key = f"{r.evidence_type.value}:{r.evidence_ref}"
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "evidence_type": r.evidence_type.value,
                "evidence_ref": r.evidence_ref,
                "artifact_id": r.source_artifact_id,
            }
        )
    return entries


def _manifest_by_id(root: Path, artifact_id: str, manifest_name: str) -> dict[str, Any]:
    if not artifact_id:
        return {}
    matches = [
        path
        for path in root.rglob(manifest_name)
        if path.parent.name == artifact_id
    ]
    if len(matches) != 1:
        return {}
    return _load_json_object(matches[0]) or {}


def _experiment_limitation_codes(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    raw_root: Path | None = None,
) -> set[str]:
    """Determine experiment-scoped limitations from the selected evidence chain."""
    root = Path(processed_root)
    dataset_id, split_id = latest_evaluated_chain(root, battery_id, experiment_id)
    dataset = _manifest_by_id(
        root / "datasets" / battery_id / experiment_id,
        dataset_id,
        "dataset_manifest.json",
    )
    split = _load_json_object(
        root / "splits" / battery_id / experiment_id / dataset_id / split_id / "split_manifest.json"
    ) or {}
    active: set[str] = set()
    if _has_invalid_parser_manifest(root, battery_id, experiment_id, raw_root):
        active.add("SOURCE_PROVENANCE_INVALID")

    if dataset:
        battery_groups = dataset.get("battery_group_count")
        cycle_groups = dataset.get("cycle_group_count")
        if isinstance(battery_groups, int) and battery_groups <= 1:
            active.add("ONE_BATTERY_ONLY")
        if isinstance(cycle_groups, int) and cycle_groups == 2:
            active.add("TWO_CYCLES_ONLY")
        if str(dataset.get("soc_label_temporality", "")).startswith("RETROSPECTIVE"):
            active.add("RETROSPECTIVE_SOC_REFERENCE")

    evaluation_scope = split.get("evaluation_scope") if isinstance(split, dict) else None
    # Experiment-level reporting currently aggregates only within-experiment
    # model artifacts; a declared split scope is not a reviewed cohort result.
    active.add("NO_CROSS_BATTERY_EVALUATION")
    role_semantics = split.get("role_semantics", {})
    if not isinstance(role_semantics, dict):
        role_semantics = {}
    validation_groups = role_semantics.get("independent_validation_groups")
    if not isinstance(validation_groups, int) or validation_groups == 0:
        active.add("NO_INDEPENDENT_VALIDATION_GROUP")
    # The current model artifact chain contains fixed baselines, not a tuning run.
    active.add("NO_HYPERPARAMETER_TUNING")
    if evaluation_scope == "WITHIN_BATTERY_CROSS_CYCLE":
        active.add("LIMITED_CROSS_CYCLE_GENERALIZATION")

    soh_manifests = list(
        (root / "datasets" / battery_id / experiment_id / "SOH_CAPACITY").glob(
            "*/dataset_manifest.json"
        )
    )
    soh_not_ready = [
        _load_json_object(path) or {}
        for path in soh_manifests
        if (_load_json_object(path) or {}).get("dataset_status") == "NOT_READY_FOR_MODEL_EVALUATION"
    ]
    if soh_not_ready:
        active.add("SOH_INDEPENDENT_STATES_TOO_FEW")

    sync = _load_json_object(
        root / "synchronization" / battery_id / experiment_id / "synchronization_manifest.json"
    )
    if isinstance(sync, dict) and sync.get("validated_sync") is not True:
        active.add("PROVISIONAL_TIMEBASE")

    canonical_tof_active = _canonical_tof_active(root, battery_id, experiment_id)
    absolute_tof = _load_json_object(
        root / "features_physical" / battery_id / experiment_id / "tof_activation_manifest.json"
    )
    if isinstance(absolute_tof, dict) and absolute_tof.get("tof_status") == "BLOCKED":
        active.add("ABSOLUTE_ARRIVAL_TOF_BLOCKED")
    if not canonical_tof_active:
        active.add("TOF_UNAVAILABLE_OR_BLOCKED")

    if dataset_id and split_id:
        comparison = (
            root / "models" / battery_id / experiment_id / dataset_id / split_id
            / "model_comparison.parquet"
        )
        if comparison.is_file():
            try:
                frame = pd.read_parquet(comparison, columns=["strategy", "fold_index", "selected_features"])
                selected = frame.drop_duplicates(["strategy", "fold_index"])
                if not selected.empty and bool((selected.groupby("strategy")["selected_features"].nunique() > 1).any()):
                    active.add("FEATURE_SELECTION_STABILITY_LIMITED")
            except (OSError, ValueError, KeyError):
                pass

    return active


def collect_limitation_registry(
    processed_root: Path | None = None,
    battery_id: str | None = None,
    experiment_id: str | None = None,
    *,
    raw_root: Path | None = None,
) -> list[dict[str, str]]:
    """Return known definitions globally or only evidence-supported experiment limitations."""
    if processed_root is None or battery_id is None or experiment_id is None:
        return [dict(item) for item in DEFAULT_LIMITATIONS]
    active = _experiment_limitation_codes(
        Path(processed_root), battery_id, experiment_id, raw_root
    )
    definitions = {item["code"]: item for item in DEFAULT_LIMITATIONS}
    limitations = [dict(definitions[code]) for code in sorted(active) if code in definitions]
    soh_manifests = [
        _load_json_object(path) or {}
        for path in (
            Path(processed_root)
            / "datasets"
            / battery_id
            / experiment_id
            / "SOH_CAPACITY"
        ).glob("*/dataset_manifest.json")
    ]
    soh_not_ready = [
        manifest
        for manifest in soh_manifests
        if manifest.get("dataset_status") == "NOT_READY_FOR_MODEL_EVALUATION"
    ]
    if soh_not_ready:
        known_counts = [
            item.get("independent_soh_state_count")
            for item in soh_not_ready
            if isinstance(item.get("independent_soh_state_count"), int)
        ]
        if known_counts:
            count = min(known_counts)
            for item in limitations:
                if item["code"] == "SOH_INDEPENDENT_STATES_TOO_FEW":
                    item["description"] = (
                        f"SOH dataset has {count} independent SOH state groups; "
                        "event rows are not independent"
                    )
                    break
    return limitations

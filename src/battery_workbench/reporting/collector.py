"""BRW-023 evidence/result/limitation collector.

Aggregates existing BRW-003–022 artifacts into tracking registries without
recomputing any scientific values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

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
        "description": "hyperparameter tuning disabled (2 cycles, no validation group)",
    },
    {
        "code": "SOH_INDEPENDENT_STATES_TOO_FEW",
        "severity": "BLOCKING_FOR_MODELING",
        "description": "SOH has only 2 independent states (event rows not independent)",
    },
    {
        "code": "TOF_UNAVAILABLE_OR_BLOCKED",
        "severity": "LIMITATION",
        "description": "absolute TOF blocked — arrival detector not validated",
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
]

EVIDENCE_DIRECT = "DIRECT_CURRENT_ARTIFACT"


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def collect_experiment_record(
    processed_root: Path, battery_id: str, experiment_id: str
) -> ExperimentRecord:
    b, e = battery_id, experiment_id
    ps_ids = sorted(
        p.name for p in (processed_root / "parameters" / b / e).glob("PS::*") if p.is_dir()
    )
    label_manifest = _load_json(processed_root / "labels" / b / e / "label_manifest.json") or {}

    runs_dir = processed_root.parent / "artifacts" / "runs"
    run_ids = (
        sorted(p.parent.name for p in runs_dir.glob("*/run_manifest.json"))
        if runs_dir.exists()
        else []
    )

    return ExperimentRecord(
        battery_id=b,
        experiment_id=e,
        raw_assets=["E001", "U001"],
        parameter_set_ids=ps_ids,
        latest_canonical_artifacts={
            "dataset_id": "DS::6a3142e5186fc684964ff09e",
            "label_set_id": label_manifest.get("label_set_id", ""),
            "split_id": "SPLIT::062cf007d21578a11ab2d728",
            "gate_set_id": "GATESET::8633ce421ad5e26fe686",
            "feature_set_id": "FS::60649fd12c540267fe585914",
        },
        run_ids=run_ids,
        scientific_status="READY_FOR_LIMITED_EVALUATION",
        limitations=[l["code"] for l in DEFAULT_LIMITATIONS],
    )


def collect_results(
    processed_root: Path, battery_id: str, experiment_id: str
) -> list[ScientificResultRecord]:
    """Aggregate results from existing artifacts (read-only, no recomputation)."""
    results: list[ScientificResultRecord] = []
    b, e = battery_id, experiment_id
    DATASET_ID = "DS::6a3142e5186fc684964ff09e"
    SPLIT_ID = "SPLIT::062cf007d21578a11ab2d728"

    runs_dir = processed_root.parent / "artifacts" / "runs"
    latest_run_id = (
        max(p.parent.name for p in runs_dir.glob("*/run_manifest.json"))
        if runs_dir.exists()
        else None
    )

    # synchronization
    sync = _load_json(processed_root / "synchronization" / b / e / "synchronization_manifest.json")
    if sync:
        results.append(ScientificResultRecord(
            result_id="R::sync_aligned", result_type="SYNCHRONIZATION",
            name="aligned ultrasound frames", value=sync.get("matches_frames"),
            units="rows", scope="experiment", dataset_id=DATASET_ID,
            evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
            evidence_ref="synchronization_manifest.json",
            scientific_status="PROVISIONAL", limitations=["PROVISIONAL_TIMEBASE"],
        ))

    # labels
    label_manifest = _load_json(processed_root / "labels" / b / e / "label_manifest.json")
    if label_manifest:
        results.append(ScientificResultRecord(
            result_id="R::label_soc_method", result_type="LABEL",
            name="SOC method", value=label_manifest.get("soc_method"),
            scope="experiment", dataset_id=DATASET_ID,
            evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
            evidence_ref="label_manifest.json",
            scientific_status="RETROSPECTIVE",
            limitations=["RETROSPECTIVE_SOC_REFERENCE"],
        ))

    # dataset
    ds_dir = processed_root / "datasets" / b / e / "SOC" / DATASET_ID
    ds_manifest = _load_json(ds_dir / "dataset_manifest.json")
    if ds_manifest:
        results.append(ScientificResultRecord(
            result_id="R::dataset_status", result_type="DATA_QUALITY",
            name="SOC dataset status", value=ds_manifest.get("dataset_status"),
            scope="experiment", dataset_id=DATASET_ID,
            evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
            evidence_ref="dataset_manifest.json",
            scientific_status=ds_manifest.get("dataset_status", ""),
        ))

    # split
    split_dir = processed_root / "splits" / b / e / DATASET_ID / SPLIT_ID
    split_manifest = _load_json(split_dir / "split_manifest.json")
    if split_manifest:
        results.append(ScientificResultRecord(
            result_id="R::split_readiness", result_type="READINESS",
            name="split evaluation readiness", value=split_manifest.get("readiness_status"),
            scope="experiment", dataset_id=DATASET_ID, split_id=SPLIT_ID,
            evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
            evidence_ref="split_manifest.json",
            scientific_status=split_manifest.get("readiness_status", ""),
            limitations=["LIMITED_CROSS_CYCLE_GENERALIZATION"],
        ))

    # model comparison per fold per strategy
    comp_path = processed_root / "models" / b / e / DATASET_ID / SPLIT_ID / "model_comparison.parquet"
    if comp_path.exists():
        comp = pd.read_parquet(comp_path)
        for _, row in comp.iterrows():
            for metric in ("MAE", "RMSE", "R2"):
                results.append(ScientificResultRecord(
                    result_id=f"R::model_{row['strategy']}_f{row['fold_index']}_{metric}",
                    result_type="MODEL_METRIC",
                    name=f"{row['strategy']} fold{row['fold_index']} {metric}",
                    value=float(row[metric]) if pd.notna(row[metric]) else None,
                    units="percent" if metric == "MAE" else "",
                    scope=f"fold:{row['fold_index']}",
                    source_artifact_id=row["model_id"],
                    dataset_id=DATASET_ID, split_id=SPLIT_ID,
                    model_id=row["model_id"], model_family=str(row["strategy"]),
                    evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                    evidence_ref="model_comparison.parquet",
                    fold_index=int(row["fold_index"]),
                    strategy=str(row["strategy"]),
                    limitations=["LIMITED_CROSS_CYCLE_GENERALIZATION"],
                    pooled_rows_usage="POOLED_ROW_DIAGNOSTIC" if metric != "MAE" else "",
                ))
        # macro comparison
        mcomp = _load_json(comp_path.parent / "model_comparison.json") or []
        for c in mcomp:
            results.append(ScientificResultRecord(
                result_id=f"R::macro_{c['strategy']}_MAE",
                result_type="MODEL_COMPARISON",
                name=f"{c['strategy']} macro MAE",
                value=c.get("macro_MAE"), units="percent", scope="experiment",
                dataset_id=DATASET_ID, split_id=SPLIT_ID,
                source_run_id=latest_run_id, model_family=c["strategy"],
                evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
                evidence_ref="model_comparison.json",
                strategy=c["strategy"],
                limitations=["LIMITED_CROSS_CYCLE_GENERALIZATION", "TWO_CYCLES_ONLY"],
            ))

    # tof readiness
    tof = _load_json(processed_root / "features_physical" / b / e / "tof_activation_manifest.json")
    if tof:
        results.append(ScientificResultRecord(
            result_id="R::tof_status", result_type="READINESS",
            name="TOF status", value=tof.get("tof_status"),
            scope="experiment", dataset_id=DATASET_ID,
            evidence_type=EvidenceType.DIRECT_CURRENT_ARTIFACT,
            evidence_ref="tof_activation_manifest.json",
            scientific_status="BLOCKED",
            limitations=["TOF_UNAVAILABLE_OR_BLOCKED"],
        ))

    return results


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


def collect_limitation_registry() -> list[dict[str, str]]:
    return [dict(l) for l in DEFAULT_LIMITATIONS]

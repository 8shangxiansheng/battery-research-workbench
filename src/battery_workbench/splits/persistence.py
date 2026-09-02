"""BRW-020 split persistence.

Output contract (dataset stays immutable):
  data/processed/splits/{battery}/{experiment}/{dataset_id}/{split_id}/
    split_assignments.parquet / split_manifest.json / split_schema.json /
    evaluation_readiness.json / leakage_audit.json
  data/artifacts/{battery}/{experiment}/splits/{split_id}/
    split_report.json / split_report.html
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_workbench.splits.readiness import evaluate_readiness
from battery_workbench.splits.schemas import SplitSpec, SplitStrategy


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_split_payload(
    *,
    spec: SplitSpec,
    assignments: pd.DataFrame,
    dataset_id: str,
    battery_id: str,
    experiment_id: str,
    dataset_family: str,
    output_root: Path,
    group_counts: dict[str, int],
    dataset_status: str = "",
    independent_soh_states: int | None = None,
) -> dict[str, str]:
    output_root = Path(output_root)
    split_dir = output_root / "splits" / battery_id / experiment_id / dataset_id / spec.split_id
    split_dir.mkdir(parents=True, exist_ok=True)

    assignments_path = split_dir / "split_assignments.parquet"
    assignments.to_parquet(assignments_path, index=False)

    readiness = evaluate_readiness(
        dataset_family=dataset_family,
        independent_soh_states=independent_soh_states,
        battery_count=1,
        cycle_group_count=len(group_counts),
    )

    audit = (
        json.loads((split_dir / "leakage_audit.json").read_text())
        if (split_dir / "leakage_audit.json").exists()
        else None
    )
    from battery_workbench.splits.engine import leakage_audit

    audit = leakage_audit(spec, assignments, assignments)
    audit_path = split_dir / "leakage_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2) + "\n")

    readiness_path = split_dir / "evaluation_readiness.json"
    readiness_path.write_text(json.dumps(readiness, indent=2, ensure_ascii=False) + "\n")

    schema_entries = [
        {"column": c, "dtype": str(assignments[c].dtype)} for c in assignments.columns
    ]
    schema_path = split_dir / "split_schema.json"
    schema_path.write_text(json.dumps(schema_entries, indent=2) + "\n")

    evaluation_type = (
        "LEAVE_ONE_GROUP_OUT_LIMITED_EVALUATION"
        if spec.strategy == SplitStrategy.LEAVE_ONE_GROUP_OUT
        else spec.strategy.value
    )
    roles = sorted(set(assignments["role"])) if len(assignments) else []
    role_semantics = {
        "held_out_role": "HELD_OUT" if "HELD_OUT" in roles else "",
        "independent_validation_groups": 0 if "HELD_OUT" in roles else None,
        "independent_test_groups": 0 if "HELD_OUT" in roles else None,
        "three_way_structure_present": "VALIDATION" in roles and "TEST" in roles,
        "held_out_target_usage": (
            "FORBIDDEN_FOR_MODEL_SELECTION" if "HELD_OUT" in roles else "NOT_APPLICABLE"
        ),
        "note": (
            "independent cycles only; no simultaneous independent validation + test groups exist"
            if "HELD_OUT" in roles
            else ""
        ),
    }
    manifest = {
        "split_id": spec.split_id,
        "split_version": spec.split_version,
        "strategy": spec.strategy.value,
        "split_unit": spec.split_unit,
        "group_column": spec.group_column,
        "dataset_id": dataset_id,
        "dataset_family": dataset_family,
        "dataset_status": dataset_status,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "purpose": spec.purpose,
        "evaluation_scope": readiness.get("evaluation_scope", "WITHIN_BATTERY_CROSS_CYCLE"),
        "evaluation_type": evaluation_type,
        "role_semantics": role_semantics,
        "readiness_status": readiness["status"],
        "group_counts": group_counts,
        "group_count": len(group_counts),
        "fold_count": int(assignments["fold"].nunique()) if len(assignments) else 0,
        "row_count": len(assignments),
        "leakage_audit": audit,
        "provenance": {
            "engine": "brw020_grouped_split_engine",
            "engine_version": spec.split_version,
            "dataset_immutable": True,
        },
        "output_checksums": {
            "split_assignments": _sha256_file(assignments_path),
            "leakage_audit": _sha256_file(audit_path),
            "evaluation_readiness": _sha256_file(readiness_path),
        },
    }
    manifest_path = split_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    # reports (recommended)
    report_dir = output_root / "artifacts" / battery_id / experiment_id / "splits" / spec.split_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "split_id": spec.split_id,
        "dataset_id": dataset_id,
        "strategy": spec.strategy.value,
        "split_unit": spec.split_unit,
        "readiness_status": readiness["status"],
        "evaluation_scope": manifest["evaluation_scope"],
        "group_counts": group_counts,
        "fold_count": manifest["fold_count"],
        "row_count": manifest["row_count"],
        "leakage_audit": audit,
        "limitations": readiness.get("limitations", []),
    }
    report_json = report_dir / "split_report.json"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    report_html = report_dir / "split_report.html"
    report_html.write_text(
        "<html><body><h1>Split Report</h1><pre>"
        + json.dumps(report, indent=2, ensure_ascii=False)
        + "</pre></body></html>\n"
    )

    return {
        "split_id": spec.split_id,
        "split_dir": str(split_dir),
        "split_assignments": str(assignments_path),
        "split_manifest": str(manifest_path),
        "split_schema": str(schema_path),
        "evaluation_readiness": str(readiness_path),
        "leakage_audit": str(audit_path),
        "report_json": str(report_json),
        "report_html": str(report_html),
    }

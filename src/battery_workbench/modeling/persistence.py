"""BRW-022 persistence: model artifacts + comparison + reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.modeling.schemas import ModelSpec
from battery_workbench.modeling.view import FoldTrainingView


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_model_payload(
    *,
    spec: ModelSpec,
    fitted: Any,
    view: FoldTrainingView,
    predictions: pd.DataFrame,
    metrics: dict[str, Any],
    battery_id: str,
    experiment_id: str,
    output_root: Path,
    confirmed_fold_selections: list[str] | None = None,
) -> dict[str, str]:
    import joblib

    output_root = Path(output_root)
    model_dir = (
        output_root
        / "models"
        / battery_id
        / experiment_id
        / spec.dataset_id
        / spec.split_id
        / spec.model_id
    )
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / "model.joblib"
    joblib.dump(fitted.estimator, model_path)

    schema_entries = [
        {"column": c, "dtype": str(predictions[c].dtype)} for c in predictions.columns
    ]
    schema_path = model_dir / "model_schema.json"
    schema_path.write_text(json.dumps(schema_entries, indent=2) + "\n")

    predictions_path = model_dir / "held_out_predictions.parquet"
    predictions.to_parquet(predictions_path, index=False)

    metrics_path = model_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")

    manifest = {
        "model_id": spec.model_id,
        "policy_version": spec.policy_version,
        "confirmed_fold_selections": confirmed_fold_selections or [],
        "strategy": spec.strategy,
        "fixed_config": spec.config,
        "random_state": spec.random_state,
        "dataset_id": spec.dataset_id,
        "split_id": spec.split_id,
        "fold_index": spec.fold_index,
        "selection_id": spec.selection_id,
        "selected_features": spec.selected_features,
        "preprocessing": (
            "StandardScaler fitted on TRAIN rows only (sklearn Pipeline)"
            if spec.strategy in ("LINEAR_REGRESSION", "RIDGE")
            else "NONE (tree-based, no scaling)"
        ),
        "missing_value_policy": "FAIL",
        "train_row_count": metrics["overall"]["n"],
        "train_group_ids": sorted(view.train_group_ids),
        "held_out_group_ids": sorted(view.held_out_group_ids),
        "scientific_claims": {
            "evaluation_scope": "WITHIN_BATTERY_CROSS_CYCLE",
            "readiness": "READY_FOR_LIMITED_EVALUATION",
            "battery_group_count": 1,
            "cycle_group_count": 2,
            "no_cross_battery_generalization_claim": True,
            "no_independent_validation_group": True,
            "no_hyperparameter_tuning": True,
            "evaluation_uncertainty_high": True,
            "pooled_rows_usage": "POOLED_ROW_DIAGNOSTIC",
        },
        "provenance": {"engine": "brw022_baseline_modeling"},
        "output_checksums": {
            "model": _sha256_file(model_path),
            "held_out_predictions": _sha256_file(predictions_path),
        },
    }
    manifest_path = model_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    report_dir = output_root / "artifacts" / battery_id / experiment_id / "models" / spec.model_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / "model_report.json"
    report_json.write_text(
        json.dumps({**metrics, "model_id": spec.model_id}, indent=2, ensure_ascii=False) + "\n"
    )
    report_html = report_dir / "model_report.html"
    report_html.write_text(
        "<html><body><h1>SOC Baseline Model Report</h1><pre>"
        + json.dumps({**metrics, "model_id": spec.model_id}, indent=2, ensure_ascii=False)
        + "</pre></body></html>\n"
    )

    return {
        "model_id": spec.model_id,
        "model_dir": str(model_dir),
        "model": str(model_path),
        "model_manifest": str(manifest_path),
        "model_schema": str(schema_path),
        "held_out_predictions": str(predictions_path),
        "metrics": str(metrics_path),
        "report_json": str(report_json),
        "report_html": str(report_html),
    }


def write_model_comparison(
    *,
    comparison_rows: list[dict[str, Any]],
    battery_id: str,
    experiment_id: str,
    dataset_id: str,
    split_id: str,
    output_root: Path,
) -> dict[str, str]:
    out_dir = output_root / "models" / battery_id / experiment_id / dataset_id / split_id
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(comparison_rows)
    parquet_path = out_dir / "model_comparison.parquet"
    df.to_parquet(parquet_path, index=False)
    json_path = out_dir / "model_comparison.json"
    json_path.write_text(json.dumps(comparison_rows, indent=2, ensure_ascii=False) + "\n")
    return {
        "model_comparison_parquet": str(parquet_path),
        "model_comparison_json": str(json_path),
    }

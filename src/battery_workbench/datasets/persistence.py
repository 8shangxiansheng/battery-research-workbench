"""Persist BRW-016 dataset outputs (parquet + manifest + schema + leakage policy)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.datasets.roles import ColumnRole, get_column_role
from battery_workbench.datasets.schemas import (
    DatasetConfig,
    DatasetManifest,
    DatasetReport,
    DatasetSchemaEntry,
)


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_scalar) + "\n",
        encoding="utf-8",
    )


def _build_schema_entries(df: pd.DataFrame) -> list[DatasetSchemaEntry]:
    entries = []
    for col in df.columns:
        role = get_column_role(col)
        entries.append(
            DatasetSchemaEntry(
                name=col,
                dtype=str(df[col].dtype),
                role=role.value,
                predictor_enabled=(role == ColumnRole.PREDICTOR),
            )
        )
    return entries


def write_dataset_payload(
    *,
    report: DatasetReport,
    df: pd.DataFrame,
    config: DatasetConfig,
    battery_id: str,
    experiment_id: str,
    dataset_family: str,
    feature_set_path: Path,
    label_set_path: Path,
    output_root: Path,
    canonical_tof_manifest_path: Path | None = None,
) -> dict[str, str]:
    """Write dataset.parquet + manifest + schema + leakage_policy; returns paths."""
    from battery_workbench.datasets.leakage import (
        frame_random_split_prohibited,
        future_split_preference,
        leakage_reasons,
        minimum_safe_grouping_key,
    )

    output_root = Path(output_root)
    out_dir = (
        output_root / "datasets" / battery_id / experiment_id / dataset_family / report.dataset_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "dataset.parquet"
    df.to_parquet(parquet_path, index=False)

    schema_entries = _build_schema_entries(df)
    schema_path = out_dir / "dataset_schema.json"
    _write_json(schema_path, [e.model_dump(mode="json") for e in schema_entries])

    leakage = {
        "frame_level_random_split_prohibited": frame_random_split_prohibited(),
        "reasons": leakage_reasons(),
        "minimum_safe_grouping_key": minimum_safe_grouping_key(),
        "future_split_preference": future_split_preference(),
        "leakage_policy_version": config.leakage_policy_version,
    }
    leakage_path = out_dir / "leakage_policy.json"
    _write_json(leakage_path, leakage)

    canonical_tof_manifest_path = (
        Path(canonical_tof_manifest_path) if canonical_tof_manifest_path is not None else None
    )
    label_manifest_path = Path(label_set_path).parent / "label_manifest.json"
    label_manifest_exists = label_manifest_path.is_file()
    feature_manifest_path = Path(feature_set_path).parent / "feature_set_manifest.json"
    feature_manifest_exists = feature_manifest_path.is_file()
    canonical_tof_path = (
        canonical_tof_manifest_path.parent / "canonical_tof.parquet"
        if canonical_tof_manifest_path is not None
        else None
    )
    manifest = DatasetManifest(
        dataset_id=report.dataset_id,
        dataset_family=report.dataset_family,
        target_name=report.target_name,
        dataset_status=report.dataset_status,
        battery_id=battery_id,
        experiment_id=experiment_id,
        analysis_slice_id=report.analysis_slice_id,
        feature_set_id=report.feature_set_id,
        feature_set_path=str(feature_set_path),
        feature_set_checksum=_sha256(feature_set_path),
        feature_set_manifest_path=(
            str(feature_manifest_path) if feature_manifest_exists else ""
        ),
        feature_set_manifest_checksum=(
            _sha256(feature_manifest_path) if feature_manifest_exists else ""
        ),
        label_set_id=report.label_set_id,
        label_set_path=str(label_set_path),
        label_set_checksum=_sha256(label_set_path),
        label_set_manifest_path=str(label_manifest_path) if label_manifest_exists else "",
        label_set_manifest_checksum=(
            _sha256(label_manifest_path) if label_manifest_exists else ""
        ),
        parameter_set_id=report.parameter_set_id,
        parameter_dependency=config.parameter_dependency,
        gate_calibration_id=report.gate_calibration_id,
        canonical_tof_path=str(canonical_tof_path) if canonical_tof_path is not None else "",
        canonical_tof_checksum=_sha256(canonical_tof_path) if canonical_tof_path is not None else "",
        canonical_tof_manifest_path=(
            str(canonical_tof_manifest_path) if canonical_tof_manifest_path is not None else ""
        ),
        canonical_tof_manifest_checksum=(
            _sha256(canonical_tof_manifest_path)
            if canonical_tof_manifest_path is not None
            else ""
        ),
        predictor_policy=config.predictor_policy,
        predictor_columns=report.predictor_columns,
        forbidden_predictor_columns=report.forbidden_predictor_columns,
        selected_features=report.selected_features,
        context_columns=report.context_columns,
        group_columns=report.group_columns,
        quality_columns=report.quality_columns,
        identity_columns=report.identity_columns,
        target_column=report.target_column,
        input_feature_rows=report.input_feature_rows,
        input_label_rows=report.input_label_rows,
        joined_rows=report.joined_rows,
        eligible_rows=report.eligible_rows,
        excluded_rows=report.excluded_rows,
        exclusion_breakdown=report.exclusion_breakdown,
        battery_group_count=report.battery_group_count,
        experiment_group_count=report.experiment_group_count,
        cycle_group_count=report.cycle_group_count,
        distinct_target_values=report.distinct_soh_values
        if report.dataset_family == "SOH_CAPACITY"
        else 0,
        independent_soh_state_count=report.independent_soh_state_count,
        target_method_version=report.soc_formula_version or "",
        soc_label_temporality=report.soc_label_temporality,
        frame_random_split_prohibited=True,
        output_path=str(parquet_path),
        output_checksum=_sha256(parquet_path),
        warnings=report.warnings,
        limitations=report.limitations,
    )
    manifest_path = out_dir / "dataset_manifest.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    report.artifacts.update(
        {
            "dataset": str(parquet_path),
            "dataset_schema": str(schema_path),
            "leakage_policy": str(leakage_path),
            "dataset_manifest": str(manifest_path),
        }
    )

    # QA report artifacts.
    report_dir = (
        output_root
        / "artifacts"
        / battery_id
        / experiment_id
        / "datasets"
        / dataset_family
        / report.dataset_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / "dataset_report.json"
    _write_json(report_json, report.model_dump(mode="json"))
    report_html = report_dir / "dataset_report.html"
    report_html.write_text(
        "<!doctype html>\n<html><head><meta charset='utf-8'><title>Dataset Report</title></head>\n"
        f"<body><h1>{report.dataset_family} Dataset Report</h1>"
        f"<p>dataset_id: {report.dataset_id}</p>"
        f"<p>status: {report.dataset_status}</p>"
        f"<p>rows: {report.eligible_rows}</p>"
        f"<p>target: {report.target_name}</p></body></html>\n",
        encoding="utf-8",
    )
    report.artifacts["report_json"] = str(report_json)
    report.artifacts["report_html"] = str(report_html)
    return report.artifacts

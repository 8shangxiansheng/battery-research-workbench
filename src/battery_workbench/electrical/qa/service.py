from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.anomalies import anomaly, status_from
from battery_workbench.electrical.qa.checks import check_schema, completeness, physical_ranges
from battery_workbench.electrical.qa.cross_table import analyze_cross_table
from battery_workbench.electrical.qa.cycles import analyze_cycles
from battery_workbench.electrical.qa.figures import generate_figures
from battery_workbench.electrical.qa.report import write_report
from battery_workbench.electrical.qa.schemas import (
    ElectricalQAConfig,
    ElectricalQAReport,
    QAAnomaly,
)
from battery_workbench.electrical.qa.steps import analyze_steps
from battery_workbench.electrical.qa.temporal import analyze_temporal

REQUIRED_TABLES = ("records", "cycles", "steps")
OPTIONAL_TABLES = ("aux_temperature", "aux_voltage")


def run_electrical_qa(
    battery_id: str,
    experiment_id: str,
    input_dir: str | Path,
    artifact_dir: str | Path,
    config: ElectricalQAConfig,
) -> ElectricalQAReport:
    input_path = Path(input_dir)
    output_path = Path(artifact_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = {name: input_path / f"{name}.parquet" for name in (*REQUIRED_TABLES, *OPTIONAL_TABLES)}
    manifest_path = input_path / "parser_manifest.json"
    tables: dict[str, pd.DataFrame | None] = {}
    issues: list[QAAnomaly] = []
    for name in REQUIRED_TABLES:
        if paths[name].is_file():
            tables[name] = pd.read_parquet(paths[name])
        else:
            tables[name] = pd.DataFrame()
            issues.append(
                anomaly(
                    "REQUIRED_TABLE_MISSING",
                    "critical",
                    name,
                    f"Required input {paths[name].name} is missing",
                )
            )
    for name in OPTIONAL_TABLES:
        tables[name] = pd.read_parquet(paths[name]) if paths[name].is_file() else None
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    )
    if manifest.get("battery_id") not in (None, battery_id) or manifest.get(
        "experiment_id"
    ) not in (None, experiment_id):
        issues.append(
            anomaly(
                "IDENTITY_MISMATCH",
                "critical",
                "manifest",
                "Requested identity differs from parser manifest",
            )
        )
    records = tables["records"]
    cycles_table = tables["cycles"]
    steps_table = tables["steps"]
    assert records is not None and cycles_table is not None and steps_table is not None
    schema, found = check_schema(records, config)
    issues.extend(found)
    temporal: dict[str, Any] = {}
    cycle_summaries: list[dict[str, Any]] = []
    step_summaries: list[dict[str, Any]] = []
    physical: dict[str, Any] = {}
    cross: dict[str, Any] = {}
    critical_schema = any(item.severity == "critical" for item in found)
    if not critical_schema and not records.empty:
        temporal, found = analyze_temporal(records, config)
        issues.extend(found)
        cycle_summaries, found = analyze_cycles(records, cycles_table, config)
        issues.extend(found)
        step_summaries, found = analyze_steps(records, steps_table)
        issues.extend(found)
        physical, found = physical_ranges(records, tables["aux_temperature"], config)
        issues.extend(found)
        cross, found = analyze_cross_table(
            records,
            cycles_table,
            steps_table,
            {name: tables[name] for name in OPTIONAL_TABLES},
            config,
        )
        issues.extend(found)
    else:
        cross, found = analyze_cross_table(
            pd.DataFrame(columns=["electrical_asset_id", "record_index_raw", "timestamp"]),
            cycles_table,
            steps_table,
            {name: tables[name] for name in OPTIONAL_TABLES},
            config,
        )
        issues.extend(found)
    if records.empty:
        issues.append(
            anomaly("EMPTY_RECORDS", "critical", "records", "records.parquet contains no rows")
        )
    input_files = {
        path.name: {"path": str(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}
        for path in [*paths.values(), manifest_path]
        if path.is_file()
    }
    row_counts = {name: len(frame) if frame is not None else 0 for name, frame in tables.items()}
    report = ElectricalQAReport(
        battery_id=battery_id,
        experiment_id=experiment_id,
        qa_version=config.version,
        inputs={"files": input_files, "parser_manifest": manifest},
        summary={"row_counts": row_counts},
        schema=schema,
        completeness=completeness(tables),
        temporal=temporal,
        cycles=cycle_summaries,
        steps=step_summaries,
        physical_ranges=physical,
        cross_table=cross,
        anomalies=issues,
        warnings=[item.message for item in issues if item.severity == "warning"],
        status=status_from(issues),  # type: ignore[arg-type]
        artifacts={},
        configuration=config.model_dump(mode="json"),
    )
    figure_paths = generate_figures(
        records,
        cycle_summaries,
        step_summaries,
        tables["aux_temperature"],
        output_path / "figures",
        battery_id,
        experiment_id,
        config,
    )
    report.artifacts = {
        "json": str(output_path / "electrical_qa_report.json"),
        "html": str(output_path / "electrical_qa_report.html"),
        "cycle_summary": str(output_path / "tables/cycle_summary.csv"),
        "step_summary": str(output_path / "tables/step_summary.csv"),
        "anomalies": str(output_path / "tables/anomalies.csv"),
        **{f"figure:{name}": path for name, path in figure_paths.items()},
    }
    write_report(report, output_path)
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

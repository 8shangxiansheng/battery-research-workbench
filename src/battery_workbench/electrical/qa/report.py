from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.electrical.qa.schemas import ElectricalQAReport

SECTIONS = [
    "Experiment Overview",
    "Input / Provenance",
    "QA Status",
    "Schema",
    "Missing Data",
    "Temporal Quality",
    "Cycle Summary",
    "Step Summary",
    "Electrical Ranges",
    "Cross-table Consistency",
    "Anomalies / Warnings",
    "Figures",
    "QA Configuration",
    "Software / Version Provenance",
]


def write_report(report: ElectricalQAReport, artifact_dir: Path) -> None:
    tables = artifact_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report.cycles).to_csv(tables / "cycle_summary.csv", index=False)
    pd.DataFrame(report.steps).to_csv(tables / "step_summary.csv", index=False)
    anomaly_rows = [item.model_dump(mode="json") for item in report.anomalies]
    pd.DataFrame(
        anomaly_rows, columns=["code", "severity", "scope", "message", "count", "metadata"]
    ).to_csv(tables / "anomalies.csv", index=False)
    (artifact_dir / "electrical_qa_report.json").write_text(
        report.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
    )
    payload = html.escape(
        json.dumps(report.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
    )
    section_html = "".join(
        f"<section><h2>{index} {name}</h2>"
        + (f"<pre>{payload}</pre>" if index == 1 else "")
        + "</section>"
        for index, name in enumerate(SECTIONS, start=1)
    )
    (artifact_dir / "electrical_qa_report.html").write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><title>Electrical QA</title></head><body><h1>Electrical QA: {html.escape(report.battery_id)} / {html.escape(report.experiment_id)}</h1>{section_html}</body></html>\n",
        encoding="utf-8",
    )


def json_safe(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value

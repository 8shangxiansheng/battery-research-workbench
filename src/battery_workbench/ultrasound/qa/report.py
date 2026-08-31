from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from battery_workbench.ultrasound.qa.schemas import UltrasoundQAReport

HTML_SECTIONS = [
    "Experiment Overview",
    "Input/Provenance",
    "QA Status",
    "Structural Integrity",
    "Temporal Quality",
    "Waveform Amplitude Statistics",
    "Frame-level Quality",
    "Cross-frame Stability",
    "Anomalies/Warnings",
    "Contiguous anomaly regions",
    "Figures",
    "QA Configuration",
    "Scientific Metadata Limitations",
    "Software/Version Provenance",
]


def write_report(
    report: UltrasoundQAReport,
    frame_quality: pd.DataFrame,
    artifact_dir: Path,
) -> None:
    tables = artifact_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    frame_quality.to_csv(tables / "frame_quality.csv", index=False)
    pd.DataFrame(report.assets).to_csv(tables / "asset_summary.csv", index=False)
    anomaly_rows = [item.model_dump(mode="json") for item in report.anomalies]
    pd.DataFrame(
        anomaly_rows,
        columns=[
            "code",
            "severity",
            "scope",
            "asset_id",
            "frame_index_raw",
            "message",
            "metrics",
        ],
    ).to_csv(tables / "anomalies.csv", index=False)
    (artifact_dir / "ultrasound_qa_report.json").write_text(
        report.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
    )
    payload = html.escape(
        json.dumps(report.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
    )
    sections = "".join(
        _html_section(index, name, payload, report)
        for index, name in enumerate(HTML_SECTIONS, start=1)
    )
    (artifact_dir / "ultrasound_qa_report.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Ultrasound QA</title></head><body><h1>Ultrasound QA: "
        f"{html.escape(report.battery_id)} / {html.escape(report.experiment_id)}</h1>"
        f"{sections}</body></html>\n",
        encoding="utf-8",
    )


def _html_section(
    index: int,
    name: str,
    payload: str,
    report: UltrasoundQAReport,
) -> str:
    body = f"<pre>{payload}</pre>" if index == 1 else ""
    if name == "Contiguous anomaly regions":
        body = _anomaly_region_table(report)
    return f"<section><h2>{index} {name}</h2>{body}</section>"


def _anomaly_region_table(report: UltrasoundQAReport) -> str:
    if not report.anomaly_regions:
        return "<p>No frame-level anomaly regions.</p>"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.code)}</td>"
        f"<td>{html.escape(item.severity)}</td>"
        f"<td>{html.escape(item.asset_id)}</td>"
        f"<td>{item.start_frame_index_raw}</td>"
        f"<td>{item.end_frame_index_raw}</td>"
        f"<td>{item.frame_count}</td>"
        "</tr>"
        for item in report.anomaly_regions
    )
    return (
        "<table><thead><tr><th>Code</th><th>Severity</th><th>Asset</th>"
        "<th>Start frame</th><th>End frame</th><th>Frame count</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )

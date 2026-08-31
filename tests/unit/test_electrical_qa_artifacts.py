from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from battery_workbench.electrical.qa import ElectricalQAConfig, run_electrical_qa
from battery_workbench.electrical.qa.figures import REQUIRED_FIGURES
from battery_workbench.electrical.qa.schemas import ElectricalQAReport


def test_json_html_tables_and_figures_are_complete(
    electrical_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    input_dir = electrical_qa_input_factory()
    artifact_dir = tmp_path / "qa"
    report = run_electrical_qa(
        "CELL_TEST", "EXP_TEST", input_dir, artifact_dir, ElectricalQAConfig()
    )

    parsed = ElectricalQAReport.model_validate_json(
        (artifact_dir / "electrical_qa_report.json").read_text(encoding="utf-8")
    )
    assert parsed.status == report.status
    html = (artifact_dir / "electrical_qa_report.html").read_text(encoding="utf-8")
    for section in (
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
    ):
        assert section in html
    assert json.loads((artifact_dir / "electrical_qa_report.json").read_text())["artifacts"]
    for filename in REQUIRED_FIGURES:
        assert (artifact_dir / "figures" / filename).stat().st_size > 0
    for filename in ("cycle_summary.csv", "step_summary.csv", "anomalies.csv"):
        assert (artifact_dir / "tables" / filename).stat().st_size > 0

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from battery_workbench.ultrasound.qa import UltrasoundQAConfig, run_ultrasound_qa
from battery_workbench.ultrasound.qa.figures import REQUIRED_FIGURES
from battery_workbench.ultrasound.qa.report import HTML_SECTIONS
from battery_workbench.ultrasound.qa.schemas import UltrasoundQAReport


def test_json_html_tables_and_eight_figures(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    input_dir = ultrasound_qa_input_factory()
    artifact_dir = tmp_path / "artifacts"
    report = run_ultrasound_qa(
        "CELL_TEST", "EXP_TEST", input_dir, artifact_dir, UltrasoundQAConfig()
    )
    parsed = UltrasoundQAReport.model_validate_json(
        (artifact_dir / "ultrasound_qa_report.json").read_text()
    )
    assert parsed.status == report.status
    assert parsed.anomaly_regions == []
    html = (artifact_dir / "ultrasound_qa_report.html").read_text()
    for section in HTML_SECTIONS:
        assert section in html
    assert "Contiguous anomaly regions" in html
    for filename in REQUIRED_FIGURES:
        assert (artifact_dir / "figures" / filename).stat().st_size > 0
    for filename in ("frame_quality.csv", "asset_summary.csv", "anomalies.csv"):
        assert (artifact_dir / "tables" / filename).stat().st_size > 0
    serialized = (artifact_dir / "ultrasound_qa_report.json").read_text().lower()
    assert '"tof_us":' not in serialized
    assert '"frequency_hz":' not in serialized

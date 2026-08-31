from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from battery_workbench.electrical.qa import ElectricalQAConfig, run_electrical_qa
from battery_workbench.electrical.qa.schemas import ElectricalQAReport


def run_fixture(
    factory: Callable[..., Path], tmp_path: Path, **kwargs: object
) -> ElectricalQAReport:
    input_dir = factory(**kwargs)
    return run_electrical_qa(
        "CELL_TEST",
        "EXP_TEST",
        input_dir,
        tmp_path / "artifacts" / input_dir.name,
        ElectricalQAConfig(),
    )


def anomaly_codes(report: ElectricalQAReport) -> set[str]:
    return {anomaly.code for anomaly in report.anomalies}


def test_perfect_synthetic_experiment_passes(
    electrical_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    report = run_fixture(electrical_qa_input_factory, tmp_path)
    assert report.status == "PASS"
    assert report.summary["row_counts"] == {
        "records": 4,
        "cycles": 2,
        "steps": 4,
        "aux_temperature": 4,
        "aux_voltage": 4,
    }


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"duplicate": True}, "DUPLICATE_TIMESTAMP"),
        ({"backwards": True}, "NON_MONOTONIC_TIMESTAMP"),
        ({"large_gap": True}, "LARGE_TIMESTAMP_GAP"),
        ({"cycle_mismatch": True}, "CYCLE_ID_MISMATCH"),
        ({"step_mismatch": True}, "STEP_ID_MISMATCH"),
        ({"voltage_outlier": True}, "PHYSICAL_RANGE_OUTLIER"),
    ],
)
def test_anomalies_are_reported_without_mutating_rows(
    electrical_qa_input_factory: Callable[..., Path],
    tmp_path: Path,
    kwargs: dict[str, bool],
    code: str,
) -> None:
    report = run_fixture(electrical_qa_input_factory, tmp_path, **kwargs)
    assert report.status == "PASS_WITH_WARNINGS"
    assert code in anomaly_codes(report)
    assert report.summary["row_counts"]["records"] == 4


def test_missing_required_column_is_fail(
    electrical_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    report = run_fixture(electrical_qa_input_factory, tmp_path, missing_column="timestamp")
    assert report.status == "FAIL"
    assert "MISSING_REQUIRED_COLUMN" in anomaly_codes(report)


def test_missing_optional_aux_is_explicit_warning(
    electrical_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    report = run_fixture(electrical_qa_input_factory, tmp_path, missing_aux_temperature=True)
    assert report.status == "PASS_WITH_WARNINGS"
    assert report.cross_table["aux_temperature"]["available"] is False
    assert "OPTIONAL_TABLE_MISSING" in anomaly_codes(report)


def test_duplicate_groups_and_aux_coverage_are_reported(
    electrical_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    report = run_fixture(electrical_qa_input_factory, tmp_path, duplicate=True)
    assert report.temporal["duplicate_timestamp_count"] == 1
    assert len(report.temporal["duplicate_timestamp_groups"]) == 1
    assert report.cross_table["aux_temperature"]["exact_timestamp_match_rate"] == 1.0

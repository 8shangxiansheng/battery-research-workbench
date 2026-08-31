from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from battery_workbench.ultrasound.qa import UltrasoundQAConfig, run_ultrasound_qa


def make_waveforms() -> np.ndarray:
    base = np.arange(-625, 625, dtype=np.int32)
    return np.stack([base] * 5)


def run_values(factory: Callable[..., Path], tmp_path: Path, values: np.ndarray, config=None):
    input_dir = factory(waveforms=values)
    return run_ultrasound_qa(
        "CELL_TEST",
        "EXP_TEST",
        input_dir,
        tmp_path / "artifacts" / input_dir.name,
        config or UltrasoundQAConfig(),
    )


def codes(report: object) -> set[str]:
    return {item.code for item in report.anomalies}  # type: ignore[attr-defined]


def test_all_zero_is_critical_and_constant_nonzero_is_warning(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    zero = make_waveforms()
    zero[2] = 0
    constant = make_waveforms()
    constant[2] = 7
    zero_report = run_values(ultrasound_qa_input_factory, tmp_path, zero)
    constant_report = run_values(ultrasound_qa_input_factory, tmp_path, constant)
    assert zero_report.status == "FAIL"
    assert "ALL_ZERO_FRAME" in codes(zero_report)
    assert constant_report.status == "PASS_WITH_WARNINGS"
    assert "CONSTANT_FRAME" in codes(constant_report)


def test_rms_p2p_dc_and_correlation_outliers_are_reported(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    rms = make_waveforms()
    rms[2] *= 10
    dc = make_waveforms()
    dc[2] += 10000
    correlation = make_waveforms()
    correlation[2] = correlation[2][::-1]
    rms_report = run_values(ultrasound_qa_input_factory, tmp_path, rms)
    dc_report = run_values(ultrasound_qa_input_factory, tmp_path, dc)
    corr_report = run_values(ultrasound_qa_input_factory, tmp_path, correlation)
    assert {"RMS_OUTLIER", "P2P_OUTLIER"} <= codes(rms_report)
    assert "DC_OFFSET_OUTLIER" in codes(dc_report)
    assert "LOW_ADJACENT_CORRELATION" in codes(corr_report)


def test_unknown_rails_only_reports_possible_saturation(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    values = make_waveforms()
    values[2, :100] = values[2].min()
    report = run_values(ultrasound_qa_input_factory, tmp_path, values)
    anomaly = next(item for item in report.anomalies if item.code == "POSSIBLE_SATURATION")
    assert anomaly.metrics["adc_rails_known"] is False
    assert "clipping" not in anomaly.message.lower()
    assert report.waveform["repeated_global_min_count"] >= 100
    assert report.waveform["repeated_global_max_count"] > 0


def test_known_adc_rails_are_reported_as_metrics(
    ultrasound_qa_input_factory: Callable[..., Path], tmp_path: Path
) -> None:
    values = make_waveforms()
    values[2, :100] = -625
    config = UltrasoundQAConfig()
    config.saturation.adc_min = -625
    config.saturation.adc_max = 624
    report = run_values(ultrasound_qa_input_factory, tmp_path, values, config)
    assert report.waveform["rail_hit_count"] > 0
    assert report.waveform["adc_rails_known"] is True

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

from battery_workbench.ultrasound.qa import UltrasoundQAConfig, run_ultrasound_qa


def tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.mark.integration
def test_current_cell_001_ultrasound_qa_and_input_immutability(tmp_path: Path) -> None:
    input_dir = Path("data/processed/ultrasound/CELL_001/EXP_001")
    if not input_dir.is_dir():
        pytest.skip("current BRW-005 processed outputs are unavailable")
    before = tree_checksum(input_dir)
    artifact_dir = tmp_path / "ultrasound_qa"
    report = run_ultrasound_qa(
        "CELL_001",
        "EXP_001",
        input_dir,
        artifact_dir,
        UltrasoundQAConfig(),
    )
    assert report.status == "PASS_WITH_WARNINGS"
    assert report.summary["frame_count"] == 3999
    assert report.summary["zarr_shapes"] == {"U001": [3999, 1250]}
    assert report.temporal["elapsed_time_min_s"] == pytest.approx(0.031217)
    assert report.temporal["elapsed_time_max_s"] == pytest.approx(39980.03)
    assert report.waveform["global_min"] == -29123
    assert report.waveform["global_max"] == 29392
    assert report.waveform["all_zero_frame_count"] == 0
    assert report.waveform["constant_frame_count"] == 0
    assert report.cross_frame["correlation_min"] == pytest.approx(0.9999631899251327)
    counts = Counter(item.code for item in report.anomalies)
    assert counts == {"RMS_OUTLIER": 68, "P2P_OUTLIER": 52}
    assert len(report.anomalies) == 120
    assert [
        (
            region.code,
            region.start_frame_index_raw,
            region.end_frame_index_raw,
            region.frame_count,
        )
        for region in report.anomaly_regions
    ] == [
        ("P2P_OUTLIER", 0, 50, 51),
        ("P2P_OUTLIER", 52, 52, 1),
        ("RMS_OUTLIER", 0, 67, 68),
    ]
    html = (artifact_dir / "ultrasound_qa_report.html").read_text(encoding="utf-8")
    assert "Contiguous anomaly regions" in html
    assert "P2P_OUTLIER" in html
    assert "RMS_OUTLIER" in html
    assert "ABSOLUTE_TIMESTAMP_MISMATCH" not in {item.code for item in report.anomalies}
    assert report.scientific_metadata["sampling_rate_hz"] is None
    assert report.inputs["checksums_before"] == report.inputs["checksums_after"]
    assert set(report.inputs["checksums_before"]) == {
        "frames_parquet_sha256",
        "parser_manifest_sha256",
        "waveforms_zarr_sha256",
    }
    assert tree_checksum(input_dir) == before

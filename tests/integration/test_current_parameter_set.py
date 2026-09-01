from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.parameters.schemas import ParameterConfig
from battery_workbench.parameters.service import build_parameter_set

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
P = REPO_ROOT / "data" / "processed"
EVENTS = P / "multimodal" / "CELL_001" / "EXP_001" / "measurement_events.parquet"
ZARR = P / "ultrasound" / "CELL_001" / "EXP_001" / "waveforms.zarr"
LABELS = P / "labels" / "CELL_001" / "EXP_001" / "label_manifest.json"
PARSER_MANIFEST = P / "ultrasound" / "CELL_001" / "EXP_001" / "parser_manifest.json"
CONFIG = ParameterConfig.from_yaml(REPO_ROOT / "configs" / "experiment_parameters.yaml")


def _sha256(path: Path) -> str:
    if path.is_dir():
        return "<dir>"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.skipif(
    not (EVENTS.exists() and ZARR.exists() and LABELS.exists()),
    reason="CELL_001 inputs not present",
)
def test_real_baseline_parameter_set(tmp_path: Path) -> None:
    report = build_parameter_set(
        output_root=tmp_path,
        config=CONFIG,
        measurement_events_path=EVENTS,
        waveform_store_path=ZARR,
        label_manifest_path=LABELS,
    )
    assert report.parameter_set_id.startswith("PS::")

    effective = json.loads(
        Path(report.artifacts["effective_parameters"]).read_text(encoding="utf-8")
    )
    # 1. fs stays UNKNOWN — nothing in the real data provides it, nothing guessed.
    fs = effective["ultrasound.sampling_rate_hz"]
    assert fs["value"] is None
    assert fs["status"] == "UNKNOWN"

    # 2. acquisition window auto-read from the Zarr shape.
    aw = effective["ultrasound.acquisition_window_samples"]
    assert aw["value"] == 1250
    assert aw["status"] == "RESOLVED"

    # 3. reference capacity auto-read from the BRW-014 label manifest.
    ref = effective["battery.reference_capacity_ah"]
    assert ref["value"] == pytest.approx(11.0441)
    assert ref["status"] == "RESOLVED"
    assert effective["labels.reference_cycle_index"]["value"] == 1

    # 4. derived acquisition_window_s stays UNKNOWN (fs unverified).
    assert effective["ultrasound.acquisition_window_s"]["value"] is None

    # 5. capability matrix.
    matrix = json.loads(Path(report.artifacts["capability_matrix"]).read_text(encoding="utf-8"))
    assert matrix["sample_time_conversion"]["status"] == "BLOCKED"
    assert matrix["raw_tof"]["status"] == "BLOCKED"
    assert matrix["capacity_based_soc"]["status"] == "AVAILABLE"
    assert matrix["capacity_based_soh"]["status"] == "AVAILABLE"


@pytest.mark.skipif(
    not (EVENTS.exists() and ZARR.exists() and LABELS.exists()),
    reason="CELL_001 inputs not present",
)
def test_real_parser_manifest_untouched(tmp_path: Path) -> None:
    """The resolution layer never mutates the raw parser manifest."""
    before = _sha256(PARSER_MANIFEST)
    build_parameter_set(
        output_root=tmp_path,
        config=CONFIG,
        measurement_events_path=EVENTS,
        waveform_store_path=ZARR,
        label_manifest_path=LABELS,
    )
    assert _sha256(PARSER_MANIFEST) == before


@pytest.mark.skipif(
    not (EVENTS.exists() and ZARR.exists() and LABELS.exists()),
    reason="CELL_001 inputs not present",
)
def test_real_user_override_example_shape(tmp_path: Path) -> None:
    """A USER_SUPPLIED 100 MHz override resolves as UNVERIFIED and does not
    unlock sample-time conversion (example-only value; never written to the
    real canonical baseline by default)."""
    report = build_parameter_set(
        output_root=tmp_path,
        config=CONFIG,
        measurement_events_path=EVENTS,
        waveform_store_path=ZARR,
        label_manifest_path=LABELS,
        user_overrides={
            "ultrasound.sampling_rate_hz": {
                "value": 100.0,
                "unit": "MHz",
                "verification_status": "UNVERIFIED",
            }
        },
    )
    effective = json.loads(
        Path(report.artifacts["effective_parameters"]).read_text(encoding="utf-8")
    )
    fs = effective["ultrasound.sampling_rate_hz"]
    assert fs["value"] == pytest.approx(1e8)
    assert fs["verification_status"] == "UNVERIFIED"
    matrix = json.loads(Path(report.artifacts["capability_matrix"]).read_text(encoding="utf-8"))
    # Unverified critical parameter unlocks nothing.
    assert matrix["sample_time_conversion"]["status"] == "BLOCKED"


@pytest.mark.skipif(
    not (EVENTS.exists() and ZARR.exists() and LABELS.exists()),
    reason="CELL_001 inputs not present",
)
def test_real_input_immutability(tmp_path: Path) -> None:
    inputs = [EVENTS, ZARR, LABELS, PARSER_MANIFEST]
    before = {p: _sha256(p) for p in inputs}
    build_parameter_set(
        output_root=tmp_path,
        config=CONFIG,
        measurement_events_path=EVENTS,
        waveform_store_path=ZARR,
        label_manifest_path=LABELS,
    )
    after = {p: _sha256(p) for p in inputs}
    assert before == after

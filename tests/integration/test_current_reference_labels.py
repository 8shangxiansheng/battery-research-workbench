from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.labels.builder import build_reference_labels
from battery_workbench.labels.schemas import LabelConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
P = REPO_ROOT / "data" / "processed"
EVENTS = P / "multimodal" / "CELL_001" / "EXP_001" / "measurement_events.parquet"
RECORDS = P / "electrical" / "CELL_001" / "EXP_001" / "records.parquet"
CYCLES = P / "electrical" / "CELL_001" / "EXP_001" / "cycles.parquet"
STEPS = P / "electrical" / "CELL_001" / "EXP_001" / "steps.parquet"
ULTRA = P / "ultrasound" / "CELL_001" / "EXP_001" / "parser_manifest.json"
CONFIG = LabelConfig.from_yaml(REPO_ROOT / "configs" / "reference_labels.yaml")

_Q_REF_CYCLE1 = 11.0441  # real baseline discharge capacity (independently read below)
_Q_REF_CYCLE2 = 11.0083


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build(tmp_path: Path):
    return build_reference_labels(
        measurement_events_path=EVENTS,
        records_path=RECORDS,
        cycles_path=CYCLES,
        steps_path=STEPS,
        ultrasound_manifest_path=ULTRA,
        output_root=tmp_path,
        config=CONFIG,
    )


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_event_labels_rows_match_events_t46(tmp_path: Path) -> None:
    events = pd.read_parquet(EVENTS)
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "event_labels.parquet")
    assert len(out) == len(events) == 3999
    assert out["measurement_event_id"].tolist() == events["measurement_event_id"].tolist()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_cycle_labels_unique_keys_t47(tmp_path: Path) -> None:
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "cycle_labels.parquet")
    assert out["cycle_index_raw"].is_unique
    assert set(out["cycle_index_raw"]) == {1.0, 2.0}


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_definitions_and_manifest_persisted_t48_t49(tmp_path: Path) -> None:
    _build(tmp_path)
    d = tmp_path / "labels" / "CELL_001" / "EXP_001"
    assert (d / "label_definitions.json").exists()
    assert (d / "label_manifest.json").exists()
    import json

    m = json.loads((d / "label_manifest.json").read_text(encoding="utf-8"))
    assert m["frame_random_split_prohibited"] is True
    assert m["soc_temporality"] == "RETROSPECTIVE_FULL_CYCLE_REFERENCE"


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_tof_readiness_persisted_t50(tmp_path: Path) -> None:
    _build(tmp_path)
    import json

    t = json.loads(
        (tmp_path / "labels" / "CELL_001" / "EXP_001" / "tof_readiness.json").read_text(
            encoding="utf-8"
        )
    )
    assert t["absolute_tof_status"] == "BLOCKED_MISSING_SAMPLING_RATE"
    assert t["sampling_rate_hz"] is None
    assert t["arrival_detector_status"] == "NOT_SELECTED"


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_input_immutability_t51(tmp_path: Path) -> None:
    before = {p: _sha256(p) for p in (EVENTS, RECORDS, CYCLES, STEPS)}
    _build(tmp_path)
    after = {p: _sha256(p) for p in (EVENTS, RECORDS, CYCLES, STEPS)}
    assert before == after


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_real_cycle_capacity_golden_t52(tmp_path: Path) -> None:
    """T52: cycle discharge capacities read independently from cycles.parquet."""
    cycles = pd.read_parquet(CYCLES)
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "cycle_labels.parquet")
    # Independent expected values from the canonical cycles table.
    expected = dict(zip(cycles["cycle_index_raw"], cycles["discharge_capacity_ah"]))
    for _, row in out.iterrows():
        assert row["discharge_capacity_measured_ah"] == pytest.approx(
            expected[row["cycle_index_raw"]]
        )
    # Reference capacity is the baseline (cycle 1) discharge capacity.
    assert out["reference_capacity_ah"].iloc[0] == pytest.approx(_Q_REF_CYCLE1)


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_real_soc_golden_t53(tmp_path: Path) -> None:
    """T53: SOC endpoints independently verified on the discharge direction."""
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "event_labels.parquet")
    d1 = out[(out["cycle_index_raw"] == 1) & (out["soc_direction"] == "DISCHARGE")]
    assert len(d1) > 0
    first = d1.iloc[0]
    last = d1.iloc[-1]
    # Discharge starts near 100 and ends near 0 (alignment offset <= ~0.2%).
    assert first["soc_reference_percent"] == pytest.approx(100.0, abs=0.2)
    assert last["soc_reference_percent"] == pytest.approx(0.0, abs=0.2)
    assert (d1["soc_reference_quality"] == "VALID_REFERENCE").all()


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_real_soh_golden_t54(tmp_path: Path) -> None:
    """T54: cycle1 SOH=100 (definitional); cycle2 = ratio vs baseline."""
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "cycle_labels.parquet")
    c1 = out[out["cycle_index_raw"] == 1].iloc[0]
    c2 = out[out["cycle_index_raw"] == 2].iloc[0]
    assert c1["soh_capacity_reference_percent"] == pytest.approx(100.0)
    assert c2["soh_capacity_reference_percent"] == pytest.approx(
        100 * _Q_REF_CYCLE2 / _Q_REF_CYCLE1
    )


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_vendor_soc_dod_diagnostic_t55(tmp_path: Path) -> None:
    """T55: vendor field is a diagnostic only — never promoted."""
    report = _build(tmp_path)
    diag = report.vendor_diagnostic
    assert diag["valid_pair_count"] > 0
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "event_labels.parquet")
    # The label table has no vendor pass-through column.
    assert "soc_dod_percent" not in out.columns


@pytest.mark.skipif(not EVENTS.exists(), reason="CELL_001 inputs not present")
def test_no_ultrasound_features_in_labels(tmp_path: Path) -> None:
    _build(tmp_path)
    out = pd.read_parquet(tmp_path / "labels" / "CELL_001" / "EXP_001" / "event_labels.parquet")
    for forbidden in ("rms", "p2p", "xcorr", "waveform", "tof", "fft"):
        assert not any(forbidden in c for c in out.columns)

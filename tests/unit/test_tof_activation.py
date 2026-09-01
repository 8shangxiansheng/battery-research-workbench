"""BRW-017 Physical TOF Activation: parameter entry + arrival detector + chain.

Chain under test (per the BRW-017 pipeline):
  参数录入 (BRW-015 user_overrides → new PS::id)
    + arrival detector synthetic validation (AGENTS.md #13)
    → real tof_us + amplitude activation.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_workbench.features_physical.activation import build_tof_column
from battery_workbench.features_physical.arrival_detector import (
    DETECTOR_VERSION,
    detect_arrival_sample,
    synthetic_arrival_waveform,
    validate_arrival_detector,
)

# --- Synthetic waveform helpers (known ground truth) ---


def _synthetic_waveform(
    *,
    arrival_sample: int,
    n_samples: int = 1250,
    noise_sigma: float = 1.0,
    pulse_amplitude: float = 100.0,
    seed: int = 42,
) -> np.ndarray:
    return synthetic_arrival_waveform(
        arrival_sample=arrival_sample,
        n_samples=n_samples,
        noise_sigma=noise_sigma,
        pulse_amplitude=pulse_amplitude,
        seed=seed,
    )


# --- Arrival detector (sample domain — no fs needed) ---


def test_detector_synthetic_exact_hits() -> None:
    for arrival in (100, 300, 777):
        wave = _synthetic_waveform(arrival_sample=arrival, seed=arrival)
        assert detect_arrival_sample(wave) == arrival


def test_detector_no_pulse_returns_none() -> None:
    rng = np.random.default_rng(7)
    assert detect_arrival_sample(rng.normal(0.0, 1.0, 1250)) is None


def test_detector_deterministic() -> None:
    wave = _synthetic_waveform(arrival_sample=500, seed=3)
    assert detect_arrival_sample(wave) == detect_arrival_sample(wave)


def test_detector_low_snr_still_exact() -> None:
    wave = _synthetic_waveform(arrival_sample=200, noise_sigma=5.0, pulse_amplitude=250.0, seed=11)
    assert detect_arrival_sample(wave) == 200


def test_validation_suite_passes() -> None:
    report = validate_arrival_detector()
    assert report["detector_version"] == DETECTOR_VERSION
    assert report["validated"] is True
    assert report["failed_cases"] == []
    assert report["case_count"] >= 8


def test_validation_report_persistable() -> None:
    report = validate_arrival_detector()
    payload = json.dumps(report)  # must be JSON-serializable
    assert "validated" in json.loads(payload)


# --- Parameter entry (BRW-015 user_overrides → new PS::id) ---


def _param_inputs(tmp_path: Path) -> dict[str, Path]:
    import zarr

    events = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "battery_id": ["CELL_X"], "experiment_id": ["EXP_X"]}
    ).to_parquet(events, index=False)
    zarr_path = tmp_path / "waveforms.zarr"
    g = zarr.open_group(str(zarr_path), mode="w")
    arr = g.create_array("U001/waveform", data=np.zeros((4, 1250), dtype="int32"))
    arr.attrs["sampling_rate_hz"] = None
    return {"measurement_events_path": events, "waveform_store_path": zarr_path}


def _effective_from_report(report: object, tmp_path: Path) -> dict:
    """Read the effective parameters written by build_parameter_set."""
    matches = list((tmp_path / "ps").glob("parameters/*/*/PS::*/effective_parameters.json"))
    assert len(matches) == 1, f"expected one effective_parameters.json, found {matches}"
    return json.loads(matches[0].read_text())


def test_parameter_entry_fs_mhz_creates_resolved_param(tmp_path: Path) -> None:
    from battery_workbench.parameters.service import build_parameter_set

    inputs = _param_inputs(tmp_path)
    build_parameter_set(
        output_root=tmp_path / "ps",
        user_overrides={"ultrasound.sampling_rate_hz": {"value": 100.0, "unit": "MHz"}},
        **inputs,
    )
    eff = _effective_from_report(build_parameter_set, tmp_path)
    fs = eff["ultrasound.sampling_rate_hz"]
    assert fs["value"] == pytest.approx(1e8)
    assert fs["status"] == "RESOLVED"


def test_parameter_entry_changes_ps_id(tmp_path: Path) -> None:
    from battery_workbench.parameters.service import build_parameter_set

    inputs = _param_inputs(tmp_path)
    base = build_parameter_set(output_root=tmp_path / "a", **inputs)
    entered = build_parameter_set(
        output_root=tmp_path / "b",
        user_overrides={"ultrasound.sampling_rate_hz": {"value": 100.0, "unit": "MHz"}},
        **inputs,
    )
    assert base.parameter_set_id != entered.parameter_set_id


def test_parameter_entry_trigger_flow(tmp_path: Path) -> None:
    from battery_workbench.parameters.service import build_parameter_set

    inputs = _param_inputs(tmp_path)
    build_parameter_set(
        output_root=tmp_path / "ps",
        user_overrides={"ultrasound.trigger_sample_index": {"value": 0, "unit": "sample"}},
        **inputs,
    )
    eff = _effective_from_report(build_parameter_set, tmp_path)
    trig = eff["ultrasound.trigger_sample_index"]
    assert trig["value"] == 0
    assert trig["status"] == "RESOLVED"


# --- Activation chain: effective params + arrivals + validated detector → tof_us ---


def _effective(fs: float | None, trigger: int | None) -> dict:
    out: dict = {}
    if fs is not None:
        out["ultrasound.sampling_rate_hz"] = {"value": fs, "status": "RESOLVED"}
    if trigger is not None:
        out["ultrasound.trigger_sample_index"] = {"value": trigger, "status": "RESOLVED"}
    return out


def test_chain_end_to_end_exact_tof() -> None:
    tof, status, reason = build_tof_column(
        effective=_effective(1e8, 10),
        arrival_samples=[130, 230],
        detector_validated=True,
    )
    assert tof == pytest.approx([1.2, 2.2])
    assert status == "READY"
    assert reason == ""


def test_chain_fs_only_blocked() -> None:
    tof, status, reason = build_tof_column(
        effective=_effective(1e8, None),
        arrival_samples=[130],
        detector_validated=True,
    )
    assert tof == [None]
    assert status == "BLOCKED"
    assert reason == "MISSING_TRIGGER"


def test_chain_missing_fs_blocked() -> None:
    tof, _status, reason = build_tof_column(
        effective={},
        arrival_samples=[130],
        detector_validated=True,
    )
    assert tof == [None]
    assert reason == "MISSING_SAMPLING_RATE"


def test_chain_unvalidated_detector_blocked() -> None:
    tof, _status, reason = build_tof_column(
        effective=_effective(1e8, 10),
        arrival_samples=[130],
        detector_validated=False,
    )
    assert tof == [None]
    assert reason == "ARRIVAL_DETECTOR_NOT_VALIDATED"


# --- Nonphysical flight time (trigger at window start, arrival at/before it) ---


def test_engine_nonphysical_block_reason() -> None:
    from battery_workbench.features_physical.engine import TOF_BLOCK_NONPHYSICAL, tof_block_reason

    reason = tof_block_reason(
        sampling_rate_hz=50e6,
        trigger_sample_index=0,
        arrival_sample_index=0,
        arrival_detector_validated=True,
    )
    assert reason == TOF_BLOCK_NONPHYSICAL == "NONPHYSICAL_FLIGHT_TIME"


def test_chain_all_nonphysical_blocked() -> None:
    """Real-data case: signal already present at window start, trigger=0."""
    tof, status, reason = build_tof_column(
        effective=_effective(50e6, 0),
        arrival_samples=[0, 0, 0],
        detector_validated=True,
    )
    assert tof == [None, None, None]
    assert status == "BLOCKED"
    assert reason == "NONPHYSICAL_FLIGHT_TIME"


def test_chain_mixed_physical_ready() -> None:
    """Some events physical, some not → READY; per-event nulls stay null."""
    tof, status, reason = build_tof_column(
        effective=_effective(1e8, 10),
        arrival_samples=[130, 5],
        detector_validated=True,
    )
    assert tof[0] == pytest.approx(1.2)
    assert tof[1] is None
    assert status == "READY"
    assert reason == ""

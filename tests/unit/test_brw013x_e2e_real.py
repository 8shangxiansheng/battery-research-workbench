"""BRW-013X V2 E2E — real CELL_001/EXP_001 pipeline integration.

Chain under test:
  raw ultrasound frames (zarr)
  → MATLAB-aligned TD/FD statistical features (full waveform + explicit gate)
  → V2.1 physical features (amplitudes / XCorr TOF / attenuation / BPS)
  → SAME measurement_event_id electrical context per frame (no per-gate rematch)
  → feature–state correlation workbench (SOC suite / temperature / SOH guard)
  → extraction profile + binding registry policy gates

Read-only: no data/ writes, no historical artifact mutation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from battery_workbench.features.gate_calibration import (
    FeatureExtractionProfile,
    FeatureGateBindingRegistry,
    select_calibration_frames,
)
from battery_workbench.features.physical_v2 import (
    bottom_attenuation_explicit,
    bottom_wave_amplitude,
    bottom_wave_phase_shift,
    surface_bottom_xcorr_tof,
    surface_wave_amplitude,
)
from battery_workbench.features.spectral_transform import (
    SpectralTransformDefinition,
    extract_fd_block,
    extract_td_block,
)
from battery_workbench.features.state_correlation import (
    FeatureStateRow,
    correlate_feature_state,
    soc_correlation_suite,
    soh_cycle_summary,
)

REPO = Path(__file__).resolve().parents[2]
EXP = REPO / "data/processed/ultrasound/CELL_001/EXP_001"

pytestmark = pytest.mark.skipif(
    not (EXP / "frames.parquet").is_file(), reason="real CELL_001 artifacts unavailable"
)


@pytest.fixture(scope="module")
def frames() -> np.ndarray:
    g = zarr.open(str(EXP / "waveforms.zarr"), mode="r")
    return np.asarray(g["U001/waveform"][0:120], dtype=np.float64)


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return pd.read_parquet(
        REPO / "data/processed/multimodal/CELL_001/EXP_001/measurement_events.parquet"
    )


@pytest.fixture(scope="module")
def labels() -> pd.DataFrame:
    return pd.read_parquet(
        REPO / "data/processed/labels/CELL_001/EXP_001/event_labels.parquet"
    )


class TestStatisticalExtractionOnRealFrames:
    def test_td19_full_waveform(self, frames):
        blocks = extract_td_block(frames[0])
        assert len(blocks) == 19
        vals = {b.code: b.value for b in blocks}
        assert vals["TDMax"] == pytest.approx(frames[0].max())
        assert vals["TDMin"] == pytest.approx(frames[0].min())
        # matches BRW-013 legacy waveforms (identical semantics aliased)
        assert vals["TDM"] == pytest.approx(float(np.mean(frames[0])))

    def test_td_on_swa_gate_slice(self, frames):
        # gate [89:200) — inside frame length 1250
        blocks = extract_td_block(
            frames[0], scope="USER_SELECTED_EXPLICIT_GATE",
            gate_id="SWA_SURFACE_GATE", python_start=89, python_end_exclusive=200,
        )
        by_code = {b.code: b for b in blocks}
        assert by_code["TDMax"].value == pytest.approx(frames[0, 89:200].max())
        assert by_code["TDM"].gate_id == "SWA_SURFACE_GATE"

    def test_fd_with_explicit_transform(self, frames):
        transform = SpectralTransformDefinition(
            spectral_transform_id="CELL001_REAL_HANN_MAG_V1",
            remove_dc=True,
            window="hann",
            fft_length=2048,
            one_sided=True,
            spectral_representation="MAGNITUDE",
        )
        blocks = extract_fd_block(frames[0], transform, sampling_rate_hz=50e6)
        assert len(blocks) == 14
        fdaf = next(b for b in blocks if b.code == "FDAF")
        # mean frequency of a 5 MHz-ish packet is within a sane band, not 0/NaN
        assert 0 < fdaf.value < 25e6
        assert all(np.isfinite(b.value) for b in blocks)


class TestPhysicalFeaturesOnRealFrames:
    def test_amplitude_series(self, frames):
        b = bottom_wave_amplitude(frames)
        s = surface_wave_amplitude(frames)
        assert b["raw"].shape == (120,)
        assert np.isfinite(b["raw"]).all() and np.isfinite(s["raw"]).all()
        assert b["raw"].min() > 0 and s["raw"].min() > 0

    def test_xcorr_tof_samples(self, frames):
        out = surface_bottom_xcorr_tof(frames)
        tof = out["tof_samples"]
        assert tof.shape == (120,)
        # real packets: surface ~90:200, bottom ~750:1200 → positive TOF
        assert (tof > 0).mean() > 0.9
        assert out["tof_us"] is None  # never fabricated without fs

    def test_attenuation_and_bps(self, frames):
        att = bottom_attenuation_explicit(frames)
        assert np.isfinite(att["amp_max"]).all()
        assert att["hf_band_status"] == "SOURCE_FORMULA_INCOMPLETE"
        bps = bottom_wave_phase_shift(frames)
        assert bps["reference_frame_index"] == 0
        assert bps["raw_radian"][0] == pytest.approx(0.0, abs=1e-9)


class TestOneFrameOneEventContext:
    """C08–C10 on real data — frame i ↔ measurement_event_id i, no rematch."""

    def test_frame_index_aligns_with_event_id(self, events):
        sub = events.iloc[0:120]
        # frame_index_raw == trailing event id segment (same source order)
        assert (sub["frame_index_raw"].values == np.arange(120)).all()
        assert sub["measurement_event_id"].is_unique

    def test_all_frame_features_share_one_context(self, events, labels):
        merged = events.iloc[0:120].merge(
            labels, on="measurement_event_id", suffixes=("", "_label")
        )
        assert len(merged) == 120
        # one row per frame → all its features (TD/FD/physical) inherit this
        # exact context row; cycle/step/step_type/SOC identical for every
        # gate-local feature of the same frame
        assert merged["cycle_index_raw"].notna().all()
        assert merged["soc_reference_percent"].notna().all()

    def test_ambiguous_sync_frames_exist_and_are_excluded(self, events):
        ineligible = events[~events["analysis_eligible"]]
        assert len(ineligible) == 4  # known ambiguous sync frames
        assert ineligible["sync_ambiguous"].all()


class TestCorrelationOnRealData:
    def _rows(self, events, labels, frames, feature_series, code) -> list[FeatureStateRow]:
        sub = events.iloc[: len(feature_series)].merge(
            labels, on="measurement_event_id", suffixes=("", "_label")
        )
        rows = []
        for i, r in enumerate(sub.itertuples()):
            rows.append(
                FeatureStateRow(
                    measurement_event_id=str(r.measurement_event_id),
                    battery_id=str(r.battery_id),
                    experiment_id=str(r.experiment_id),
                    cycle=int(r.cycle_index_raw) if pd.notna(r.cycle_index_raw) else -1,
                    step=int(r.step_index_raw) if pd.notna(r.step_index_raw) else -1,
                    state={
                        "恒流充电": "charge", "恒压充电": "charge",
                        "恒流放电": "discharge", "搁置": "rest",
                    }.get(str(r.step_type), "rest"),
                    timestamp_s=float(r.elapsed_time_s) if pd.notna(r.elapsed_time_s) else 0.0,
                    feature_code=code,
                    value=float(feature_series[i]),
                    reference_soc_percent=(
                        float(r.soc_reference_percent)
                        if pd.notna(r.soc_reference_percent) else None
                    ),
                    temperature_c=(
                        float(r.temperature_c) if pd.notna(r.temperature_c) else None
                    ),
                    soh_percent=(
                        float(r.soh_capacity_reference_percent)
                        if pd.notna(r.soh_capacity_reference_percent) else None
                    ),
                    analysis_eligible=bool(r.analysis_eligible),
                )
            )
        return rows

    def test_soc_suite_on_real_swa(self, events, labels, frames):
        swa = surface_wave_amplitude(frames)["raw"]
        rows = self._rows(events, labels, frames, swa, "SWA")
        suite = soc_correlation_suite(rows, analysis_id="real-swa", feature_code="SWA")
        overall = next(
            r for r in suite if r.scope == "overall" and r.method == "pearson"
        )
        assert overall.n_valid >= 100
        assert overall.coefficient is not None and np.isfinite(overall.coefficient)
        assert overall.excluded_ineligible_count >= 0
        scopes = {r.scope for r in suite}
        assert {"charge", "discharge", "rest"} <= scopes

    def test_temperature_insufficient_or_valid(self, events, labels, frames):
        swa = surface_wave_amplitude(frames)["raw"]
        rows = self._rows(events, labels, frames, swa, "SWA")
        r = correlate_feature_state(
            rows, state_variable="temperature_c", method="pearson",
            analysis_id="real-temp", feature_code="SWA",
        )
        # real CELL_001 has no temperature channel → stays null/unavailable
        assert r.coefficient is None
        assert r.status in ("TEMPERATURE_UNAVAILABLE", "INSUFFICIENT_VARIATION")

    def test_soh_two_states_not_ready(self, events, labels, frames):
        swa = surface_wave_amplitude(frames)["raw"]
        rows = self._rows(events, labels, frames, swa, "SWA")
        r = correlate_feature_state(
            rows, state_variable="soh_percent", method="pearson",
            analysis_id="real-soh", feature_code="SWA",
        )
        assert r.status == "NOT_READY_INSUFFICIENT_SOH_STATES"
        summ = soh_cycle_summary(rows)
        # frames 0..119 all fall inside cycle 1 (cycle 2 starts later)
        assert {s["cycle"] for s in summ} == {1}

    def test_calibration_subset_from_real_frame_count(self):
        frames_ids = select_calibration_frames(3999)
        assert 24 <= len(frames_ids) <= 40
        assert frames_ids[0] < 400 and frames_ids[-1] > 3600

    def test_profile_validates_against_bindings(self):
        reg = FeatureGateBindingRegistry()
        reg.validate_gates_exist()
        profile = FeatureExtractionProfile(
            profile_id="CELL001_CORE_PHYSICAL",
            feature_codes=["SWA", "BOTTOM_AMP", "TOF_XCORR", "ATTENUATION", "BPS"],
            gate_ids=[
                "SWA_SURFACE_GATE", "BOTTOM_AMPLITUDE_GATE",
                "TOF_SURFACE_REFERENCE_GATE", "TOF_BOTTOM_GATE",
                "ATTENUATION_BOTTOM_GATE", "BPS_BOTTOM_GATE",
            ],
        )
        profile.validate_against_bindings(reg)

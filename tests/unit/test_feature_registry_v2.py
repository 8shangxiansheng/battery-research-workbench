"""BRW-017 V2: Feature Registry + Physical Features + Dataset Retrofit tests."""

from __future__ import annotations

import pytest

from battery_workbench.feature_registry.registry import (
    ALL_REGISTRY_ENTRIES,
    AUXILIARY_FEATURES,
    CORE_FEATURES,
    get_available_features,
    get_missing_parameters_for,
)
from battery_workbench.feature_registry.schemas import (
    AvailabilityStatus,
)

# --- Registry (T01-T08) ---


def test_core_features_t01() -> None:
    names = {e.feature_name for e in CORE_FEATURES}
    assert names == {"tof_us", "amplitude_a_u"}


def test_amplitude_alias_t02() -> None:
    amp = next(e for e in CORE_FEATURES if e.feature_name == "amplitude_a_u")
    assert amp.source_columns == ["waveform_abs_peak_a_u"]


def test_tof_requires_fs_trigger_detector_t03() -> None:
    tof = next(e for e in CORE_FEATURES if e.feature_name == "tof_us")
    assert "ultrasound.sampling_rate_hz" in tof.requires_parameters
    assert "ultrasound.trigger_sample_index" in tof.requires_parameters
    assert "arrival_detector" in tof.requires_capabilities


def test_auxiliary_features_t04() -> None:
    names = {e.feature_name for e in AUXILIARY_FEATURES}
    assert "waveform_rms_a_u" in names
    assert "waveform_p2p_a_u" in names
    assert "waveform_energy_sum_sq_a_u2" in names
    assert "envelope_peak_a_u" in names
    assert len(names) >= 10


def test_all_entries_no_duplicates() -> None:
    names = [e.feature_name for e in ALL_REGISTRY_ENTRIES]
    assert len(names) == len(set(names))


def test_label_fields_rejected() -> None:
    """Label-layer and formula-intermediate fields are never registry entries."""
    names = {e.feature_name for e in ALL_REGISTRY_ENTRIES}
    for forbidden in (
        "soc_reference_percent",
        "soh_capacity_reference_percent",
        "soc_dod_percent",
        "capacity_ah",
        "soc_integral_unbounded_percent",
    ):
        assert forbidden not in names


def test_availability_status_enum() -> None:
    assert set(AvailabilityStatus) == {
        "AVAILABLE",
        "UNAVAILABLE_MISSING_PARAMETER",
        "UNAVAILABLE_CAPABILITY_BLOCKED",
        "UNAVAILABLE_ALGORITHM_NOT_VALIDATED",
    }


def test_current_baseline_availability() -> None:
    """With fs=UNKNOWN: amplitude available, tof_us unavailable."""
    available = {e.feature_name for e in get_available_features()}
    assert "amplitude_a_u" in available
    assert "waveform_rms_a_u" in available
    assert "tof_us" not in available


# --- Minimal facade (T09-T16) ---


def test_missing_fs_prompt_t09() -> None:
    missing = get_missing_parameters_for(["tof_us"])
    assert "ultrasound.sampling_rate_hz" in missing


def test_amplitude_no_params_needed_t10() -> None:
    assert get_missing_parameters_for(["amplitude_a_u"]) == []


def test_tof_progressive_prompt_fs_then_trigger() -> None:
    """Spec#5: ask fs first; only after fs is given, ask for trigger.
    The arrival detector is an algorithm capability — never a user prompt.
    """
    missing = get_missing_parameters_for(["tof_us"])
    # Step 1: only fs is asked.
    assert missing == ["ultrasound.sampling_rate_hz"]
    # Step 2: with fs supplied, trigger is asked next.
    missing_after_fs = get_missing_parameters_for(
        ["tof_us"], available={"ultrasound.sampling_rate_hz"}
    )
    assert missing_after_fs == ["ultrasound.trigger_sample_index"]
    # The detector never appears in user prompts.
    assert all("detector" not in m for m in missing + missing_after_fs)


def test_wave_speed_asks_path_t13() -> None:
    missing = get_missing_parameters_for(["wave_speed_m_s"])
    assert "experiment.ultrasound_path_length_m" in missing


def test_next_user_prompt_progressive() -> None:
    """Spec#5: the facade asks fs first, then trigger, then nothing.
    The arrival detector is an algorithm capability — never a user prompt.
    """
    from battery_workbench.feature_registry.facade import next_user_prompt_for

    assert next_user_prompt_for(["tof_us"]) == "请输入采样频率 (MHz)"
    assert (
        next_user_prompt_for(["tof_us"], available={"ultrasound.sampling_rate_hz"})
        == "请输入触发/时间零点 sample index"
    )
    # With fs+trigger supplied the facade stops asking — detector never prompts.
    assert (
        next_user_prompt_for(
            ["tof_us"],
            available={"ultrasound.sampling_rate_hz", "ultrasound.trigger_sample_index"},
        )
        is None
    )


# --- TOF canonical semantics: ABSOLUTE arrival-based flight time ---


def test_fs_only_does_not_populate_tof() -> None:
    """Spec#8: fs alone is NOT sufficient — tof_us stays null."""
    from battery_workbench.features_physical.engine import compute_tof_us

    assert compute_tof_us(sampling_rate_hz=1e8) is None


def test_xcorr_shift_plus_fs_does_not_populate_tof() -> None:
    """Spec#2: xcorr shift + fs is a relative delay, never canonical tof_us."""
    from battery_workbench.features_physical.engine import (
        compute_relative_delay_us,
        compute_tof_us,
    )

    # The relative delay exists as its own analysis-layer quantity…
    rel = compute_relative_delay_us(xcorr_shift_samples=3, sampling_rate_hz=1e8)
    assert rel == pytest.approx(0.03)
    # …but no combination of xcorr+fs populates tof_us without arrival+trigger.
    assert compute_tof_us(sampling_rate_hz=1e8, xcorr_shift_samples=3) is None


def test_fs_trigger_without_validated_detector_null() -> None:
    """Spec#8: fs + trigger but no validated arrival detector → tof_us null."""
    from battery_workbench.features_physical.engine import compute_tof_us

    assert (
        compute_tof_us(
            sampling_rate_hz=1e8,
            trigger_sample_index=10,
            arrival_sample_index=130,
            arrival_detector_validated=False,
        )
        is None
    )


def test_fs_trigger_validated_synthetic_arrival_exact_tof() -> None:
    """Spec#8: fs + trigger + validated known synthetic arrival → exact tof_us."""
    from battery_workbench.features_physical.engine import compute_tof_us

    # Synthetic: arrival at sample 130, trigger at 10, fs=100 MHz → 1.2 us.
    assert compute_tof_us(
        sampling_rate_hz=1e8,
        trigger_sample_index=10,
        arrival_sample_index=130,
        arrival_detector_validated=True,
    ) == pytest.approx(1.2)


def test_tof_null_without_any_required_input() -> None:
    from battery_workbench.features_physical.engine import compute_tof_us

    assert compute_tof_us() is None
    assert compute_tof_us(trigger_sample_index=10, arrival_sample_index=130) is None


def test_relative_delay_is_not_tof_alias() -> None:
    """The relative delay keeps existing under its own name, never as tof_us."""
    from battery_workbench.features_physical.engine import compute_relative_delay_us

    assert compute_relative_delay_us(xcorr_shift_samples=None, sampling_rate_hz=1e8) is None
    assert compute_relative_delay_us(xcorr_shift_samples=-2, sampling_rate_hz=1e8) == pytest.approx(
        -0.02
    )


def test_arrival_before_trigger_invalid() -> None:
    from battery_workbench.features_physical.engine import compute_tof_us

    assert (
        compute_tof_us(
            sampling_rate_hz=1e8,
            trigger_sample_index=130,
            arrival_sample_index=10,
            arrival_detector_validated=True,
        )
        is None
    )


def test_no_absolute_tof_without_detector_t30() -> None:
    """Absolute TOF requires a validated arrival detector — envelope peak is not one."""
    from battery_workbench.features_physical.engine import absolute_tof_available

    assert absolute_tof_available(has_detector=False) is False
    assert absolute_tof_available(has_detector=True, trigger=True, fs=1e8) is True


# --- Wave speed (T37-T43) ---


def test_wave_speed_corrected_tof_path_t37() -> None:
    from battery_workbench.features_physical.engine import compute_wave_speed

    result = compute_wave_speed(tof_s=1e-6, path_length_m=0.001)
    assert result == pytest.approx(1000.0)


def test_wave_speed_mm_to_m_t38() -> None:
    from battery_workbench.features_physical.engine import compute_wave_speed

    # 5 mm path, 1 us TOF → 5000 m/s
    assert compute_wave_speed(tof_s=1e-6, path_length_m=0.005) == pytest.approx(5000.0)


def test_wave_speed_us_to_s_t39() -> None:
    """1000 us = 0.001 s; wave speed = path / tof."""
    from battery_workbench.features_physical.engine import compute_wave_speed

    assert compute_wave_speed(tof_s=1e-3, path_length_m=1.0) == pytest.approx(1000.0)


def test_wave_speed_missing_path_blocked_t40() -> None:
    from battery_workbench.features_physical.engine import compute_wave_speed

    assert compute_wave_speed(tof_s=1e-6, path_length_m=None) is None


def test_wave_speed_missing_tof_blocked_t41() -> None:
    from battery_workbench.features_physical.engine import compute_wave_speed

    assert compute_wave_speed(tof_s=None, path_length_m=0.01) is None


def test_wave_speed_nonpositive_tof_invalid_t42() -> None:
    from battery_workbench.features_physical.engine import compute_wave_speed

    assert compute_wave_speed(tof_s=0.0, path_length_m=0.01) is None
    assert compute_wave_speed(tof_s=-1e-6, path_length_m=0.01) is None


def test_thickness_not_auto_path_t43() -> None:
    """cell_thickness_m is never auto-substituted for path_length_m."""
    from battery_workbench.features_physical.engine import compute_wave_speed

    assert compute_wave_speed(tof_s=1e-6, path_length_m=None, cell_thickness_m=0.005) is None


# --- 10s/1250 guards ---


def test_10s_cadence_cannot_satisfy_fs() -> None:
    from battery_workbench.features_physical.engine import frame_cadence_cannot_resolve_fs

    assert frame_cadence_cannot_resolve_fs(10.0) is True


def test_sample_count_cannot_satisfy_fs() -> None:
    from battery_workbench.features_physical.engine import sample_count_cannot_resolve_fs

    assert sample_count_cannot_resolve_fs(1250) is True


# --- Unit conversion ---


def test_100mhz_to_1e8hz() -> None:
    from battery_workbench.feature_registry.facade import mhz_to_hz

    assert mhz_to_hz(100.0) == pytest.approx(1e8)


def test_unverified_critical_gate() -> None:
    from battery_workbench.feature_registry.facade import unverified_unlocks_nothing

    assert unverified_unlocks_nothing("UNVERIFIED") is True
    assert unverified_unlocks_nothing("VERIFIED") is False

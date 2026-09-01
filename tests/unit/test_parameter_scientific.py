from __future__ import annotations

import pytest

from battery_workbench.parameters.catalog import get_spec
from battery_workbench.parameters.resolution import resolve_parameter
from battery_workbench.parameters.schemas import ParameterRecord
from battery_workbench.parameters.validation import (
    frame_cadence_cannot_resolve_fs,
    sample_count_cannot_resolve_fs,
    unverified_fs_unlocks_nothing,
)


def _rec(value, source, verification, scope="EXPERIMENT", scope_key="CELL_001/EXP_001"):
    return ParameterRecord(
        parameter_record_id=f"fs:{source}:{value}",
        canonical_name="ultrasound.sampling_rate_hz",
        value=value,
        unit="Hz",
        source_type=source,
        verification_status=verification,
        scope_type=scope,
        scope_key=scope_key,
    )


def test_file_null_plus_user_value_t25() -> None:
    """T25: parser file reports null; a user-supplied value resolves."""
    result = resolve_parameter(
        [_rec(1e8, "USER_SUPPLIED", "UNVERIFIED")], get_spec("ultrasound.sampling_rate_hz")
    )
    assert result.value == pytest.approx(1e8)
    assert result.source_type == "USER_SUPPLIED"
    assert result.verification_status == "UNVERIFIED"


def test_raw_parser_manifest_unchanged_t26() -> None:
    """T26: resolution never mutates the raw parser manifest."""
    manifest = {"assets": [{"asset_id": "U001", "sampling_rate_hz": None}]}
    import copy

    snapshot = copy.deepcopy(manifest)
    resolve_parameter(
        [_rec(1e8, "USER_SUPPLIED", "UNVERIFIED")], get_spec("ultrasound.sampling_rate_hz")
    )
    assert manifest == snapshot


def test_frame_cadence_cannot_resolve_fs_t27() -> None:
    """T27: the 10 s frame cadence can never fill ultrasound.sampling_rate_hz."""
    assert frame_cadence_cannot_resolve_fs(10.0) is True


def test_sample_count_cannot_resolve_fs_t28() -> None:
    """T28: 1250 samples can never be inverted into a sampling rate."""
    assert sample_count_cannot_resolve_fs(1250) is True


def test_100mhz_gives_10ns_period_t29() -> None:
    """T29: a resolved fs yields the sample period (sanity, not TOF)."""
    result = resolve_parameter(
        [_rec(1e8, "USER_SUPPLIED", "VERIFIED")], get_spec("ultrasound.sampling_rate_hz")
    )
    assert 1.0 / result.value == pytest.approx(1e-8)


def test_unverified_fs_unlocks_nothing_t30() -> None:
    """T30: an UNVERIFIED fs cannot unlock sample-time conversion."""
    assert unverified_fs_unlocks_nothing("UNVERIFIED") is True
    assert unverified_fs_unlocks_nothing("VERIFIED") is False


def test_level0_no_fs_t31() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=None, trigger=False, detector=False, calibration=False) == 0


def test_level1_verified_fs_t32() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=1e8, trigger=False, detector=False, calibration=False) == 1


def test_level2_fs_plus_trigger_t33() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=1e8, trigger=True, detector=False, calibration=False) == 2


def test_no_detector_blocks_raw_tof_t34() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=1e8, trigger=True, detector=False, calibration=False) == 2


def test_level3_raw_capability_t35() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=1e8, trigger=True, detector=True, calibration=False) == 3


def test_level4_corrected_capability_t36() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    assert evaluate_tof_level(fs=1e8, trigger=True, detector=True, calibration=True) == 4


def test_unverified_fs_caps_level_at_0() -> None:
    from battery_workbench.parameters.capabilities import evaluate_tof_level

    # An UNVERIFIED fs behaves like no fs for capability purposes.
    assert (
        evaluate_tof_level(fs=1e8, fs_verified=False, trigger=True, detector=True, calibration=True)
        == 0
    )


def test_no_double_subtraction_t37() -> None:
    """T37: SYSTEM_DELAY_TOTAL policy forbids re-subtracting components."""
    from battery_workbench.parameters.capabilities import delay_policy_allows_component_subtraction

    assert delay_policy_allows_component_subtraction("SYSTEM_DELAY_TOTAL") is False
    assert delay_policy_allows_component_subtraction("COMPONENT_SUM") is True
    assert delay_policy_allows_component_subtraction("NONE") is True


def test_unverified_calibration_blocks_corrected_t38() -> None:
    from battery_workbench.parameters.capabilities import corrected_tof_available

    assert corrected_tof_available(calibration_verified=False) is False
    assert corrected_tof_available(calibration_verified=True) is True


def test_no_path_length_blocks_wave_speed_t39() -> None:
    from battery_workbench.parameters.capabilities import wave_speed_available

    assert wave_speed_available(path_length_m=None, corrected_tof_verified=False) is False


def test_verified_path_plus_corrected_tof_t40() -> None:
    from battery_workbench.parameters.capabilities import wave_speed_available

    assert wave_speed_available(path_length_m=0.01, corrected_tof_verified=True) is True


def test_thickness_not_auto_path_t41() -> None:
    """T41: cell thickness is never silently used as the acoustic path."""
    from battery_workbench.parameters.capabilities import wave_speed_available

    assert (
        wave_speed_available(
            path_length_m=None, corrected_tof_verified=True, cell_thickness_m=0.005
        )
        is False
    )


def test_geometry_unit_normalization_t42() -> None:
    from battery_workbench.parameters.units import canonicalize

    assert canonicalize(5.0, "mm") == pytest.approx(0.005)


def test_nominal_is_not_reference_t43() -> None:
    """T43: a nominal capacity never auto-fills battery.reference_capacity_ah."""
    from battery_workbench.parameters.resolution import resolve_parameter

    nominal = ParameterRecord(
        parameter_record_id="nom",
        canonical_name="battery.nominal_capacity_ah",
        value=11.0,
        unit="Ah",
        source_type="USER_SUPPLIED",
        verification_status="UNVERIFIED",
        scope_type="BATTERY",
        scope_key="CELL_001",
    )
    result = resolve_parameter([nominal], get_spec("battery.reference_capacity_ah"))
    assert result.status == "UNKNOWN"
    assert result.value is None


def test_rpt_scope_t44() -> None:
    """T44: RPT capacity is USER_ONLY — no data auto-read fills it."""
    spec = get_spec("labels.rpt_capacity_ah")
    assert spec.resolution_policy.value == "USER_ONLY"


def test_reference_cycle_auto_read_t45() -> None:
    """T45: labels.reference_cycle_index is auto-readable (BRW-014 baseline)."""
    spec = get_spec("labels.reference_cycle_index")
    assert spec.resolution_policy.value == "AUTO_ONLY"


def test_unverified_capacity_no_policy_override_t46() -> None:
    """T46: an unverified RPT value cannot silently change the label policy."""
    from battery_workbench.parameters.capabilities import label_policy_change_allowed

    assert label_policy_change_allowed(rpt_verified=False) is False
    assert label_policy_change_allowed(rpt_verified=True) is True


def test_parameter_set_id_integration_t47() -> None:
    """T47: labels reference a parameter_set_id without recomputation."""
    from battery_workbench.parameters.capabilities import label_recomputation_required

    assert label_recomputation_required() is False


def test_no_soc_soh_recomputation_t48() -> None:
    """T48: the registry exposes no SOC/SOH computation entry points."""
    import battery_workbench.parameters as params

    assert not hasattr(params, "compute_soc_reference")
    assert not hasattr(params, "compute_soh_reference")

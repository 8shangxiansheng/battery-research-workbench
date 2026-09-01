from __future__ import annotations

import pytest

from battery_workbench.parameters.catalog import (
    CANONICAL_PARAMETERS,
    get_spec,
    is_critical,
)
from battery_workbench.parameters.schemas import (
    ParameterRecord,
    ResolutionPolicy,
    ScopeType,
    SourceType,
    VerificationStatus,
)


def test_canonical_names_t01() -> None:
    """T01: catalog names are dot-namespaced and unique."""
    names = [p.canonical_name for p in CANONICAL_PARAMETERS]
    assert len(names) == len(set(names))
    assert all("." in n for n in names)
    assert "ultrasound.sampling_rate_hz" in names
    assert "battery.reference_capacity_ah" in names


def test_unknown_canonical_name_rejected() -> None:
    with pytest.raises(KeyError):
        get_spec("made.up.parameter")


def test_source_enum_t02() -> None:
    """T02: the full source enum exists."""
    expected = {
        "FILE_REPORTED",
        "MANIFEST_REPORTED",
        "EXPERIMENT_LOG",
        "INSTRUMENT_SETTING",
        "CALIBRATION_RECORD",
        "USER_SUPPLIED",
        "DERIVED_FROM_VERIFIED_PARAMETERS",
        "UNKNOWN",
    }
    assert set(SourceType) == expected


def test_verification_enum_t03() -> None:
    """T03: verification enum."""
    assert set(VerificationStatus) == {"VERIFIED", "UNVERIFIED", "CONFLICT", "UNKNOWN"}


def test_scope_enum_t04() -> None:
    """T04: scope enum includes all six levels."""
    assert set(ScopeType) == {"GLOBAL", "BATTERY", "EXPERIMENT", "DATA_ASSET", "CYCLE", "STEP"}


def test_scope_identity_t05() -> None:
    """T05: scope keys identify battery/experiment/asset targets."""
    r = ParameterRecord(
        canonical_name="ultrasound.sampling_rate_hz",
        value=1e8,
        unit="Hz",
        source_type="USER_SUPPLIED",
        verification_status="UNVERIFIED",
        scope_type="DATA_ASSET",
        scope_key="CELL_001/EXP_001/U001",
    )
    assert r.scope_key == "CELL_001/EXP_001/U001"
    assert r.scope_type == "DATA_ASSET"


def test_unknown_source_allowed_t06() -> None:
    """T06: UNKNOWN source/verification is representable, never guessed."""
    r = ParameterRecord(
        canonical_name="ultrasound.transducer_model",
        value=None,
        unit="text",
        source_type="UNKNOWN",
        verification_status="UNKNOWN",
        scope_type="DATA_ASSET",
        scope_key="CELL_001/EXP_001/U001",
    )
    assert r.source_type == "UNKNOWN"
    assert r.verification_status == "UNKNOWN"


def test_critical_flags_t07() -> None:
    """T07: the scientific-critical set matches the task contract."""
    critical = {
        "ultrasound.sampling_rate_hz",
        "ultrasound.trigger_sample_index",
        "ultrasound.system_delay_s",
        "experiment.ultrasound_path_length_m",
        "battery.reference_capacity_ah",
        "labels.rpt_capacity_ah",
    }
    flagged = {p.canonical_name for p in CANONICAL_PARAMETERS if p.critical}
    assert critical <= flagged
    assert is_critical("ultrasound.sampling_rate_hz")
    assert not is_critical("ultrasound.transducer_model")


def test_user_source_preserved_t08() -> None:
    """T08: a USER_SUPPLIED record keeps its source type verbatim."""
    r = ParameterRecord(
        canonical_name="ultrasound.sampling_rate_hz",
        value=1e8,
        unit="Hz",
        source_type="USER_SUPPLIED",
        verification_status="UNVERIFIED",
        scope_type="EXPERIMENT",
        scope_key="CELL_001/EXP_001",
    )
    assert r.source_type == "USER_SUPPLIED"
    assert r.verification_status == "UNVERIFIED"


def test_user_only_params_exist() -> None:
    """User principle: params that cannot be derived from data are USER_ONLY."""
    assert (
        get_spec("experiment.ultrasound_path_length_m").resolution_policy
        == ResolutionPolicy.USER_ONLY
    )
    assert get_spec("ultrasound.system_delay_s").resolution_policy == ResolutionPolicy.USER_ONLY
    assert get_spec("labels.rpt_capacity_ah").resolution_policy == ResolutionPolicy.USER_ONLY


def test_auto_only_params_exist() -> None:
    """User principle: data-factual params are AUTO_ONLY (user cannot override)."""
    assert (
        get_spec("ultrasound.acquisition_window_samples").resolution_policy
        == ResolutionPolicy.AUTO_ONLY
    )
    assert get_spec("battery.reference_capacity_ah").resolution_policy == ResolutionPolicy.AUTO_ONLY


def test_fs_is_auto_read_then_user() -> None:
    """User principle: fs is critical — auto-read when data provides it, else user."""
    assert (
        get_spec("ultrasound.sampling_rate_hz").resolution_policy
        == ResolutionPolicy.AUTO_READ_THEN_USER
    )

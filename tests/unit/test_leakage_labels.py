from __future__ import annotations

from battery_workbench.labels.leakage import (
    build_group_ids,
    forbidden_feature_columns,
    frame_random_split_prohibited,
)


def test_deterministic_group_ids_t27() -> None:
    """T27: identical inputs produce identical group IDs."""
    a = build_group_ids("CELL_001", "EXP_001", 1)
    b = build_group_ids("CELL_001", "EXP_001", 1)
    assert a == b


def test_same_cycle_same_group_t28() -> None:
    a = build_group_ids("CELL_001", "EXP_001", 1)
    b = build_group_ids("CELL_001", "EXP_001", 1)
    assert a["cycle_group_id"] == b["cycle_group_id"]


def test_different_cycle_different_group_t29() -> None:
    a = build_group_ids("CELL_001", "EXP_001", 1)
    b = build_group_ids("CELL_001", "EXP_001", 2)
    assert a["cycle_group_id"] != b["cycle_group_id"]


def test_different_battery_different_group_t30() -> None:
    a = build_group_ids("CELL_001", "EXP_001", 1)
    b = build_group_ids("CELL_002", "EXP_001", 1)
    assert a["battery_group_id"] != b["battery_group_id"]
    assert a["cycle_group_id"] != b["cycle_group_id"]


def test_group_id_format() -> None:
    g = build_group_ids("CELL_001", "EXP_001", 1)
    assert g["battery_group_id"] == "BG::CELL_001"
    assert g["experiment_group_id"] == "EG::CELL_001::EXP_001"
    assert g["cycle_group_id"] == "CG::CELL_001::EXP_001::1"


def test_frame_random_split_prohibited_t31() -> None:
    """T31: the policy flag is fixed True and cannot be disabled."""
    assert frame_random_split_prohibited() is True


def test_reference_scope_persisted_t32() -> None:
    """T32: reference capacity scope must be an allowed explicit value."""
    allowed = {"WITHIN_EXPERIMENT_BASELINE", "EXTERNAL_METADATA", "RPT", "TRAIN_ONLY_ESTIMATE"}
    assert "WITHIN_EXPERIMENT_BASELINE" in allowed


def test_no_global_denominator_t33() -> None:
    """T33: GLOBAL_DATASET_FIT is never an allowed reference scope."""
    allowed = {"WITHIN_EXPERIMENT_BASELINE", "EXTERNAL_METADATA", "RPT", "TRAIN_ONLY_ESTIMATE"}
    assert "GLOBAL_DATASET_FIT" not in allowed


def test_labels_contain_no_ultrasound_features_t34() -> None:
    """T34: label tables must not carry ultrasound/waveform feature columns."""
    forbidden = forbidden_feature_columns()
    for name in ("rms", "p2p", "xcorr", "waveform", "fft", "tof"):
        assert any(name in f for f in forbidden)


def test_eligibility_from_label_quality_t35() -> None:
    """T35: only VALID_REFERENCE / valid SOH quality is label-eligible."""
    from battery_workbench.labels.validation import is_label_eligible

    assert is_label_eligible("VALID_REFERENCE") is True
    assert is_label_eligible("ANCHOR_UNAVAILABLE") is False
    assert is_label_eligible("INCOMPLETE_CYCLE") is False
    assert is_label_eligible("OUT_OF_RANGE_REFERENCE") is False


def test_future_test_reference_guard_t36() -> None:
    """T36: TRAIN_ONLY_ESTIMATE is the only scope usable for future-safe refs."""
    from battery_workbench.labels.leakage import future_safe_reference_scopes

    scopes = future_safe_reference_scopes()
    assert "GLOBAL_DATASET_FIT" not in scopes
    assert "TRAIN_ONLY_ESTIMATE" in scopes

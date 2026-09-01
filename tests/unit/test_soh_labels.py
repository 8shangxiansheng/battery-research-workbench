"""BRW-014 V2: SOH readiness guard + label versioning tests (T25-T24..T30)."""

from __future__ import annotations

from pathlib import Path


def test_only_two_independent_states_t25() -> None:
    """T25: the readiness guard reports the true independent state count."""
    from battery_workbench.labels.soh import soh_model_readiness

    r = soh_model_readiness(independent_state_count=2)
    assert r.independent_state_count == 2
    assert r.readiness == "NOT_READY_FOR_ROBUST_SUPERVISED_LEARNING"
    assert r.suitable_for_supervised_learning is False


def test_soh_readiness_threshold_t26() -> None:
    """T26: the guard is data-driven, not hardcoded to fail forever."""
    from battery_workbench.labels.soh import soh_model_readiness

    ok = soh_model_readiness(independent_state_count=30, min_states=20)
    assert ok.readiness == "READY_FOR_SUPERVISED_LEARNING_CANDIDATE"
    assert ok.suitable_for_supervised_learning is True


def test_no_synthetic_soh_interpolation_t27() -> None:
    """T27: the SOH module exposes no interpolation/fabrication helpers."""
    from battery_workbench.labels import soh

    for forbidden in ("interpolate", "augment", "synthetic_states", "add_noise"):
        assert not hasattr(soh, forbidden)


def test_frame_rows_are_not_state_count() -> None:
    """T28: readiness is computed from cycle count, never frame count."""
    from battery_workbench.labels.soh import soh_model_readiness

    r = soh_model_readiness(independent_state_count=2, frame_count=3999)
    assert r.readiness == "NOT_READY_FOR_ROBUST_SUPERVISED_LEARNING"
    assert r.frame_count == 3999  # recorded, but does not change readiness


def test_v2_formula_version_t21(tmp_path: Path) -> None:
    """T21: config carries the bumped version."""
    from battery_workbench.labels.schemas import LabelConfig

    cfg = LabelConfig()
    assert cfg.soc.formula_version == "0.2.0"
    assert cfg.label_definition_version == "0.2.0"


def test_temporality_enum_v2() -> None:
    import typing

    from battery_workbench.labels.schemas import SocTemporality

    values = set(typing.get_args(SocTemporality))
    assert "RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE" in values

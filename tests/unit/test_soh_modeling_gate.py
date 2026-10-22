"""SOH modeling gate contract (BRW SOH target enablement).

Locks the SOC_MODELING node's decision for the capacity-ratio SOH target:

- SOH is a *supported* target, gated by the number of distinct SOH reference
  values — never by the target name alone.
- Event/frame rows are not independent states: a dataset with thousands of rows
  but few distinct reference values is still not ready.
- The gate must read distinct reference values, matching the FeatureAnalysis
  ``UA::SOH_NOT_READY`` gate and the dataset readiness notion, so upstream and
  downstream gates cannot disagree.

The threshold mirrors FeatureAnalysis (3). Real activation additionally requires
more ageing cycles and independent batteries; these tests use synthetic dataset
manifests and make no claim about real cross-state or cross-battery evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.orchestrator.nodes import (
    _SOH_MIN_INDEPENDENT_STATES,
    SocModelingNode,
)
from battery_workbench.orchestrator.schemas import ArtifactRef

NODE = SocModelingNode()


class _Plan:
    """Minimal plan surface consumed by the modeling readiness gates."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.modeling: dict = {}


def _dataset_manifest(
    tmp_path: Path,
    *,
    distinct_target_values: int,
    independent_soh_state_count: int | None = None,
    dataset_family: str = "SOH_CAPACITY",
) -> ArtifactRef:
    """Write a synthetic SOH dataset manifest and return its artifact ref.

    ``distinct_target_values`` is what the dataset builder persists as the
    distinct SOH reference value count for the SOH_CAPACITY family.
    """
    manifest: dict[str, object] = {
        "dataset_id": "DS::synthetic-soh",
        "battery_id": "CELL_X",
        "experiment_id": "EXP_X",
        "dataset_family": dataset_family,
        "distinct_target_values": distinct_target_values,
    }
    if independent_soh_state_count is not None:
        manifest["independent_soh_state_count"] = independent_soh_state_count
    manifest_path = tmp_path / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return ArtifactRef(
        artifact_type="DATASET",
        artifact_id="DS::synthetic-soh",
        battery_id="CELL_X",
        experiment_id="EXP_X",
        path=str(tmp_path / "dataset.parquet"),
        manifest_path=str(manifest_path),
    )


def _soh_inputs(tmp_path: Path, **kwargs) -> dict[str, ArtifactRef]:
    return {"DATASET": _dataset_manifest(tmp_path, **kwargs)}


def test_soh_modeling_blocks_below_minimum_distinct_states(tmp_path: Path) -> None:
    """Two distinct reference values cannot support a supervised evaluation."""
    readiness = NODE.validate_readiness(_Plan("soh_capacity_reference_percent"),
                                        _soh_inputs(tmp_path, distinct_target_values=2))

    assert not readiness.ok
    assert "distinct SOH reference values" in readiness.reason
    assert readiness.user_action is not None
    assert readiness.user_action.action_type == "SOH_MODELING_NOT_READY"
    assert readiness.user_action.blocking is True


def test_soh_modeling_passes_at_minimum_distinct_states(tmp_path: Path) -> None:
    """Reaching the threshold clears the independent-state gate.

    Feature-selection confirmation is a separate on-disk artifact concern, so
    readiness here only asserts the state gate is satisfied.
    """
    readiness = NODE.validate_readiness(
        _Plan("soh_capacity_reference_percent"),
        _soh_inputs(tmp_path, distinct_target_values=_SOH_MIN_INDEPENDENT_STATES),
    )

    assert readiness.ok, readiness.reason


def test_event_rows_are_not_counted_as_independent_states(tmp_path: Path) -> None:
    """A large group count must not substitute for distinct reference values.

    The gate input is the distinct-value count, so many independent groups that
    still carry only two distinct SOH values remain blocked.
    """
    readiness = NODE.validate_readiness(
        _Plan("soh_capacity_reference_percent"),
        _soh_inputs(tmp_path, distinct_target_values=2, independent_soh_state_count=500),
    )

    assert not readiness.ok
    assert "distinct SOH reference values" in readiness.reason


def test_gate_reads_distinct_values_not_group_count(tmp_path: Path) -> None:
    """Locks the gate口径: distinct reference values, not group cardinality.

    FeatureAnalysis gates on ``soh_capacity_reference_percent.nunique()``; the
    modeling gate must use the same measure so the two cannot disagree.
    """
    assert NODE._independent_soh_states(
        _soh_inputs(tmp_path, distinct_target_values=4, independent_soh_state_count=2)
    ) == 4
    assert NODE._independent_soh_states(
        _soh_inputs(tmp_path, distinct_target_values=2, independent_soh_state_count=9)
    ) == 2


def test_missing_dataset_artifact_blocks_soh_modeling(tmp_path: Path) -> None:
    """An unknown state count must block rather than assume readiness."""
    readiness = NODE.validate_readiness(_Plan("soh_capacity_reference_percent"), {})

    assert not readiness.ok
    assert readiness.user_action is not None
    assert readiness.user_action.action_type == "SOH_MODELING_NOT_READY"


def test_soh_target_with_non_soh_dataset_family_is_blocked(tmp_path: Path) -> None:
    """A non-SOH dataset cannot satisfy the SOH state gate.

    The builder persists ``distinct_target_values=0`` for non-SOH families, so
    the observed count is 0 and the gate blocks instead of reading an unrelated
    value off the wrong dataset family.
    """
    inputs = _soh_inputs(
        tmp_path,
        distinct_target_values=0,
        independent_soh_state_count=2,
        dataset_family="SOC",
    )

    assert NODE._independent_soh_states(inputs) == 0
    readiness = NODE.validate_readiness(_Plan("soh_capacity_reference_percent"), inputs)
    assert not readiness.ok
    assert readiness.user_action is not None
    assert readiness.user_action.action_type == "SOH_MODELING_NOT_READY"


def test_soc_target_is_unaffected_by_the_soh_gate(tmp_path: Path) -> None:
    """The Reference SOC contract keeps its existing unconditional readiness."""
    readiness = NODE.validate_readiness(_Plan("soc_reference_percent"), {})

    assert readiness.ok
    assert "modeling spec present" in readiness.reason


def test_unsupported_targets_still_rejected(tmp_path: Path) -> None:
    """Targets outside the supported set remain hard-rejected."""
    for target in ("temperature_c", "unknown_target"):
        readiness = NODE.validate_readiness(_Plan(target), {})
        assert not readiness.ok
        assert "only supports" in readiness.reason


def test_soc_bin_diagnostics_are_soh_specific_not_reported_for_soh() -> None:
    """SOC bin diagnostics describe the SOC target scale only.

    The modeling loop passes ``soc_bins=target != _SOH_TARGET``, so an SOH
    evaluation reports overall metrics without SOC-scale binning.
    """
    import numpy as np

    from battery_workbench.modeling.engine import evaluate_predictions

    y_true = np.array([95.0, 96.0, 97.0, 98.0])
    y_pred = np.array([95.5, 95.5, 97.5, 98.5])

    soh_metrics = evaluate_predictions(y_true, y_pred, step_type=None, soc_bins=False)
    soc_metrics = evaluate_predictions(y_true, y_pred, step_type=None, soc_bins=True)

    assert "soc_bin_diagnostics" not in soh_metrics
    assert soh_metrics["overall"]["MAE"] == soc_metrics["overall"]["MAE"]
    assert "soc_bin_diagnostics" in soc_metrics

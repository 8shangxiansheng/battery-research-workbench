"""Capacity-based SOH reference labels (BRW-014).

``SOH_Q(cycle) = 100 * Q_discharge_measured(cycle) / Q_ref`` where ``Q_ref``
comes from the baseline cycle's complete discharge capacity (never a guessed
nominal capacity, never a GLOBAL_DATASET_FIT). The baseline cycle's SOH=100 is
a definitional result, not an absolute vendor claim.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ReferenceCapacity:
    q_ref_ah: float
    reference_cycle_index: int
    reference_capacity_source: str


def select_reference_capacity(
    cycles: pd.DataFrame,
    *,
    rpt_capacity_ah: float | None = None,
) -> ReferenceCapacity:
    """Select Q_ref: explicit RPT when provided, else the baseline cycle."""
    if rpt_capacity_ah is not None and rpt_capacity_ah > 0:
        baseline = cycles.sort_values("cycle_index_raw").iloc[0]
        return ReferenceCapacity(
            q_ref_ah=float(rpt_capacity_ah),
            reference_cycle_index=int(baseline["cycle_index_raw"]),
            reference_capacity_source="RPT",
        )
    complete = cycles[
        cycles["discharge_capacity_ah"].notna() & (cycles["discharge_capacity_ah"] > 0)
    ]
    if complete.empty:
        raise ValueError("no complete cycle with a positive discharge capacity")
    baseline = complete.sort_values("cycle_index_raw").iloc[0]
    return ReferenceCapacity(
        q_ref_ah=float(baseline["discharge_capacity_ah"]),
        reference_cycle_index=int(baseline["cycle_index_raw"]),
        reference_capacity_source="BASELINE_CYCLE",
    )


def compute_soh_reference(*, q_discharge_ah: float | None, q_ref_ah: float) -> SohLabelResult:
    """Compute one capacity-based SOH reference value."""
    if q_discharge_ah is None or q_ref_ah <= 0:
        return SohLabelResult(
            soh_capacity_reference_percent=None,
            soh_reference_quality="REFERENCE_CAPACITY_UNAVAILABLE",
            soh_label_eligible=False,
        )
    soh = 100.0 * q_discharge_ah / q_ref_ah
    return SohLabelResult(
        soh_capacity_reference_percent=soh,
        soh_reference_quality="VALID_REFERENCE",
        soh_label_eligible=True,
    )


@dataclass
class SohLabelResult:
    soh_capacity_reference_percent: float | None
    soh_reference_quality: str
    soh_label_eligible: bool


def build_cycle_soh_labels(
    cycles: pd.DataFrame,
    *,
    reference: ReferenceCapacity,
) -> pd.DataFrame:
    """Attach SOH reference labels to every cycle row (exact cycle keys)."""
    out = cycles.copy()
    soh_values: list[float | None] = []
    ref_cycle: list[int] = []
    qualities: list[str] = []
    eligible: list[bool] = []
    for _, row in out.iterrows():
        result = compute_soh_reference(
            q_discharge_ah=row["discharge_capacity_ah"]
            if pd.notna(row["discharge_capacity_ah"])
            else None,
            q_ref_ah=reference.q_ref_ah,
        )
        soh_values.append(result.soh_capacity_reference_percent)
        ref_cycle.append(reference.reference_cycle_index)
        qualities.append(result.soh_reference_quality)
        eligible.append(result.soh_label_eligible)
    out["reference_capacity_ah"] = reference.q_ref_ah
    out["reference_capacity_source"] = reference.reference_capacity_source
    out["reference_capacity_source_scope"] = "WITHIN_EXPERIMENT_BASELINE"
    # Canonical measured-capacity naming per the BRW-014 output contract.
    out["charge_capacity_measured_ah"] = out["charge_capacity_ah"]
    out["discharge_capacity_measured_ah"] = out["discharge_capacity_ah"]
    out["cycle_complete"] = out["discharge_capacity_ah"].notna() & (
        out["discharge_capacity_ah"] > 0
    )
    out["soh_capacity_reference_percent"] = soh_values
    out["soh_reference_cycle_index"] = ref_cycle
    out["soh_reference_quality"] = qualities
    out["soh_label_eligible"] = eligible
    out["soh_reference_method"] = "CAPACITY_BASELINE_RATIO"
    out["soh_formula_version"] = "0.1.0"
    return out


@dataclass
class SohModelReadiness:
    independent_state_count: int
    frame_count: int | None
    readiness: str
    suitable_for_supervised_learning: bool


def soh_model_readiness(
    *,
    independent_state_count: int,
    frame_count: int | None = None,
    min_states: int = 20,
) -> SohModelReadiness:
    """Guard: SOH supervised-learning readiness from the TRUE state count.

    Frame count is recorded but never substitutes for independent cycle-level
    states. Diversity is a data-collection property — never manufactured.
    """
    ready = independent_state_count >= min_states
    return SohModelReadiness(
        independent_state_count=independent_state_count,
        frame_count=frame_count,
        readiness=(
            "READY_FOR_SUPERVISED_LEARNING_CANDIDATE"
            if ready
            else "NOT_READY_FOR_ROBUST_SUPERVISED_LEARNING"
        ),
        suitable_for_supervised_learning=ready,
    )

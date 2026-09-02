"""BRW-020 evaluation readiness.

Wording is scientific, not marketing: 1 battery can only ever be a
within-battery cross-cycle limited evaluation. SOH event rows are not
independent states.
"""

from __future__ import annotations

from typing import Any


def evaluate_readiness(
    *,
    dataset_family: str,
    independent_soh_states: int | None,
    battery_count: int,
    cycle_group_count: int,
) -> dict[str, Any]:
    limitations: list[str] = []
    if dataset_family == "SOH_CAPACITY" and (
        independent_soh_states is not None and independent_soh_states < 3
    ):
        return {
            "status": "NOT_READY_FOR_MODEL_EVALUATION",
            "reason": (
                f"only {independent_soh_states} independent SOH states "
                "(event rows are not independent states)"
            ),
            "independent_soh_states": independent_soh_states,
            "battery_count": battery_count,
            "limitations": [
                "SOH event rows are not independent states",
                "no supervised evaluation protocol is scientifically meaningful yet",
            ],
        }
    if battery_count < 2:
        limitations.append("within-battery cross-cycle evaluation only — NOT cross-battery")
    if cycle_group_count < 3:
        limitations.append(
            f"only {cycle_group_count} cycle groups: 3-way train/val/test impossible; "
            "leave-one-group-out limited evaluation recommended"
        )
    return {
        "status": "READY_FOR_LIMITED_EVALUATION",
        "battery_count": battery_count,
        "cycle_group_count": cycle_group_count,
        "evaluation_scope": "WITHIN_BATTERY_CROSS_CYCLE",
        "limitations": limitations,
    }

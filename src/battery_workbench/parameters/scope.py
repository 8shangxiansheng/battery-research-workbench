"""Scope specificity ordering for BRW-015.

``STEP > CYCLE > DATA_ASSET > EXPERIMENT > BATTERY > GLOBAL`` — used only as a
tiebreaker AFTER verification, per the frozen precedence policy.
"""

from __future__ import annotations

from battery_workbench.parameters.schemas import ScopeType

SCOPE_PRIORITY: dict[str, int] = {
    ScopeType.STEP.value: 60,
    ScopeType.CYCLE.value: 50,
    ScopeType.DATA_ASSET.value: 40,
    ScopeType.EXPERIMENT.value: 30,
    ScopeType.BATTERY.value: 20,
    ScopeType.GLOBAL.value: 10,
}


def scope_priority(scope_type: str | ScopeType) -> int:
    return SCOPE_PRIORITY.get(str(scope_type), 0)

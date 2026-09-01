"""Parameter resolution engine for BRW-015.

Frozen precedence policy:

1. **Verification** is the primary key — VERIFIED beats UNVERIFIED at any scope.
2. **Scope specificity** (STEP > CYCLE > DATA_ASSET > EXPERIMENT > BATTERY >
   GLOBAL) breaks ties within the same verification class.
3. **Source priority** (CALIBRATION > INSTRUMENT > DERIVED > LOG > MANIFEST >
   FILE > USER) breaks further ties, deterministically.

Records agreeing on the normalized value coexist; equal-precedence records
disagreeing on the value produce a CONFLICT that blocks selection. Losing
records are retained as ``shadowed_records``. The engine never mutates raw
parser manifests.
"""

from __future__ import annotations

from battery_workbench.parameters.catalog import ParameterSpec
from battery_workbench.parameters.schemas import (
    EffectiveParameter,
    ParameterRecord,
)
from battery_workbench.parameters.scope import scope_priority
from battery_workbench.parameters.sources import (
    source_priority,
    verification_priority,
)
from battery_workbench.parameters.units import canonicalize


def _sort_key(record: ParameterRecord) -> tuple[int, int, int, str]:
    return (
        verification_priority(str(record.verification_status)),
        scope_priority(str(record.scope_type)),
        source_priority(str(record.source_type)),
        record.parameter_record_id,
    )


def _normalized_value(record: ParameterRecord, spec: ParameterSpec) -> float | str | None:
    """Canonical value of a record; unit-equivalent records compare equal."""
    if record.value is None:
        return None
    if isinstance(record.value, str):
        return record.value
    try:
        return canonicalize(float(record.value), record.unit, dimension=spec.dimension)
    except (TypeError, ValueError):  # malformed value/unit -> treated as absent
        return None


def resolve_parameter(
    records: list[ParameterRecord],
    spec: ParameterSpec,
    *,
    target_scope_key: str | None = None,
) -> EffectiveParameter:
    """Resolve one canonical parameter from candidate records.

    ``target_scope_key`` (when given) excludes records that belong to a
    sibling target (e.g. another battery/experiment) at the same scope type;
    GLOBAL-scope records always participate.
    """
    effective = EffectiveParameter(
        canonical_name=spec.canonical_name,
        critical=spec.critical,
    )

    def _in_target(record: ParameterRecord) -> bool:
        if target_scope_key is None:
            return True
        if str(record.scope_type) == "GLOBAL":
            return True
        key = record.scope_key
        return (
            key == target_scope_key
            or target_scope_key.startswith(key + "/")
            or key.startswith(target_scope_key + "/")
        )

    candidates = [
        r
        for r in records
        if r.canonical_name == spec.canonical_name and r.value is not None and _in_target(r)
    ]
    if not candidates:
        effective.resolution_reason = "no candidate records; parameter stays UNKNOWN"
        return effective

    candidates = sorted(candidates, key=_sort_key, reverse=True)
    top = candidates[0]
    top_value = _normalized_value(top, spec)

    # Disagreement detection: any record whose normalized value differs from
    # the top candidate AND whose precedence ties with it -> CONFLICT (block).
    top_key = _sort_key(top)
    agreeing: list[ParameterRecord] = []
    conflicting: list[ParameterRecord] = []
    for record in candidates[1:]:
        value = _normalized_value(record, spec)
        if value is not None and top_value is not None and value != top_value:
            conflicting.append(record)
        else:
            agreeing.append(record)

    tied_conflicts = [
        c
        for c in conflicting
        if _sort_key(c)[:2] == top_key[:2]
        and source_priority(str(c.source_type)) == source_priority(str(top.source_type))
    ]
    if tied_conflicts:
        effective.status = "CONFLICT"
        effective.verification_status = "CONFLICT"
        effective.resolution_reason = (
            f"equal-precedence records disagree on {spec.canonical_name}: "
            f"{top_value} vs {_normalized_value(tied_conflicts[0], spec)}; blocked, no silent selection"
        )
        effective.shadowed_records = [c.parameter_record_id for c in candidates[1:]]
        return effective

    effective.status = "RESOLVED"
    effective.value = top_value
    effective.unit = spec.unit
    effective.selected_parameter_record_id = top.parameter_record_id
    effective.source_type = str(top.source_type)
    effective.verification_status = str(top.verification_status)
    effective.resolution_reason = (
        f"selected by verification={top.verification_status}, "
        f"scope={top.scope_type}, source={top.source_type}"
    )
    effective.shadowed_records = [c.parameter_record_id for c in candidates[1:]]
    return effective

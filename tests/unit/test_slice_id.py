from __future__ import annotations

import json

from battery_workbench.analysis.schemas import ConditionSliceSpec
from battery_workbench.analysis.slice_id import (
    build_analysis_slice_id,
    normalize_spec,
)


def test_normalize_list_order_t22() -> None:
    """T22: list values sort on normalization."""
    assert normalize_spec({"cycle_indices": [2, 1, 3]})["cycle_indices"] == [1, 2, 3]


def test_normalize_duplicates_t23() -> None:
    """T23: duplicate list values are deduplicated."""
    normalized = normalize_spec({"cycle_indices": [2, 1, 1, 2]})
    assert normalized["cycle_indices"] == [1, 2]


def test_deterministic_id_same_spec_t24() -> None:
    """T24: same input checksum + normalized spec yields the same id."""
    spec = ConditionSliceSpec(cycle_indices=[1], analysis_eligible_only=True)
    n = normalize_spec(spec.model_dump(mode="json"))
    a = build_analysis_slice_id("abc" * 12, n)
    b = build_analysis_slice_id("abc" * 12, n)
    assert a == b
    assert a.startswith("AS::")


def test_different_checksum_different_id_t25() -> None:
    """T25: different input checksum yields a different id (same spec)."""
    spec = ConditionSliceSpec(cycle_indices=[1])
    n = normalize_spec(spec.model_dump(mode="json"))
    a = build_analysis_slice_id("a" * 12, n)
    b = build_analysis_slice_id("b" * 12, n)
    assert a != b


def test_different_spec_different_id() -> None:
    """Different normalized spec (same checksum) yields a different id."""
    n1 = normalize_spec(ConditionSliceSpec(cycle_indices=[1]).model_dump(mode="json"))
    n2 = normalize_spec(ConditionSliceSpec(cycle_indices=[2]).model_dump(mode="json"))
    a = build_analysis_slice_id("c" * 12, n1)
    b = build_analysis_slice_id("c" * 12, n2)
    assert a != b


def test_canonical_serialization_json_safe() -> None:
    """The normalized spec serializes to stable JSON (sort_keys, no spaces)."""
    n = normalize_spec({"b": [2, 1], "a": 3})
    text = json.dumps(n, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert text.startswith('{"a":3,"b":[1,2]}')

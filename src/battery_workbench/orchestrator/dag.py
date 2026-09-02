"""BRW-019 explicit dependency DAG.

The DAG mirrors the real repository contracts (manifests define what each
stage consumes). It is data, not science: the orchestrator only orders and
invalidates — it never computes.
"""

from __future__ import annotations

NODE_DEPENDENCIES: dict[str, list[str]] = {
    "ELECTRICAL_CANONICAL": [],
    "ULTRASOUND_CANONICAL": [],
    "TIME_ANCHOR": ["ULTRASOUND_CANONICAL"],
    "ULTRASOUND_TIMESTAMPS": ["ULTRASOUND_CANONICAL", "TIME_ANCHOR"],
    "SYNCHRONIZATION": ["ELECTRICAL_CANONICAL", "ULTRASOUND_TIMESTAMPS"],
    "MEASUREMENT_EVENTS": ["SYNCHRONIZATION"],
    "ANALYSIS_SLICE": ["MEASUREMENT_EVENTS"],
    "ULTRASOUND_FEATURES": ["ANALYSIS_SLICE"],
    "REFERENCE_LABELS": ["MEASUREMENT_EVENTS"],
    "PARAMETER_SET": ["MEASUREMENT_EVENTS"],
    "TOF_ACTIVATION": ["ULTRASOUND_FEATURES", "PARAMETER_SET"],
    "GATED_FEATURES": ["ANALYSIS_SLICE", "PARAMETER_SET"],
    "FEATURE_LABEL_ANALYSIS": ["GATED_FEATURES", "REFERENCE_LABELS", "PARAMETER_SET"],
    "DATASET": ["ULTRASOUND_FEATURES", "REFERENCE_LABELS", "PARAMETER_SET"],
    "FEATURE_ANALYSIS": ["FEATURE_LABEL_ANALYSIS"],
    "SPLIT": ["DATASET"],
}

# Optional (mode-conditional) upstream: resolved when present in the run, never
# required (e.g. ML-safe FEATURE_ANALYSIS additionally consumes DATASET + SPLIT).
NODE_OPTIONAL_DEPENDENCIES: dict[str, list[str]] = {
    "FEATURE_ANALYSIS": ["DATASET", "SPLIT"],
}


class CycleDetectedError(ValueError):
    pass


class UnknownNodeError(KeyError):
    pass


def topological_order(stages: list[str], dependencies: dict[str, list[str]]) -> list[str]:
    """Deterministic topological order (stable by first-seen index)."""
    unknown = [s for s in stages if s not in dependencies]
    if unknown:
        raise UnknownNodeError(f"unknown stages: {unknown}")
    index = {s: i for i, s in enumerate(stages)}
    order: list[str] = []
    state: dict[str, int] = {}  # 0=visiting, 1=done

    def visit(node: str) -> None:
        mark = state.get(node, 0)
        if mark == 1:
            return
        if mark == 0 and node in state:
            raise CycleDetectedError(f"dependency cycle through {node!r}")
        state[node] = 0
        for dep in dependencies.get(node, []):
            if dep in index:
                visit(dep)
        state[node] = 1
        order.append(node)

    for stage in stages:
        visit(stage)
    return order


def downstream_closure(node: str, dependencies: dict[str, list[str]]) -> set[str]:
    """All nodes that (transitively) depend on ``node``."""
    dependents: dict[str, set[str]] = {n: set() for n in dependencies}
    for n, deps in dependencies.items():
        for d in deps:
            dependents.setdefault(d, set()).add(n)
    closure: set[str] = set()
    frontier = [node]
    while frontier:
        current = frontier.pop()
        for dep in dependents.get(current, set()):
            if dep not in closure:
                closure.add(dep)
                frontier.append(dep)
    return closure

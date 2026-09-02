"""BRW-019 artifact lineage.

Answers "what is this artifact built from" by walking producer manifests'
declared upstream ids/paths. Structured JSON only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from battery_workbench.orchestrator.resolver import _resolve_manifest_path

_MAX_DEPTH = 12

# artifact_type → (manifest name, id key, path rel dir, input manifest keys
#                  that name upstream artifacts)
_UPSTREAM: dict[str, dict[str, Any]] = {
    "DATASET": {
        "manifest": "dataset_manifest.json",
        "dir": "datasets/{b}/{e}/{family}",
        "inputs": [
            ("ULTRASOUND_FEATURE_SET", "feature_set_id", "feature_set_path"),
            ("LABEL_SET", "label_set_id", "label_set_path"),
            ("PARAMETER_SET", "parameter_set_id", None),
        ],
    },
    "ULTRASOUND_FEATURE_SET": {
        "manifest": "feature_set_manifest.json",
        "dir": "features/{b}/{e}",
        "scan": True,
        "inputs": [("ANALYSIS_SLICE", "analysis_slice_id", "analysis_slice_path")],
    },
    "ANALYSIS_SLICE": {
        "manifest": "analysis_slice_manifest.json",
        "dir": "analysis_slices/{b}/{e}",
        "scan": True,
        "inputs": [("MEASUREMENT_EVENTS", None, "input_path")],
    },
    "MEASUREMENT_EVENTS": {
        "manifest": "measurement_event_manifest.json",
        "dir": "multimodal/{b}/{e}",
        "inputs": [
            ("SYNCHRONIZATION", None, "input_paths"),
            ("ELECTRICAL_CANONICAL", None, "input_paths"),
        ],
    },
    "SYNCHRONIZATION": {
        "manifest": "synchronization_manifest.json",
        "dir": "synchronization/{b}/{e}",
        "inputs": [
            ("ULTRASOUND_TIMESTAMPS", None, "input_paths"),
            ("ELECTRICAL_CANONICAL", None, "input_paths"),
        ],
    },
    "ULTRASOUND_TIMESTAMPS": {
        "manifest": "timestamp_engine_manifest.json",
        "dir": "synchronization/{b}/{e}",
        "inputs": [
            ("ULTRASOUND_CANONICAL", None, "input_paths"),
            ("TIME_ANCHORS", None, "input_paths"),
        ],
    },
    "LABEL_SET": {
        "manifest": "label_manifest.json",
        "dir": "labels/{b}/{e}",
        "inputs": [("MEASUREMENT_EVENTS", None, "input_paths")],
    },
    "PARAMETER_SET": {
        "manifest": "parameter_set_manifest.json",
        "dir": "parameters/{b}/{e}",
        "scan": True,
        "id_key": "parameter_set_id",
        "inputs": [("MEASUREMENT_EVENTS", None, "input_paths")],
    },
}


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _find_dir(
    processed_root: Path,
    rel_pattern: str,
    artifact_id: str | None,
    id_key: str | None,
    manifest_name: str,
) -> Path | None:
    base = processed_root / rel_pattern
    if not base.exists():
        return None
    if artifact_id:
        candidate = base / artifact_id
        if (candidate / manifest_name).exists():
            return candidate
        # nested layouts (features/{b}/{e}/AS::.../FS::...)
        for p in sorted(base.rglob(manifest_name)):
            if p.parent.name == artifact_id:
                return p.parent
        return None
    for p in sorted(base.rglob(manifest_name)):
        child = p.parent
        if id_key:
            m = _load_manifest(child / manifest_name)
            if m.get(id_key):
                return child
        return child
    return None


def get_artifact_lineage(
    *,
    artifact_type: str,
    artifact_id: str | None,
    battery_id: str,
    experiment_id: str,
    processed_root: Path,
    _depth: int = 0,
) -> dict[str, Any]:
    """Structured lineage: artifact → producer manifest → upstream subtree."""
    processed_root = Path(processed_root)
    spec = _UPSTREAM.get(artifact_type)
    node: dict[str, Any] = {
        "artifact": {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id or "",
            "battery_id": battery_id,
            "experiment_id": experiment_id,
        },
        "inputs": [],
    }
    if spec is None or _depth >= _MAX_DEPTH:
        return node

    manifest_name = spec["manifest"]
    rel_dir = spec["dir"].format(b=battery_id, e=experiment_id, family="SOC")
    artifact_dir = _find_dir(
        processed_root, rel_dir, artifact_id, spec.get("id_key"), manifest_name
    )
    if artifact_dir is None and spec.get("scan"):
        # family/scope variants (e.g. dataset family dirs)
        for family in ("SOC", "SOH_CAPACITY"):
            alt = spec["dir"].format(b=battery_id, e=experiment_id, family=family)
            artifact_dir = _find_dir(
                processed_root, alt, artifact_id, spec.get("id_key"), manifest_name
            )
            if artifact_dir is not None:
                break
    if artifact_dir is None:
        return node

    manifest = _load_manifest(artifact_dir / manifest_name)
    node["artifact"]["artifact_id"] = (
        str(manifest.get(spec["id_key"])) if spec.get("id_key") else artifact_dir.name
    )
    node["artifact"]["path"] = str(artifact_dir)
    node["manifest"] = manifest

    for upstream_type, upstream_id_key, path_key in spec["inputs"]:
        if path_key == "input_paths":
            input_paths = manifest.get("input_paths") or {}
            for key, raw in input_paths.items():
                resolved = _resolve_manifest_path(processed_root.parent / "data", raw)
                if Path(raw).exists():
                    resolved = Path(raw)
                elif not resolved.exists():
                    resolved = processed_root.parent / raw
                node["inputs"].append(
                    {
                        "artifact": {
                            "artifact_type": f"INPUT:{key}",
                            "artifact_id": "",
                            "path": str(resolved),
                        },
                        "inputs": [],
                    }
                )
            continue
        upstream_id = manifest.get(upstream_id_key) if upstream_id_key else None
        upstream_path = manifest.get(path_key) if path_key else None
        child: dict[str, Any] | None = None
        if upstream_type in _UPSTREAM:
            child = get_artifact_lineage(
                artifact_type=upstream_type,
                artifact_id=str(upstream_id) if upstream_id else None,
                battery_id=battery_id,
                experiment_id=experiment_id,
                processed_root=processed_root,
                _depth=_depth + 1,
            )
        else:
            child = {
                "artifact": {
                    "artifact_type": upstream_type,
                    "artifact_id": str(upstream_id or ""),
                    "path": str(upstream_path or ""),
                },
                "inputs": [],
            }
        node["inputs"].append(child)
    return node

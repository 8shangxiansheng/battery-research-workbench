"""BRW-022 selection provenance loading.

Only TRAIN_ONLY_ML_SAFE + confirmed selections are accepted for modeling.
EXPLORATORY_FULL_DATA selections BLOCK the formal path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SelectionNotUsableError(ValueError):
    pass


def load_fold_selection(
    *,
    dataset_id: str,
    split_id: str,
    fold_index: int,
    processed_root: Path,
) -> dict[str, Any]:
    """Load the confirmed TRAIN-only selection for one fold.

    Raises SelectionNotUsableError when no confirmed TRAIN_ONLY_ML_SAFE
    selection exists for this fold (exploratory selections BLOCK the formal
    path).
    """
    base = processed_root / "feature_analysis" / "CELL_001" / "EXP_001"
    best: dict[str, Any] | None = None
    for manifest_path in sorted(base.rglob("analysis_manifest.json")):
        m = json.loads(manifest_path.read_text())
        if m.get("analysis_mode") != "TRAIN_ONLY_ML_SAFE":
            continue
        if m.get("split_id") != split_id:
            continue
        if m.get("fold_index") != fold_index:
            continue
        sel = m.get("selection") or {}
        if sel.get("commit_status") != "CONFIRMED":
            best = None
            break
        if not sel.get("selected_features"):
            continue
        best = {
            "analysis_id": m["analysis_id"],
            "analysis_mode": m["analysis_mode"],
            "selection_id": sel["selection_id"],
            "selection_basis": sel["selection_basis"],
            "split_id": m["split_id"],
            "fold_index": m["fold_index"],
            "selected_features": sel["selected_features"],
            "policy_version": sel["policy_version"],
        }
        break
    if best is None:
        raise SelectionNotUsableError(
            "no confirmed TRAIN_ONLY_ML_SAFE selection for fold "
            f"{fold_index} (EXPLORATORY_FULL_DATA selections BLOCK the formal path)"
        )
    return best

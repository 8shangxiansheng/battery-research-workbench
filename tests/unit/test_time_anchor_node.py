from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from battery_workbench.orchestrator.nodes import TimeAnchorNode
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject


def test_time_anchor_node_uses_battery_and_experiment_composite_identity(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
    (manifest_root / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
        "EXP_001,CELL_A,2024-01-01T00:00:00,,,\n"
        "EXP_001,CELL_B,2024-02-01T00:00:00,,,\n",
        encoding="utf-8",
    )
    (manifest_root / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n",
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    plan = AnalysisPlan(
        profile="INGEST_TO_MEASUREMENT_EVENTS",
        project=PlanProject(battery_id="CELL_B", experiment_id="EXP_001"),
    )

    TimeAnchorNode().run(
        plan,
        {},
        SimpleNamespace(raw_root=raw_root, processed_root=processed_root),
    )

    state_path = (
        processed_root / "synchronization/CELL_B/EXP_001/time_anchors.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["experiment_reference"]["experiment_start_time"] == "2024-02-01T00:00:00"

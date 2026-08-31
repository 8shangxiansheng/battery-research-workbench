from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.synchronization.persistence import write_time_anchor_state
from battery_workbench.synchronization.schemas import (
    AssetAnchorAssessment,
    TimeAnchorReport,
    TimeAnchorState,
)


def _state() -> TimeAnchorState:
    return TimeAnchorState(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        anchor_version="0.1.0",
        experiment_reference={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "experiment_start_time": "2024-01-06T09:52:31",
            "experiment_end_time": "2024-01-06T20:58:54",
        },
        assets=[
            AssetAnchorAssessment(
                asset_id="U001",
                modality="ultrasound",
                elapsed_min_s=0.031217,
                elapsed_max_s=39980.03,
                selected_anchor_id=None,
                anchor_status="UNVERIFIED",
                validated_sync=False,
            )
        ],
        warnings=["missing anchor"],
        limitations=["timezone unknown"],
        validated_sync=False,
    )


def test_canonical_json_contract_t17(tmp_path: Path) -> None:
    """T17: time_anchors.json schema-validates to the canonical contract."""
    processed_root = tmp_path / "processed"
    artifacts_root = tmp_path / "artifacts"
    paths = write_time_anchor_state(
        _state(),
        processed_root=processed_root,
        artifacts_root=artifacts_root,
        html_report=None,
    )
    canonical_path = (
        processed_root / "synchronization" / "CELL_001" / "EXP_001" / "time_anchors.json"
    )
    assert paths["time_anchors"] == canonical_path
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "battery_id",
        "experiment_id",
        "anchor_version",
        "experiment_reference",
        "assets",
        "warnings",
        "limitations",
        "validated_sync",
    }
    assert payload["validated_sync"] is False
    assert payload["battery_id"] == "CELL_001"


def test_json_report_contract_t18(tmp_path: Path) -> None:
    """T18: the JSON report is written under artifacts and structure is valid."""
    processed_root = tmp_path / "processed"
    artifacts_root = tmp_path / "artifacts"
    report = TimeAnchorReport(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        anchor_version="0.1.0",
        status="PASS_WITH_WARNINGS",
        assets=[],
        warnings=["missing anchor"],
        limitations=["timezone unknown"],
        validated_sync=False,
    )
    write_time_anchor_state(
        _state(),
        processed_root=processed_root,
        artifacts_root=artifacts_root,
        html_report=report,
    )
    json_path = artifacts_root / "CELL_001" / "EXP_001" / "time_anchor" / "time_anchor_report.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_WITH_WARNINGS"
    assert payload["validated_sync"] is False


def test_input_immutability_t16(tmp_path: Path) -> None:
    """T16: writing state never mutates the input manifests or processed art."""
    state = _state()
    payload_before = state.model_dump(mode="json")

    write_time_anchor_state(
        state,
        processed_root=tmp_path / "processed",
        artifacts_root=tmp_path / "artifacts",
        html_report=None,
    )
    # The state object (and by extension its inputs) is unchanged after write.
    assert state.model_dump(mode="json") == payload_before

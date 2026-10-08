from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.service import WorkbenchService
from battery_workbench.orchestrator.nodes import DatasetNode


def test_temperature_spec_is_blocked_even_when_measurement_gate_passes(tmp_path, monkeypatch):
    service = WorkbenchService(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")
    monkeypatch.setattr(service, "_temperature_target_status", lambda *_: (True, ""))

    with pytest.raises(APIError) as exc_info:
        service.create_dataset(
            {
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "dataset_family": "SOC",
                "target": "temperature_c",
                "selected_features": ["SWA"],
            }
        )

    assert exc_info.value.code == ErrorCode.SCIENTIFIC_READINESS_BLOCKED
    assert "temperature target dataset/modeling is not implemented" in exc_info.value.message
    assert not (tmp_path / "processed/datasets/CELL_001/EXP_001/TEMPERATURE").exists()


def test_dataset_node_blocks_temperature_before_materialization():
    readiness = DatasetNode().validate_readiness(
        SimpleNamespace(target="temperature_c"), {}
    )
    assert readiness.ok is False
    assert "temperature target dataset/modeling is not implemented" in readiness.reason


def test_target_catalogue_separates_temperature_relationship_readiness_from_modeling(
    monkeypatch,
):
    from battery_workbench.api.routes import features_v2

    joined = pd.DataFrame(
        {
            "soc_reference_percent": [10.0, 20.0, 30.0],
            "soc_reference_method": ["REFERENCE"] * 3,
            "temperature_c": [23.2, 24.2, 25.3],
            "soh_capacity_reference_percent": [100.0, 100.0, 99.0],
            "voltage_v": [3.2, 3.5, 3.8],
            "current_a": [1.0, 0.0, -1.0],
        }
    )
    monkeypatch.setattr(features_v2, "_events_labels_joined", lambda *_: joined)

    response = features_v2.list_targets(None, "CELL_001", "EXP_001")
    temperature = next(
        row for row in response["data"]["targets"] if row["target_id"] == "temperature_c"
    )

    assert temperature["readiness"] == "READY"
    assert temperature["modeling_readiness"] == "NOT_IMPLEMENTED"
    assert temperature["coverage"] == {"valid": 3, "total": 3}
    assert "探索性" in temperature["limitation_zh"]

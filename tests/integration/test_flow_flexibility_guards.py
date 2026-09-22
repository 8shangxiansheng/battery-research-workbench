"""Flow flexibility audit guards: split folds inventory (read-only) and the
dataset-target readiness gate (non-SOC targets must never materialize a
mislabeled "SOC" dataset spec)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

SPLIT_ID = "SPLIT::23ebb24fe8e7732fac780dde"
has_real = (PROCESSED / "splits/CELL_001/EXP_001").is_dir()

pytestmark = pytest.mark.skipif(not has_real, reason="CELL_001/EXP_001 split artifacts required")


@pytest.fixture()
def client() -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=REPO / "data/artifacts/runs")
    return TestClient(app)


class TestSplitFolds:
    def test_folds_inventory_matches_assignments(self, client: TestClient) -> None:
        resp = client.get(
            f"/api/v1/experiments/CELL_001/EXP_001/splits/{SPLIT_ID}/folds"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["split_id"] == SPLIT_ID
        assert data["strategy"] == "LEAVE_ONE_GROUP_OUT"
        folds = {f["fold"]: (f["train_rows"], f["held_out_rows"]) for f in data["folds"]}
        assert folds == {"fold1": (1903, 2092), "fold2": (2092, 1903)}

    def test_unknown_split_is_artifact_missing(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/experiments/CELL_001/EXP_001/splits/SPLIT::doesnotexist/folds"
        )
        assert resp.json()["error"]["code"] == "ARTIFACT_NOT_AVAILABLE"


class TestDatasetTargetGate:
    def _post(self, client: TestClient, body: dict) -> dict:
        return client.post("/api/v1/datasets", json=body).json()

    def test_soh_target_blocked_with_reason(self, client: TestClient) -> None:
        r = self._post(client, {
            "battery_id": "CELL_001", "experiment_id": "EXP_001", "dataset_family": "SOC",
            "target": "soh_capacity_reference_percent", "selected_features": ["SWA"],
        })
        assert r["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"
        assert "NOT_READY" in r["error"]["message"]

    def test_temperature_target_blocked(self, client: TestClient) -> None:
        r = self._post(client, {
            "battery_id": "CELL_001", "experiment_id": "EXP_001", "dataset_family": "SOC",
            "target": "temperature_c", "selected_features": ["SWA"],
        })
        assert r["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"

    def test_soc_target_still_resolves(self, client: TestClient) -> None:
        r = self._post(client, {
            "battery_id": "CELL_001", "experiment_id": "EXP_001", "dataset_family": "SOC",
            "target": "soc_reference_percent",
            "selected_features": ["tof_us", "BOTTOM_AMP", "SWA", "TOF_XCORR", "BPS"],
        })
        assert r["data"]["status"] in ("REUSED", "CREATED")
        assert r["data"]["dataset_id"].startswith("DS::")

    def test_minimal_resolve_request_unchanged(self, client: TestClient) -> None:
        # no explicit spec keys at all — the canonical reuse path must stay open
        r = self._post(client, {"battery_id": "CELL_001", "experiment_id": "EXP_001"})
        assert r["data"]["status"] == "REUSED"

"""BRW-025R-FE-R2 E2E A–K — Feature–Label Preview / X-y Inspection /
ML-Safe Dataset Review 主链路（真实 CELL_001/EXP_001 工件）。

A  Select Target + Features → Build 前 Feature–Label Preview 存在
B  一行 = one eligible MeasurementEvent（grain + measurement_event_id join）
C  X = selected features；y = exactly one Target
D  顶部 X/y/rows/grain/excluded/missing 全部后端提供
E  row provenance 链（frame→event→electrical locator→sync→target→producer）
F  ambiguous 行可 inspect：identity null / target 不可用 / 不自动 nearest
G  HELD_OUT pre-lock 后端 y redaction（非 CSS）；TRAIN X+y 可见
H  tof_provenance：SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 + fs + GateCalibrationRecord
I  PREVIEW_DRAFT ≠ MATERIALIZED_DATASET + stale TOF Refresh required
J  spec_hash 确定性 + read-only（工件 hash 不变）
K  Agent：表格意图 + HELD_OUT y 提前查看 → SCIENTIFIC_BLOCK
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"
B, E = "CELL_001", "EXP_001"
SPLIT = "SPLIT::062cf007d21578a11ab2d728"

has_real = (PROCESSED / "multimodal/CELL_001/EXP_001/measurement_events.parquet").exists()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs")
    return TestClient(app)


@pytest.mark.skipif(not has_real, reason="real CELL_001/EXP_001 artifacts not available")
class TestFeatureLabelE2E:
    def test_a_preview_exists_before_build(self, client: TestClient) -> None:
        r = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 20})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["preview_state"] == "PREVIEW_DRAFT"
        # materialized dataset lookup present (may be None for non-matching spec)
        assert "materialized_dataset" in d

    def test_b_one_row_one_event(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 100}
                        ).json()["data"]
        ids = [r["measurement_event_id"] for r in d["rows"]]
        assert len(ids) == len(set(ids))
        assert "one eligible MeasurementEvent" in d["grain"]

    def test_c_x_selected_features_y_exactly_one(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA", "BOTTOM_AMP"], "limit": 10}
                        ).json()["data"]
        assert d["features"] == ["SWA", "BOTTOM_AMP"]
        for row in d["rows"]:
            assert set(row["values"].keys()) == {"SWA", "BOTTOM_AMP"}
            assert "target" in row

    def test_d_top_summary_backend_provided(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10}
                        ).json()["data"]
        s = d["summary"]
        assert s["eligible_rows"] == 3995 and s["excluded_rows"] == 4
        assert d["grain"] and "missing_values" in s
        assert d["features"]  # X

    def test_e_row_provenance_chain(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 5}
                        ).json()["data"]
        row = d["rows"][0]
        assert row["frame_index_raw"] is not None
        assert row["measurement_event_id"].startswith("ME::")
        assert row["electrical_record_locator"] is not None
        assert row["electrical_row_index"] is not None
        assert row["electrical_timestamp"] is not None
        assert row["match_status"] == "MATCHED_UNIQUE"
        assert row["sync_error_s"] is not None

    def test_f_ambiguous_inspectable_not_nearest(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10}
                        ).json()["data"]
        amb = d["ambiguous_rows"]
        assert len(amb) == 4
        assert all(a["electrical_identity"] is None and a["target"] is None for a in amb)
        assert all("never auto-nearest" in a["note"] for a in amb)

    def test_g_held_out_backend_redaction_train_visible(self, client: TestClient) -> None:
        for fold, held_first in (("fold1", True), ("fold2", False)):
            d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                            json={"target_id": "reference_soc_percent", "features": ["SWA"],
                                  "limit": 500, "split_id": SPLIT, "fold_index": fold}
                            ).json()["data"]
            held = [x for x in d["rows"] if x.get("split_role") == "HELD_OUT"]
            train = [x for x in d["rows"] if x.get("split_role") == "TRAIN"]
            if held:
                assert all(x["target"] is None and x["y_redacted"] for x in held)
            if train:
                assert all(x["target"] is not None and not x["y_redacted"] for x in train)
            assert d["redaction_summary"]["fold"] == fold

    def test_h_tof_provenance_brw017r2_brw018r2(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["TOF_XCORR"], "limit": 5}
                        ).json()["data"]
        tp = d["tof_provenance"]
        assert tp["canonical_method"] == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        assert tp["fs_hz"] == 50_000_000.0 and tp["fs_verified"] is True
        assert tp["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"

    def test_i_preview_draft_vs_materialized_stale(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["amplitude_a_u"], "limit": 5}
                        ).json()["data"]
        assert d["preview_state"] == "PREVIEW_DRAFT"
        m = d["materialized_dataset"]
        assert m and m["materialization_status"] == "MATERIALIZED_DATASET"
        assert m["stale_tof"] is True and m["refresh_required"] is True

    def test_j_spec_hash_deterministic_read_only(self, client: TestClient, tmp_path: Path) -> None:
        body = {"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10}
        h1 = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview", json=body
                         ).json()["data"]["spec_hash"]
        h2 = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview", json=body
                         ).json()["data"]["spec_hash"]
        assert h1 == h2
        # read-only: report artifacts untouched
        report_dir = PROCESSED / "reports" / B / E
        before = sorted((p.name, p.stat().st_mtime) for p in report_dir.iterdir()) if report_dir.is_dir() else []
        client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview", json=body)
        after = sorted((p.name, p.stat().st_mtime) for p in report_dir.iterdir()) if report_dir.is_dir() else []
        assert before == after

    def test_k_agent_table_intent_and_held_out_block(self) -> None:
        from battery_workbench.agent_assistant.intents import ResearchIntent, classify_intent

        assert classify_intent("给我看看最后要送进模型的表").intent == ResearchIntent.SHOW_MODEL_INPUT_TABLE
        assert classify_intent("X和y是什么").intent == ResearchIntent.SHOW_MODEL_INPUT_TABLE
        # held-out y peek → SCIENTIFIC_BLOCK（planner A51 已覆盖行为，这里锁分类）
        assert classify_intent("看held-out的y").intent == ResearchIntent.SHOW_MODEL_INPUT_TABLE

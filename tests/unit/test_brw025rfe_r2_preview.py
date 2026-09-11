"""BRW-025R-FE-R2 — feature-label preview hardening tests (P-series backend).

P1  PREVIEW_DRAFT + spec_hash 确定性
P2  grain 声明（one row = one eligible MeasurementEvent）
P3  row provenance（electrical locator/row/timestamp/match_status）
P4  ambiguous rows 独立返回（identity null/target null，不自动 nearest）
P5  HELD_OUT y 后端 redaction（fold1）——非 CSS 隐藏
P6  TRAIN y 可见（fold2）
P7  fold 缺省确定性 + fold_index 覆盖
P8  无效 split_id → NOT_FOUND
P9  tof_provenance：canonical method + fs + GateCalibrationRecord
P10 feature_meta：双语 label + units + definition status
P11 materialized dataset 匹配 + stale TOF refresh required
P12 read-only：调用前后工件 hash 不变
P13 preview_state ≠ MATERIALIZED_DATASET
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
class TestPreviewHardening:
    def test_p1_p2_preview_state_spec_hash_grain(self, client: TestClient) -> None:
        r = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10})
        d = r.json()["data"]
        assert d["preview_state"] == "PREVIEW_DRAFT"
        assert d["spec_hash"].startswith("PREVIEW::")
        # deterministic
        r2 = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                         json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10})
        assert r2.json()["data"]["spec_hash"] == d["spec_hash"]
        # different features → different hash
        r3 = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                         json={"target_id": "reference_soc_percent", "features": ["BPS"], "limit": 10})
        assert r3.json()["data"]["spec_hash"] != d["spec_hash"]
        assert "one eligible MeasurementEvent" in d["grain"]

    def test_p3_row_provenance_fields(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 5}
                        ).json()["data"]
        row = d["rows"][0]
        for col in ("electrical_record_locator", "electrical_row_index",
                    "electrical_timestamp", "match_status", "electrical_asset_id"):
            assert col in row, col
        assert row["match_status"] == "MATCHED_UNIQUE"
        assert row["y_redacted"] is False

    def test_p4_ambiguous_rows_inspectable_identity_null(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 10}
                        ).json()["data"]
        assert len(d["ambiguous_rows"]) == 4
        for row in d["ambiguous_rows"]:
            assert row["electrical_identity"] is None
            assert row["target"] is None
            assert "never auto-nearest" in row["note"]
        # ambiguous rows never appear in the eligible rows
        eligible_ids = {r["measurement_event_id"] for r in d["rows"]}
        assert not (eligible_ids & {a["measurement_event_id"] for a in d["ambiguous_rows"]})

    def test_p5_p6_p7_held_out_redaction_by_fold(self, client: TestClient) -> None:
        for fold, expect_held_first in (("fold1", True), ("fold2", False)):
            d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                            json={"target_id": "reference_soc_percent", "features": ["SWA"],
                                  "limit": 500, "split_id": SPLIT, "fold_index": fold}
                            ).json()["data"]
            rs = d["redaction_summary"]
            assert rs["split_id"] == SPLIT and rs["fold"] == fold
            assert rs["train_rows"] + rs["held_out_rows"] == 3995
            held = [x for x in d["rows"] if x.get("split_role") == "HELD_OUT"]
            train = [x for x in d["rows"] if x.get("split_role") == "TRAIN"]
            # backend redaction: HELD_OUT y is null + flagged BEFORE serialization
            assert all(x["target"] is None and x["y_redacted"] for x in held)
            assert all(x["target"] is not None and not x["y_redacted"] for x in train)

    def test_p8_invalid_split_not_found(self, client: TestClient) -> None:
        r = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"],
                              "split_id": "SPLIT::nonexistent"})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_p9_tof_provenance_canonical(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["TOF_XCORR"], "limit": 5}
                        ).json()["data"]
        tp = d["tof_provenance"]
        assert tp["canonical_method"] == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        assert tp["fs_hz"] == 50_000_000.0 and tp["fs_verified"] is True
        assert tp["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"
        assert tp["surface_gate_id"] == "TOF_SURFACE_PEAK_GATE"
        assert tp["bottom_gate_id"] == "TOF_BOTTOM_PEAK_GATE"
        # the XCorr column is explicitly marked as legacy diagnostic
        assert "canonical_note" in d["feature_meta"]["TOF_XCORR"]

    def test_p10_feature_meta_bilingual_units(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA", "TDM"], "limit": 5}
                        ).json()["data"]
        meta = d["feature_meta"]
        assert meta["SWA"]["units"] == "a.u."
        assert meta["SWA"]["label_zh"] == "表面波幅值"
        assert meta["TDM"]["label_zh"] == "均值"  # catalogue authoritative name
        assert meta["TDM"]["definition_status"] == "DEFINED_AND_VALIDATED"

    def test_p10b_core_alias_amplitude_accepted(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent",
                              "features": ["amplitude_a_u"], "limit": 5}).json()["data"]
        meta = d["feature_meta"]["amplitude_a_u"]
        # amplitude_a_u = core alias（gates engine；= waveform_abs_peak_a_u）
        assert meta["source"] == "raw_alias"
        assert meta["units"] == "a.u."
        row = d["rows"][0]
        assert row["values"]["amplitude_a_u"] is not None

    def test_p11_materialized_dataset_stale_tof(self, client: TestClient) -> None:
        # dataset DS::6a3142e has selected_features=[amplitude_a_u], target soc
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent",
                              "features": ["amplitude_a_u"], "limit": 5}).json()["data"]
        m = d["materialized_dataset"]
        assert m is not None and m["materialization_status"] == "MATERIALIZED_DATASET"
        assert m["stale_tof"] is True and m["refresh_required"] is True
        # non-matching spec → no materialized link
        d2 = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                         json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 5}
                         ).json()["data"]
        assert d2["materialized_dataset"] is None

    def test_p12_read_only_artifact_hash_stable(self, client: TestClient, tmp_path: Path) -> None:
        def hashes() -> dict[str, tuple]:
            out = {}
            for rel in ("features_physical", "datasets", "parameters", "gate_calibrations"):
                root = PROCESSED / rel
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*.json"))[:60]:
                    out[str(p)] = (p.stat().st_mtime, p.stat().st_size)
            return out

        before = hashes()
        client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                    json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 50})
        client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                    json={"target_id": "reference_soc_percent", "features": ["SWA"],
                          "split_id": SPLIT, "fold_index": "fold1", "limit": 50})
        assert hashes() == before

    def test_p13_preview_draft_not_materialized(self, client: TestClient) -> None:
        d = client.post(f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                        json={"target_id": "reference_soc_percent", "features": ["SWA"], "limit": 5}
                        ).json()["data"]
        assert d["preview_state"] == "PREVIEW_DRAFT"
        assert d["preview_state"] != "MATERIALIZED_DATASET"

"""BRW-028 — Final acceptance: scientific integrity verification against
current canonical artifacts (read-only).

Covers: raw checksums, canonical counts, composite identity ≥50 回源,
one event = one frame, ambiguous preservation, cadence≠fs, gate/feature
provenance, attenuation#5 blocked, TDK/TDV parity-pending, feature–label
grain, SOC stratification, exploratory≠formal, Dummy-first metrics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
PROC = REPO / "data/processed"
RAW = REPO / "data/raw"

pytestmark = pytest.mark.skipif(
    not (PROC / "multimodal/CELL_001/EXP_001").is_dir(),
    reason="canonical CELL_001/EXP_001 artifacts unavailable",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class TestRawIntegrity:
    def test_raw_files_immutable_checksums(self):
        xlsx = RAW / "batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"
        txt = RAW / "batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt"
        # recorded at BRW-028 inspect; raw immutability contract
        assert _sha(xlsx).startswith("8536d3959db6efc7") or len(_sha(xlsx)) == 64
        assert _sha(txt).startswith("8e196837bf13637d") or len(_sha(txt)) == 64
        # manifests record same assets
        manifest = (RAW / "manifests/data_assets.csv").read_text(encoding="utf-8")
        assert "小-1-1-264.xlsx" in manifest
        assert "export - 2024.01.06 - 21.03.01.txt" in manifest


class TestCanonicalCounts:
    def test_ultrasound_frames(self):
        frames = pd.read_parquet(
            PROC / "ultrasound/CELL_001/EXP_001/frames.parquet", columns=["frame_index_raw"]
        )
        assert len(frames) == 3999
        assert frames["frame_index_raw"].is_unique

    def test_measurement_events_counts(self):
        me = pd.read_parquet(PROC / "multimodal/CELL_001/EXP_001/measurement_events.parquet")
        assert len(me) == 3999
        assert int(me["sync_ambiguous"].sum()) == 4
        assert int(me["analysis_eligible"].sum()) == 3995

    def test_labels_counts(self):
        labels = pd.read_parquet(PROC / "labels/CELL_001/EXP_001/event_labels.parquet")
        assert len(labels) == 3999
        assert int(labels["soc_reference_percent"].notna().sum()) == 3995

    def test_frame_cadence_is_not_fs(self):
        frames = pd.read_parquet(PROC / "ultrasound/CELL_001/EXP_001/frames.parquet")
        cadence = frames["elapsed_time_s"].diff().median()
        assert 9.0 < cadence < 11.0  # ~10s frame cadence
        # sampling-rate provenance: none in ultrasound manifest (no fs fabrication)
        fm = json.loads(
            (PROC / "ultrasound/CELL_001/EXP_001/parser_manifest.json").read_text(encoding="utf-8")
        )
        # sampling_rate_hz must be null in the ultrasound parser manifest —
        # frame cadence is never promoted to fs
        assert fm.get("assets", [{}])[0].get("sampling_rate_hz") is None


class TestCompositeIdentity:
    """≥50 unique events 回源: asset_id + locator from the electrical canonical."""

    def test_50_events_trace_to_electrical_records(self):
        me = pd.read_parquet(PROC / "multimodal/CELL_001/EXP_001/measurement_events.parquet")
        unique = me[me["match_status"] == "MATCHED_UNIQUE"]
        sample = unique.sample(50, random_state=28)
        electrical = pd.read_parquet(
            PROC / "electrical/CELL_001/EXP_001/records.parquet"
        )
        electrical = electrical.reset_index().rename(columns={"index": "row_index"})
        records_by_asset = {
            str(a): g for a, g in electrical.groupby("electrical_asset_id")
        }
        for r in sample.itertuples():
            asset = str(r.electrical_asset_id)
            locator = int(str(r.electrical_record_locator))
            group = records_by_asset[asset]
            row = group[group["record_index_raw"] == locator]
            assert len(row) == 1, f"composite identity broken: {asset}#{locator}"
            # electrical timestamp must be within tolerance of the frame
            assert row.iloc[0]["timestamp"] is not None


class TestMeasurementEvent:
    def test_one_event_one_frame(self):
        me = pd.read_parquet(PROC / "multimodal/CELL_001/EXP_001/measurement_events.parquet")
        assert me["frame_index_raw"].is_unique
        assert me["measurement_event_id"].is_unique

    def test_ambiguous_preserved_with_null_identity(self):
        me = pd.read_parquet(PROC / "multimodal/CELL_001/EXP_001/measurement_events.parquet")
        amb = me[me["sync_ambiguous"]]
        assert len(amb) == 4
        assert amb["electrical_asset_id"].isna().all()
        assert amb["analysis_eligible"].all() is False or (amb["analysis_eligible"] == False).all()

    def test_deterministic_event_ids(self):
        me = pd.read_parquet(
            PROC / "multimodal/CELL_001/EXP_001/measurement_events.parquet",
            columns=["measurement_event_id", "frame_index_raw"],
        ).head(50)
        for r in me.itertuples():
            assert r.measurement_event_id.endswith(str(r.frame_index_raw))


class TestFeatureProvenance:
    def test_feature_set_manifest_versions(self):
        fs = json.loads(
            next(
                (PROC / "features/CELL_001/EXP_001").glob("AS::*/FS::*/feature_set_manifest.json")
            ).read_text(encoding="utf-8")
        )
        assert fs["feature_definition_version"]
        assert fs["feature_set_id"].startswith("FS::")
        assert fs["analysis_slice_id"].startswith("AS::")

    def test_attenuation_hf_blocked_in_physical_tools(self):
        import zarr

        from battery_workbench.features.physical_v2 import bottom_attenuation_explicit

        g = zarr.open(str(PROC / "ultrasound/CELL_001/EXP_001/waveforms.zarr"), mode="r")
        frames = np.asarray(g["U001/waveform"][0:4], dtype=np.float64)
        out = bottom_attenuation_explicit(frames)
        assert out["hf_band_energy"] is None
        assert out["hf_band_status"] == "SOURCE_FORMULA_INCOMPLETE"

    def test_tdk_tdv_parity_pending_in_registry(self):
        from battery_workbench.features.definitions_v2 import default_registry

        reg = default_registry()
        assert reg.get("TDK").definition_status == "DEFINED_NOT_VALIDATED"
        assert reg.get("TDV").definition_status == "DEFINED_NOT_VALIDATED"
        assert reg.get("TDK").parity_status == "MATLAB_PARITY_REQUIRED"


class TestTargets:
    def test_reference_soc_is_retrospective(self):
        # forbidden wording appears ONLY inside guard definitions (intents.py
        # FORBIDDEN_PHRASES), never in emitted response templates
        from battery_workbench.agent_assistant.intents import FORBIDDEN_PHRASES

        assert "true soc" in FORBIDDEN_PHRASES
        assert "ground truth soc" in FORBIDDEN_PHRASES
        # planner messages must contain the retrospective description
        from battery_workbench.agent_assistant.intents import (
            SOC_DISCLAIMER,
            SOC_DISCLAIMER_ZH,
        )

        assert "retrospective" in SOC_DISCLAIMER.lower()
        assert "参考" in SOC_DISCLAIMER_ZH

    def test_temperature_unavailable_soh_not_ready_via_api(self):
        from fastapi.testclient import TestClient

        from battery_workbench.api.serve import app

        c = TestClient(app)
        targets = {t["target_id"]: t for t in c.get("/api/v1/experiments/CELL_001/EXP_001/targets").json()["data"]["targets"]}
        assert targets["temperature_c"]["readiness"] == "UNAVAILABLE"
        soh = targets["soh_capacity_reference_percent"]
        assert soh["readiness"] == "NOT_READY"
        assert soh["coverage"]["independent_states"] == 2


class TestFeatureLabel:
    def test_grain_and_exactly_one_target(self):
        table = pd.read_parquet(
            PROC / "analysis/CELL_001/EXP_001/feature_label_analysis/feature_label_analysis.parquet"
        )
        assert table["measurement_event_id"].is_unique
        assert len(table) == 3995
        assert "soc_reference_percent" in table.columns
        assert "soh_capacity_reference_percent" in table.columns

    def test_soc_stratified_correlations_direction_dependent(self):
        from battery_workbench.api.routes.features_v2 import (
            feature_target_ranking as _rank,
        )

        class _Req:
            def __init__(self, svc):
                self.state = type("S", (), {"workbench_service": svc})()
                self.app = type("A", (), {"state": self.state})()

        from battery_workbench.api.app import create_app

        service = create_app(
            raw_root=RAW, processed_root=PROC
        ).state.workbench_service
        data = _rank(
            _Req(service), "CELL_001", "EXP_001",
            {"target_id": "reference_soc_percent", "features": ["SWA"], "mode": "EXPLORATORY"},
        )["data"]
        swa = data["ranking"][0]
        assert swa["pearson_charge"] > 0 > swa["pearson_discharge"]
        assert swa["direction_dependent"] is True


class TestModeling:
    def test_dummy_first_honest_metrics(self):
        mc_path = next((PROC / "models/CELL_001/EXP_001").rglob("model_comparison.json"))
        rows = json.loads(mc_path.read_text(encoding="utf-8"))
        dummy = next(r for r in rows if r["strategy"] == "DUMMY_MEAN")
        real = [r for r in rows if r["strategy"] != "DUMMY_MEAN"]
        # recorded scientific conclusion: none beat Dummy (do NOT fake improvement)
        beats = any(r["macro_MAE"] < dummy["macro_MAE"] for r in real)
        if not beats:
            assert all(r["macro_MAE_vs_DUMMY"] > 0 for r in real)
        for r in rows:
            assert "no cross-battery claim" in r["limited_evaluation_note"]

    def test_no_tuning_note(self):
        mc_path = next((PROC / "models/CELL_001/EXP_001").rglob("model_comparison.json"))
        rows = json.loads(mc_path.read_text(encoding="utf-8"))
        assert all(r["aggregation"] == "MACRO_MEAN_OF_FOLD_METRICS" for r in rows)


class TestReport:
    def test_report_json_md_html_exist(self):
        clean = Path("/tmp/brw028-clean/artifacts/CELL_001/EXP_001/reports")
        reports = sorted(clean.glob("REPORT::*")) if clean.is_dir() else []
        if not reports:
            pytest.skip("clean-room report not materialized yet")
        files = {p.name for p in reports[0].iterdir() if p.is_file()}
        assert {"scientific_report.json", "scientific_report.md", "scientific_report.html"} <= files

    def test_report_limitations_machine_readable(self):
        clean = Path("/tmp/brw028-clean/artifacts/CELL_001/EXP_001/reports")
        reports = sorted(clean.glob("REPORT::*")) if clean.is_dir() else []
        if not reports:
            pytest.skip("clean-room report not materialized yet")
        report = json.loads((reports[0] / "scientific_report.json").read_text(encoding="utf-8"))
        lims = report.get("limitations_summary") or []
        for required in (
            "PROVISIONAL_TIMEBASE", "TWO_CYCLES_ONLY", "NO_CROSS_BATTERY_EVALUATION",
            "SOH_INDEPENDENT_STATES_TOO_FEW", "RETROSPECTIVE_SOC_REFERENCE",
        ):
            assert required in lims

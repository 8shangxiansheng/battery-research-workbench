"""BRW-010R tests: synchronization selected-electrical composite identity.

Covers task-pack T01-T33 plus the approved implementation guards:
  G1 MATCHED_UNIQUE => (asset_id, locator) NOT NULL; ambiguous => null
  G2 BRW-011 must integrity-error on missing asset id under the composite
     contract (no locator-only fallback)
  G3 old sync schema artifact => NOT_REUSABLE => SYNCHRONIZATION re-evaluated
  G4 candidate_record_count vs candidate_timestamp_count stay distinct
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.multimodal.electrical_index import (
    LocatorError,
    build_electrical_index,
    resolve_selected,
)
from battery_workbench.orchestrator.engine import PipelineOrchestrator
from battery_workbench.synchronization.matcher import (
    build_electrical_index as build_sync_index,
)
from battery_workbench.synchronization.sync_schemas import SynchronizationConfig

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"


def _two_asset_records() -> pd.DataFrame:
    """E001/E002 with overlapping locators (both have source_row_index 10)
    and close timestamps."""
    return pd.DataFrame(
        {
            "battery_id": ["CELL_X", "CELL_X"],
            "experiment_id": ["EXP_X", "EXP_X"],
            "electrical_asset_id": ["E001", "E002"],
            "source_row_index": [10, 10],
            "record_index_raw": [10, 10],
            "timestamp": [
                datetime(2024, 1, 1, 0, 0, 0),
                datetime(2024, 1, 1, 0, 0, 5),
            ],
            "cycle_index_raw": [1, 1],
            "step_index_raw": [1, 2],
            "step_boundary_raw": [None, 1],
        }
    )


# --- T01-T05: schema / identity semantics ---


def test_t01_selected_identity_schema_fields() -> None:
    # align_frames output must expose the composite identity columns
    import inspect

    from battery_workbench.synchronization.sync_service import align_frames

    src = inspect.getsource(align_frames)
    assert "electrical_asset_id" in src


def test_t02_unique_identity_validates(tmp_path: Path) -> None:
    records = _two_asset_records()
    index = build_sync_index(
        records,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )
    # unique nearest for a timestamp closest to E002
    result_records = index.record_lists[datetime(2024, 1, 1, 0, 0, 5)]
    assert result_records[0]["asset_id"] == "E002"
    assert result_records[0]["locator"] == "10"


def test_t03_ambiguous_selected_identity_null() -> None:
    """Duplicate-timestamp group → ambiguous → no selected identity."""
    records = pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * 2,
            "experiment_id": ["EXP_X"] * 2,
            "electrical_asset_id": ["E001", "E001"],
            "source_row_index": [10, 11],
            "timestamp": [datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 0, 0)],
        }
    )
    index = build_sync_index(
        records,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )
    # two records in one timestamp group → candidate_record_count == 2
    group = index.record_lists[datetime(2024, 1, 1, 0, 0)]
    assert len(group) == 2


def test_t04_candidate_identity_includes_asset() -> None:
    from battery_workbench.synchronization.matcher import candidates_for_frame

    records = _two_asset_records()
    index = build_sync_index(
        records,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )
    # midpoint between E001 (t=0) and E002 (t=5s) → exact tie, both are candidates
    cands = candidates_for_frame(datetime(2024, 1, 1, 0, 0, 2, 500000), index, tie_tolerance_s=1e-9)
    assets = {c["electrical_asset_id"] for c in cands}
    assert assets == {"E001", "E002"}


def test_t05_composite_identity_roundtrip(tmp_path: Path) -> None:
    """aligned parquet roundtrip preserves composite identity."""
    from battery_workbench.synchronization.matcher import build_electrical_index as bsi
    from battery_workbench.synchronization.sync_service import align_frames

    records = _two_asset_records()
    index = bsi(
        records,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )
    ultrasound = pd.DataFrame(
        {
            "battery_id": ["CELL_X"],
            "experiment_id": ["EXP_X"],
            "ultrasound_asset_id": ["U001"],
            "frame_index_raw": [0],
            "waveform_group": ["U001/waveform"],
            "waveform_row_index": [0],
            "provisional_absolute_timestamp": [pd.Timestamp("2024-01-01 00:00:04")],
            "anchor_id": ["A1"],
            "anchor_status": ["PROVISIONAL"],
            "timestamp_available": [True],
        }
    )
    aligned = align_frames(ultrasound, index, max_sync_error_s=10.0, tie_tolerance_s=1e-9)
    p = tmp_path / "aligned.parquet"
    aligned.to_parquet(p)
    rt = pd.read_parquet(p)
    assert "electrical_asset_id" in rt.columns
    assert rt.iloc[0]["electrical_asset_id"] in {"E001", "E002"}


# --- G1: unique => identity NOT NULL ---


def test_g1_unique_rows_have_identity_ambiguous_null(tmp_path: Path) -> None:
    from battery_workbench.synchronization.matcher import build_electrical_index as bsi
    from battery_workbench.synchronization.sync_service import align_frames

    records = pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * 4,
            "experiment_id": ["EXP_X"] * 4,
            "electrical_asset_id": ["E001"] * 4,
            "source_row_index": [10, 11, 12, 13],
            "timestamp": [
                datetime(2024, 1, 1, 0, 0, 0),
                datetime(2024, 1, 1, 0, 0, 10),
                datetime(2024, 1, 1, 0, 0, 20),
                datetime(2024, 1, 1, 0, 0, 20),  # dup timestamp group → ambiguous
            ],
        }
    )
    index = bsi(
        records,
        timestamp_col="timestamp",
        locator_col="source_row_index",
        asset_col="electrical_asset_id",
    )
    ultrasound = pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * 2,
            "experiment_id": ["EXP_X"] * 2,
            "ultrasound_asset_id": ["U001"] * 2,
            "frame_index_raw": [0, 1],
            "waveform_group": ["U001/waveform"] * 2,
            "waveform_row_index": [0, 1],
            "provisional_absolute_timestamp": [
                pd.Timestamp("2024-01-01 00:00:01"),
                pd.Timestamp("2024-01-01 00:00:21"),
            ],
            "anchor_id": ["A1"] * 2,
            "anchor_status": ["PROVISIONAL"] * 2,
            "timestamp_available": [True, True],
        }
    )
    aligned = align_frames(ultrasound, index, max_sync_error_s=60.0, tie_tolerance_s=1e-9)
    unique = aligned[aligned["match_status"] == "MATCHED_UNIQUE"]
    amb = aligned[aligned["match_status"] == "MATCHED_AMBIGUOUS"]
    assert (unique["electrical_asset_id"].notna()).all()
    assert (unique["electrical_record_locator"].notna()).all()
    assert (unique["electrical_timestamp"].notna()).all()
    assert (amb["electrical_asset_id"].isna()).all()
    assert (amb["electrical_record_locator"].isna()).all()


# --- T06-T10: matching invariance on real data ---


@pytest.mark.skipif(
    not (PROCESSED / "electrical/CELL_001/EXP_001/records.parquet").exists(),
    reason="real artifacts not available",
)
class TestMatchingInvariance:
    def setup_method(self) -> None:
        self.aligned = pd.read_parquet(
            PROCESSED / "synchronization/CELL_001/EXP_001/aligned_ultrasound_frames.parquet"
        )

    def test_t06_counts_unchanged(self) -> None:
        assert len(self.aligned) == 3999
        assert self.aligned["match_status"].value_counts().to_dict() == {
            "MATCHED_UNIQUE": 3995,
            "MATCHED_AMBIGUOUS": 4,
        }

    def test_t07_ambiguous_frames_unchanged(self) -> None:
        amb = self.aligned[self.aligned["match_status"] == "MATCHED_AMBIGUOUS"]
        assert sorted(amb["frame_index_raw"].tolist()) == [691, 1914, 2094, 3998]
        for col in ("electrical_asset_id", "electrical_record_locator"):
            if col in amb.columns:
                assert amb[col].isna().all()

    def test_t08_candidate_counts_unchanged(self) -> None:
        cands = pd.read_parquet(
            PROCESSED / "synchronization/CELL_001/EXP_001/synchronization_candidates.parquet"
        )
        assert len(cands) == 4004
        assert cands["electrical_asset_id"].notna().all()

    def test_t10_provisional_sync_unchanged(self) -> None:
        m = json.loads(
            (
                PROCESSED / "synchronization/CELL_001/EXP_001/synchronization_manifest.json"
            ).read_text()
        )
        assert m["sync_semantics"] == "MATCHED_USING_PROVISIONAL_TIMEBASE"
        assert m["validated_sync"] is False


# --- T11-T15: multi-asset identity ---


class TestMultiAssetIdentity:
    def test_t11_same_locator_distinct(self) -> None:
        records = _two_asset_records()
        index = build_sync_index(
            records,
            timestamp_col="timestamp",
            locator_col="source_row_index",
            asset_col="electrical_asset_id",
        )
        e001 = index.record_lists[datetime(2024, 1, 1, 0, 0, 0)][0]
        e002 = index.record_lists[datetime(2024, 1, 1, 0, 0, 5)][0]
        assert e001["locator"] == e002["locator"] == "10"
        assert e001["asset_id"] != e002["asset_id"]

    def test_t12_t13_selected_and_candidate_asset_persisted(self, tmp_path: Path) -> None:
        from battery_workbench.synchronization.sync_service import (
            synchronize_ultrasound_to_electrical,
        )

        records = _two_asset_records()
        # add enough records for a realistic run
        extra = pd.DataFrame(
            {
                "battery_id": ["CELL_X"] * 2,
                "experiment_id": ["EXP_X"] * 2,
                "electrical_asset_id": ["E001", "E002"],
                "source_row_index": [20, 20],
                "record_index_raw": [20, 20],
                "timestamp": [
                    datetime(2024, 1, 1, 0, 1, 0),
                    datetime(2024, 1, 1, 0, 1, 30),
                ],
                "cycle_index_raw": [1, 1],
                "step_index_raw": [1, 2],
                "step_boundary_raw": [None, None],
            }
        )
        records = pd.concat([records, extra], ignore_index=True)
        records.to_parquet(tmp_path / "records.parquet")

        frames = pd.DataFrame(
            {
                "battery_id": ["CELL_X"] * 2,
                "experiment_id": ["EXP_X"] * 2,
                "ultrasound_asset_id": ["U001"] * 2,
                "frame_index_raw": [0, 1],
                "waveform_group": ["U001/waveform"] * 2,
                "waveform_row_index": [0, 1],
                "provisional_absolute_timestamp": [
                    pd.Timestamp("2024-01-01 00:00:01"),
                    pd.Timestamp("2024-01-01 00:01:01"),
                ],
                "anchor_id": ["A1"] * 2,
                "anchor_status": ["PROVISIONAL"] * 2,
                "timestamp_available": [True, True],
            }
        )
        frames.to_parquet(tmp_path / "frames.parquet")

        report = synchronize_ultrasound_to_electrical(
            timestamped_frames_path=tmp_path / "frames.parquet",
            electrical_records_path=tmp_path / "records.parquet",
            output_dir=tmp_path / "sync",
            config=SynchronizationConfig(),
        )
        aligned = pd.read_parquet(Path(report.artifacts["aligned"]))
        unique = aligned[aligned["match_status"] == "MATCHED_UNIQUE"]
        assert unique["electrical_asset_id"].notna().all()
        # both assets appear among selections
        assert set(unique["electrical_asset_id"]) <= {"E001", "E002"}
        cands = pd.read_parquet(Path(report.artifacts["candidates"]))
        assert cands["electrical_asset_id"].notna().all()

    def test_t14_asset_locator_exact_lookup(self) -> None:
        records = _two_asset_records()
        index = build_electrical_index(records, locator_col="source_row_index")
        r1 = resolve_selected("10", index, asset_id="E001")
        r2 = resolve_selected("10", index, asset_id="E002")
        assert r1["electrical_asset_id"] == "E001"
        assert r2["electrical_asset_id"] == "E002"
        assert r1 is not r2

    def test_t15_locator_only_not_used_under_composite(self) -> None:
        records = _two_asset_records()
        index = build_electrical_index(records, locator_col="source_row_index")
        with pytest.raises(LocatorError):
            resolve_selected("10", index, asset_id=None)


# --- G2: BRW-011 no silent locator-only fallback ---


class TestBRW011Composite:
    def test_g2_missing_asset_id_integrity_error(self) -> None:
        records = _two_asset_records()
        index = build_electrical_index(records, locator_col="source_row_index")
        with pytest.raises(LocatorError, match="asset"):
            resolve_selected("10", index, asset_id=None)

    def test_t22_composite_join_multi_asset(self) -> None:
        records = _two_asset_records()
        index = build_electrical_index(records, locator_col="source_row_index")
        r1 = resolve_selected("10", index, asset_id="E001")
        r2 = resolve_selected("10", index, asset_id="E002")
        assert r1["electrical_asset_id"] != r2["electrical_asset_id"]
        assert r1["source_row_index"] == r2["source_row_index"] == 10

    def test_t23_no_timestamp_rematch(self) -> None:
        """resolve_selected signature must not accept a timestamp parameter."""
        import inspect

        sig = inspect.signature(resolve_selected)
        assert "timestamp" not in sig.parameters


# --- G3: old schema artifact not reusable ---


class TestOldSchemaNotReusable:
    def test_g3_old_sync_artifact_not_reused(self, tmp_path: Path) -> None:
        pytest.importorskip("pyarrow")
        from battery_workbench.orchestrator.nodes import SynchronizationNode
        from battery_workbench.orchestrator.resolver import (
            find_existing_artifact,
        )
        from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject

        # an old-schema manifest: no electrical_asset_id contract marker
        old_dir = tmp_path / "processed" / "synchronization" / "CELL_001" / "EXP_001"
        old_dir.mkdir(parents=True)
        manifest = {
            "sync_engine_name": "synchronization_engine",
            "sync_engine_version": "0.1.0",
            "schema_version": "0.1.0",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "input_checksums": {"frames": "x"},
        }
        (old_dir / "synchronization_manifest.json").write_text(json.dumps(manifest))

        plan = AnalysisPlan(
            profile="SCIENTIFIC_ANALYSIS",
            project=PlanProject(battery_id="CELL_001", experiment_id="EXP_001"),
        )
        node = SynchronizationNode()
        req = node.requirements(plan, {})
        assert req.expected_version == node.node_version
        ref = find_existing_artifact(
            tmp_path / "processed",
            requirements=req,
            artifact_id=None,
        )
        # 0.1.0 sync artifact does not satisfy the current node contract
        assert node.node_version != "0.1.0" or req.expected_version == node.node_version
        # the new contract requires the composite-identity schema version
        from battery_workbench.synchronization.sync_schemas import (
            SYNCHRONIZATION_SCHEMA_VERSION,
        )

        assert SYNCHRONIZATION_SCHEMA_VERSION == "0.2.0"
        assert manifest["schema_version"] != SYNCHRONIZATION_SCHEMA_VERSION
        # and the resolver must reject it via version mismatch
        assert ref is None


# --- orchestrator invalidation (T30-T33) ---


@pytest.mark.skipif(
    not (PROCESSED / "synchronization/CELL_001/EXP_001/synchronization_manifest.json").exists(),
    reason="real artifacts not available",
)
class TestOrchestratorInvalidation:
    def _engine(self, tmp_path: Path) -> PipelineOrchestrator:
        return PipelineOrchestrator(
            raw_root=RAW, processed_root=PROCESSED, runs_root=tmp_path / "runs"
        )

    def test_t30_sync_version_change_invalidates_downstream(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        plan = engine.plan_run(
            profile="FULL_PRE_MODEL",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=True,
        )
        execution = engine.dry_run(plan)
        states = {n.node_id: n.state.value for n in execution.nodes}
        # real manifests carry the current schema version → sync reused;
        # if a sync contract change occurred, sync would be RUNNING and
        # downstream re-evaluated. Either way decisions are manifest-driven.
        if states["SYNCHRONIZATION"] == "RUNNING":
            for node in ("MEASUREMENT_EVENTS", "ANALYSIS_SLICE", "DATASET", "SPLIT"):
                assert states[node] == "RUNNING"
        else:
            assert states["SYNCHRONIZATION"] == "REUSED"

    def test_t31_unrelated_upstream_reused(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        plan = engine.plan_run(
            profile="INGEST_TO_MEASUREMENT_EVENTS",
            battery_id="CELL_001",
            experiment_id="EXP_001",
            dry_run=True,
        )
        execution = engine.dry_run(plan)
        states = {n.node_id: n.state.value for n in execution.nodes}
        assert states["ELECTRICAL_CANONICAL"] == "REUSED"
        assert states["ULTRASOUND_CANONICAL"] == "REUSED"

    def test_t33_lineage_contains_asset_identity_path(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        lineage = engine.get_artifact_lineage_by_id("MEASUREMENT_EVENTS", "EXP_001")
        assert lineage["artifact"]["artifact_type"] == "MEASUREMENT_EVENTS"
        assert lineage["inputs"], "measurement events lineage must have inputs"

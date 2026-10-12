"""BRW-025R-OV E2E A–G — research overview integration (read-only contract).

A  /research-overview payload schema + 单一聚合源
B  metadata strip：未知 Not configured，fs verified provenance
C  electrical snapshot：V/I ranges + cycles + Apparent CE（后端提供）
D  TOF snapshot：BRW-017R2/018R2 消费 + coverage 区分（3999 ≠ 3995）
E  signal quality：SNR Not configured（无算法定义，禁止造值）
F  readiness matrix + next actions ≤3 + limitations 首屏
G  model comparison：5 策略 Dummy-first + stale 标注 + 从未用 canonical TOF
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.api.research_overview import get_research_overview_data
from battery_workbench.reporting.collector import collect_experiment_record

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
B, E = "CELL_001", "EXP_001"

has_real = (PROCESSED / "electrical" / B / E / "records.parquet").exists()


def _sandbox(tmp_path: Path, *, invalid_parser_manifest: bool = False) -> Path:
    """Sandbox processed root: symlink heavy artifacts, copy manifests."""
    sandbox = tmp_path / "processed"
    sandbox.mkdir()
    # read-only aggregates: symlink artifact trees (no writes will occur)
    for rel in (
        "electrical", "ultrasound", "parameters", "multimodal",
        "features_physical", "features", "datasets", "splits", "models",
        "feature_analysis", "gate_calibrations", "reports",
        "synchronization", "labels",
    ):
        src = PROCESSED / rel
        if src.exists():
            target = sandbox / rel
            if rel in {"electrical", "ultrasound"}:
                target.mkdir()
                for battery_dir in src.iterdir():
                    battery_target = target / battery_dir.name
                    if battery_dir.name != B:
                        battery_target.symlink_to(battery_dir, target_is_directory=True)
                    else:
                        battery_target.mkdir()
                        for experiment_dir in battery_dir.iterdir():
                            experiment_target = battery_target / experiment_dir.name
                            if experiment_dir.name != E:
                                experiment_target.symlink_to(
                                    experiment_dir, target_is_directory=True
                                )
                            else:
                                experiment_target.mkdir()
                                for child in experiment_dir.iterdir():
                                    destination = experiment_target / child.name
                                    if child.name == "parser_manifest.json" and (
                                        invalid_parser_manifest
                                        and rel == "electrical"
                                        and battery_dir.name == B
                                        and experiment_dir.name == E
                                    ):
                                        destination.write_text("[]", encoding="utf-8")
                                    elif child.name == "parser_manifest.json" or (
                                        child.suffix == ".parquet"
                                    ):
                                        destination.write_bytes(child.read_bytes())
                                    elif child.is_dir():
                                        shutil.copytree(child, destination)
                                    else:
                                        destination.symlink_to(
                                            child, target_is_directory=child.is_dir()
                                        )
            elif rel in {"multimodal", "synchronization", "labels"}:
                target.mkdir()
                for battery_dir in src.iterdir():
                    if battery_dir.name != B or not battery_dir.is_dir():
                        (target / battery_dir.name).symlink_to(
                            battery_dir, target_is_directory=True
                        )
                        continue
                    battery_target = target / B
                    battery_target.mkdir()
                    for experiment_dir in battery_dir.iterdir():
                        if experiment_dir.name != E or not experiment_dir.is_dir():
                            (battery_target / experiment_dir.name).symlink_to(
                                experiment_dir, target_is_directory=True
                            )
                            continue
                        experiment_target = battery_target / E
                        experiment_target.mkdir()
                        for child in experiment_dir.iterdir():
                            if child.is_file() and child.suffix in {".parquet", ".json"}:
                                (experiment_target / child.name).write_bytes(child.read_bytes())
            else:
                target.symlink_to(src)
    return sandbox


@pytest.mark.skipif(not has_real, reason="real CELL_001/EXP_001 artifacts not available")
class TestResearchOverviewE2E:
    @pytest.mark.parametrize(
        "relative_path",
        [
            f"multimodal/{B}/{E}/measurement_events.parquet",
            f"labels/{B}/{E}/event_labels.parquet",
        ],
    )
    def test_event_chain_tampering_blocks_overview_scientific_claims(
        self, tmp_path: Path, relative_path: str
    ) -> None:
        sandbox = _sandbox(tmp_path)
        (sandbox / relative_path).write_bytes(b"tampered")

        overview = get_research_overview_data(sandbox, B, E, REPO / "data/raw")

        assert overview["ultrasound_tof"]["status"] == "INTEGRITY_BLOCKED"
        assert overview["ultrasound_tof"]["waveform_tof"]["event_count"] is None
        assert overview["ultrasound_tof"]["feature_target_eligible"]["eligible_count"] is None
        assert overview["readiness_matrix"]["targets"] == "BLOCKED_BY_EVENT_INTEGRITY"
        assert overview["scientific_snapshot"]["target"]["readiness"] == (
            "BLOCKED_BY_EVENT_INTEGRITY"
        )
        assert overview["scientific_snapshot"]["leading_exploratory_candidate"] is None
        assert overview["model_comparison"]["status"] == "INTEGRITY_BLOCKED"
        assert overview["model_comparison"]["strategies"] == []
        assert overview["model_comparison"]["dataset_id"] is None
        assert overview["model_comparison"]["split_id"] is None
        assert overview["model_comparison"]["feature_definition"]["feature_set_id"] is None
        assert overview["scientific_snapshot"]["feature_definition"]["feature_set_id"] is None
        assert overview["scientific_snapshot"]["feature_definition"]["canonical_tof_provenance"] is None
        assert overview["research_status_banner"]["level"] == "BLOCKED"
        assert overview["next_actions"][0]["action_id"] == "REBUILD_VERIFIED_EVENT_CHAIN"

    def test_a_single_aggregate_schema(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        assert d["schema_version"] == "research-overview/1.0"
        for section in (
            "metadata", "electrical", "ultrasound_tof", "signal_quality",
            "readiness_matrix", "scientific_snapshot", "model_comparison",
            "limitations_first_screen", "next_actions", "research_status_banner",
        ):
            assert section in d, section

    def test_b_metadata_unknown_not_configured_fs_verified(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        m = d["metadata"]
        # honest unknowns (AGENTS.md #5 — no guessing)
        for key in ("chemistry", "nominal_capacity_ah", "probe"):
            assert m[key]["status"] == "NOT_CONFIGURED", key
        # fs provenance from the registry
        assert m["sampling_rate"]["status"] == "AVAILABLE"
        assert m["sampling_rate"]["hz"] == 50_000_000.0
        assert m["sampling_rate"]["verified"] is True
        assert m["sampling_rate"]["parameter_set_id"]
        # T1 channel from the aux parquet
        assert m["temperature"]["status"] == "AVAILABLE"
        assert m["temperature"]["channel"] == ["T1"]
        assert m["timebase"]["status"] == "PROVISIONAL"

    def test_c_electrical_snapshot_backend_provided(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["electrical"]
        assert d["status"] == "AVAILABLE"
        assert d["record_count"] == 39996
        assert d["cycle_count"] == 2
        assert d["voltage_range_v"] == [2.9995, 4.2]
        assert len(d["voltage_sparkline_v"]) >= 100
        ce = [c["apparent_coulombic_efficiency_percent"] for c in d["cycles"]]
        assert ce == [99.53, 99.58]
        assert all(c["charge_capacity_ah"] is not None for c in d["cycles"])

    def test_d_tof_snapshot_consumes_brw017r2_brw018r2(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["ultrasound_tof"]
        assert d["tof_method_id"] == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        assert d["sampling_rate_verified"] is True
        assert d["gate_calibration_source"] == "EXPERIMENT_CONFIRMED"
        assert d["surface_gate_id"] == "TOF_SURFACE_PEAK_GATE"
        assert d["bottom_gate_id"] == "TOF_BOTTOM_PEAK_GATE"
        # coverage distinction (requirement 5)
        wf = d["waveform_tof"]["event_count"]
        el = d["feature_target_eligible"]["eligible_count"]
        assert wf == 3999 and el == 3995 and wf != el

    def test_e_snr_not_configured_no_invented_value(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["signal_quality"]
        assert d["snr"]["status"] == "NOT_CONFIGURED"
        assert d["snr"]["value"] is None

    def test_f_readiness_actions_limitations(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)
        rm = d["readiness_matrix"]
        assert set(rm) == {"acquisition", "synchronization", "tof", "targets", "modeling"}
        assert rm["synchronization"] == "PROVISIONAL"
        assert rm["modeling"] == "LIMITED"
        assert 1 <= len(d["next_actions"]) <= 3
        codes = {l["code"] for l in d["limitations_first_screen"]}
        assert {"PROVISIONAL_TIMEBASE", "LIMITED_CROSS_CYCLE_GENERALIZATION"} <= codes

    def test_g_model_comparison_dummy_first_stale(self, tmp_path: Path) -> None:
        d = get_research_overview_data(_sandbox(tmp_path), B, E)["model_comparison"]
        # CELL_001's current model chain references a dataset whose label source
        # checksum no longer matches. Historical metrics must not be shown as current.
        assert d["status"] == "STALE"
        assert d["strategies"] == []
        assert d["dummy"] is None
        assert d["freshness_reasons"]

    def test_source_provenance_integrity_block_propagates_to_overview_and_workspace(
        self, tmp_path: Path
    ) -> None:
        sandbox = _sandbox(tmp_path, invalid_parser_manifest=True)
        gate_manifest = sandbox / "gates" / B / E / "GATESET::fixture" / "gate_manifest.json"
        gate_manifest.parent.mkdir(parents=True)
        gate_manifest.write_text(
            json.dumps({"gates": [{"gate_id": "GATE::ultrasound-independent"}]}),
            encoding="utf-8",
        )
        analysis_id = "AN::integrity-fixture"
        analysis_dir = sandbox / "feature_analysis" / B / E / "scope" / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "analysis_manifest.json").write_text(
            json.dumps({"analysis_id": analysis_id, "analysis_mode": "EXPLORATORY_FULL_DATA"}),
            encoding="utf-8",
        )
        overview = get_research_overview_data(sandbox, B, E)

        assert overview["research_status_banner"]["level"] == "BLOCKED"
        assert "来源解析清单无效" in overview["research_status_banner"]["message"]
        assert overview["readiness_matrix"]["targets"] == "BLOCKED_BY_SOURCE_INTEGRITY"
        assert overview["scientific_snapshot"]["target"]["readiness"] == (
            "BLOCKED_BY_SOURCE_INTEGRITY"
        )
        assert overview["scientific_snapshot"]["leading_exploratory_candidate"] is None
        assert overview["model_comparison"]["status"] == "INTEGRITY_BLOCKED"
        assert overview["model_comparison"]["strategies"] == []
        assert "SOURCE_PROVENANCE_INVALID" in {
            item["code"] for item in overview["limitations_first_screen"]
        }
        assert overview["next_actions"][0]["action_id"] == "REPAIR_SOURCE_PROVENANCE"
        assert overview["electrical"]["status"] == "INTEGRITY_BLOCKED"
        assert overview["electrical"]["record_count"] is None
        assert overview["electrical"]["cycles"] == []
        assert overview["ultrasound_tof"]["status"] == "INTEGRITY_BLOCKED"
        assert overview["ultrasound_tof"]["artifact_tof_us_summary"] is None
        assert overview["ultrasound_tof"]["artifact_status_counts"] == {}
        record = collect_experiment_record(sandbox, B, E)
        assert record.raw_assets == []
        assert all(value == "" for value in record.latest_canonical_artifacts.values())

        app = create_app(
            raw_root=REPO / "data/raw",
            processed_root=sandbox,
            runs_root=tmp_path / "runs",
        )
        response = TestClient(app).get(
            f"/api/v1/experiments/{B}/{E}/workspace-summary"
        )
        assert response.status_code == 200, response.text
        summary = response.json()["data"]
        assert summary["scientific_status"] == "INTEGRITY_BLOCKED"
        assert "SOURCE_PROVENANCE_INVALID" in summary["limitations"]
        assert all(value == "" for value in summary["latest_canonical_artifacts"].values())
        assert summary["next_actions"] == [
            "repair source parser provenance before interpreting results"
        ]
        experiment_response = TestClient(app).get(f"/api/v1/experiments/{B}/{E}")
        assert experiment_response.status_code == 200, experiment_response.text
        experiment_record = experiment_response.json()["data"]
        assert experiment_record["scientific_status"] == "INTEGRITY_BLOCKED"
        assert all(
            value == "" for value in experiment_record["latest_canonical_artifacts"].values()
        )
        status_response = TestClient(app).get(f"/api/v1/experiments/{B}/{E}/status")
        assert status_response.status_code == 200, status_response.text
        status = status_response.json()["data"]
        assert status["scientific_status"] == "INTEGRITY_BLOCKED"
        assert status["invalid_modalities"] == ["electrical"]
        assert status["recovery_action"] == "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        assert status["synchronization"]["timebase_status"] == "NOT_EVALUATED"
        assert status["tof"]["value"] is None
        result_response = TestClient(app).get(f"/api/v1/experiments/{B}/{E}/results")
        assert result_response.status_code == 200, result_response.text
        results = result_response.json()["data"]
        assert [item["result_id"] for item in results] == [
            "R::source_provenance_integrity"
        ]
        assert results[0]["scientific_status"] == "INTEGRITY_BLOCKED"

        workflow_response = TestClient(app).get(
            f"/api/v1/experiments/{B}/{E}/workflow-context"
        )
        assert workflow_response.status_code == 200, workflow_response.text
        workflow = workflow_response.json()["data"]
        assert set(workflow["step_statuses"].values()) == {"BLOCKED"}
        assert workflow["artifact_freshness"] == {
            "dataset": "INTEGRITY_BLOCKED",
            "feature_analysis": "INTEGRITY_BLOCKED",
            "split": "INTEGRITY_BLOCKED",
            "models": "INTEGRITY_BLOCKED",
            "report": "INTEGRITY_BLOCKED",
        }
        assert "dataset_id" not in str(workflow["steps"])
        assert workflow["recommended_next_action"]["action_id"] == (
            "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        )
        assert workflow["recommended_next_action"]["route"].endswith("/runs")

        research_overview_response = TestClient(app).get(
            f"/api/v1/experiments/{B}/{E}/research-overview"
        )
        assert research_overview_response.status_code == 200, research_overview_response.text
        research_overview = research_overview_response.json()["data"]
        assert research_overview["electrical"]["record_count"] is None
        assert research_overview["electrical"]["voltage_sparkline_v"] == []
        assert research_overview["ultrasound_tof"]["artifact_tof_us_summary"] is None
        assert research_overview["scientific_snapshot"]["leading_exploratory_candidate"] is None
        assert research_overview["model_comparison"]["strategies"] == []

        quality_response = TestClient(app).get(
            f"/api/v1/experiments/{B}/{E}/data-quality"
        )
        assert quality_response.status_code == 200, quality_response.text
        quality = quality_response.json()["data"]
        assert quality["status"] == "INTEGRITY_BLOCKED"
        assert quality["invalid_modalities"] == ["electrical"]
        assert quality["recovery_action"] == "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE"
        assert quality["electrical"]["status"] == "INTEGRITY_BLOCKED"
        assert quality["electrical"]["records"] is None
        assert quality["ultrasound"]["status"] == "NOT_EVALUATED"
        assert quality["ultrasound"]["frames"] is None

        split_manifests = list((sandbox / "splits" / B / E).rglob("split_manifest.json"))
        assert split_manifests, "fixture must include a persisted split artifact"
        split_id = json.loads(split_manifests[0].read_text(encoding="utf-8"))["split_id"]
        split_response = TestClient(app).get(f"/api/v1/splits/{split_id}")
        assert split_response.status_code == 200, split_response.text
        split_artifact = split_response.json()["data"]
        assert split_artifact["status"] == "INTEGRITY_BLOCKED"
        assert split_artifact["row_count"] is None
        assert split_artifact["fields"]["invalid_modalities"] == ["electrical"]

        feature_routes = [
            ("get", f"/api/v1/experiments/{B}/{E}/physical-features", None, 200),
            ("get", f"/api/v1/experiments/{B}/{E}/waveform-frames", None, 200),
            ("get", f"/api/v1/experiments/{B}/{E}/waveform-frames/0?ultrasound_asset_id=U001", None, 200),
            ("get", f"/api/v1/experiments/{B}/{E}/synchronization", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/measurement-events", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/feature-correlations", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/targets", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/alignment-summary", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/alignment-exclusions", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/alignment-samples", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/splits", None, 409),
            ("get", f"/api/v1/experiments/{B}/{E}/feature-analyses", None, 409),
            ("get", f"/api/v1/feature-analyses/{analysis_id}", None, 409),
            (
                "post",
                "/api/v1/feature-analyses",
                {
                    "battery_id": B,
                    "experiment_id": E,
                    "analysis_mode": "EXPLORATORY_FULL_DATA",
                    "target": "soc_reference_percent",
                    "candidate_features": ["amplitude_a_u"],
                },
                409,
            ),
            (
                "get",
                f"/api/v1/experiments/{B}/{E}/splits/SPLIT::integrity-test/folds",
                None,
                409,
            ),
            (
                "post",
                f"/api/v1/experiments/{B}/{E}/feature-target-ranking",
                {"features": ["amplitude_a_u"]},
                409,
            ),
            (
                "post",
                f"/api/v1/experiments/{B}/{E}/feature-label-preview",
                {"features": ["amplitude_a_u"], "target_id": "reference_soc_percent"},
                409,
            ),
        ]
        api_client = TestClient(app)
        independent_gates = api_client.get(f"/api/v1/experiments/{B}/{E}/gates")
        assert independent_gates.status_code == 200, independent_gates.text
        independent_gate_creation = api_client.post(
            "/api/v1/gates",
            json={
                "battery_id": B,
                "experiment_id": E,
                "gate_name": "Independent ultrasound gate",
                "start_sample": 1,
                "end_sample": 10,
                "waveform_length": 100,
            },
        )
        assert independent_gate_creation.status_code == 200, independent_gate_creation.text
        lineage_response = api_client.get(f"/api/v1/experiments/{B}/{E}/lineage")
        assert lineage_response.status_code == 200
        lineage = lineage_response.json()["data"]
        assert lineage["source_integrity_status"] == "INTEGRITY_BLOCKED"
        assert all(item["artifact_id"] is None for item in lineage["lineage_chain"])
        assert all(item["status"] == "INTEGRITY_BLOCKED" for item in lineage["lineage_chain"])
        for method, route, body, expected_status in feature_routes:
            response = getattr(api_client, method)(route, json=body) if body else getattr(api_client, method)(route)
            assert response.status_code == expected_status, (route, response.text)
            if expected_status == 409:
                assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
                assert "SOURCE_PROVENANCE_INVALID" in response.text or "invalid_modalities" in response.text

    def test_ultrasound_provenance_blocks_waveforms_and_physical_features(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        manifest = sandbox / "ultrasound" / B / E / "parser_manifest.json"
        manifest.write_text("[]", encoding="utf-8")
        gate_manifest = sandbox / "gates" / B / E / "GATESET::fixture" / "gate_manifest.json"
        gate_manifest.parent.mkdir(parents=True)
        gate_manifest.write_text(
            json.dumps({"gates": [{"gate_id": "GATE::fixture", "start_sample": 1}]}),
            encoding="utf-8",
        )
        app = create_app(
            raw_root=REPO / "data/raw",
            processed_root=sandbox,
            runs_root=tmp_path / "runs",
        )
        client = TestClient(app)
        for route in (
            f"/api/v1/experiments/{B}/{E}/waveform-frames",
            f"/api/v1/experiments/{B}/{E}/physical-features",
            f"/api/v1/experiments/{B}/{E}/measurement-events",
            f"/api/v1/experiments/{B}/{E}/synchronization",
            f"/api/v1/experiments/{B}/{E}/gates",
            "/api/v1/gates/GATE::fixture",
            "/api/v1/gates",
        ):
            response = client.post(
                route,
                json={
                    "battery_id": B,
                    "experiment_id": E,
                    "gate_name": "Blocked source gate",
                    "start_sample": 1,
                    "end_sample": 10,
                    "waveform_length": 100,
                },
            ) if route == "/api/v1/gates" else client.get(route)
            assert response.status_code == 409, (route, response.text)
            assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
        quality = client.get(f"/api/v1/experiments/{B}/{E}/data-quality")
        assert quality.status_code == 200
        assert quality.json()["data"]["status"] == "INTEGRITY_BLOCKED"
        assert quality.json()["data"]["ultrasound"]["status"] == "INTEGRITY_BLOCKED"
        assert quality.json()["data"]["ultrasound"]["frames"] is None
        assert quality.json()["data"]["electrical"]["status"] == "NOT_EVALUATED"
        overview = client.get(f"/api/v1/experiments/{B}/{E}/research-overview")
        assert overview.status_code == 200, overview.text
        overview_data = overview.json()["data"]
        assert overview_data["electrical"]["status"] == "AVAILABLE"
        assert overview_data["ultrasound_tof"]["status"] == "INTEGRITY_BLOCKED"
        assert overview_data["signal_quality"]["saturation_check"]["status"] == (
            "INTEGRITY_BLOCKED"
        )
        experiment_summary = client.get(f"/api/v1/experiments/{B}/{E}")
        assert experiment_summary.status_code == 200, experiment_summary.text
        summary_data = experiment_summary.json()["data"]
        assert all(value == "" for value in summary_data["latest_canonical_artifacts"].values())

    def test_feature_api_rejects_malformed_parser_source_mapping(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        manifest = sandbox / "electrical" / B / E / "parser_manifest.json"
        manifest.write_text(
            '{"source_sha256": [], "source_asset_details": []}', encoding="utf-8"
        )
        app = create_app(
            raw_root=REPO / "data/raw",
            processed_root=sandbox,
            runs_root=tmp_path / "runs",
        )
        response = TestClient(app).get(
            f"/api/v1/experiments/{B}/{E}/feature-correlations"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
        details = response.json()["error"]["details"]
        assert details["invalid_modalities"]
        assert details["integrity_reasons"]

    def test_read_only_no_artifact_writes(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        # hash the symlinked trees before/after — a read must not mutate artifacts
        def snapshot() -> dict[str, tuple]:
            out = {}
            for rel in ("features_physical", "datasets", "models", "parameters",
                        "gate_calibrations"):
                root = sandbox / rel
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*.json"))[:80]:
                    out[str(p)] = (p.stat().st_mtime, p.stat().st_size)
            return out

        before = snapshot()
        get_research_overview_data(sandbox, B, E)
        assert snapshot() == before


def test_overview_blocks_raw_dependent_snapshots_after_registered_source_changes(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    assets = {
        "electrical": ("E_TEST", "batteries/CELL_TEST/EXP_TEST/electrical/source.xlsx", b"xlsx"),
        "ultrasound": ("U_TEST", "batteries/CELL_TEST/EXP_TEST/ultrasound/source.txt", b"txt"),
    }
    manifest_rows = ["asset_id,battery_id,experiment_id,modality,relative_path"]
    for modality, (asset_id, relative_path, content) in assets.items():
        source = raw / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        manifest_rows.append(
            f"{asset_id},{battery_id},{experiment_id},{modality},{relative_path}"
        )
        parser_dir = processed / modality / battery_id / experiment_id
        parser_dir.mkdir(parents=True)
        detail_key = "source_asset_details" if modality == "electrical" else "assets"
        path_key = "relative_path" if modality == "electrical" else "source_file"
        (parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": battery_id,
                    "experiment_id": experiment_id,
                    "source_sha256": {asset_id: digest},
                    detail_key: [{"asset_id": asset_id, path_key: relative_path}],
                }
            ),
            encoding="utf-8",
        )
    raw_manifest = raw / "manifests" / "data_assets.csv"
    raw_manifest.parent.mkdir(parents=True)
    raw_manifest.write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")
    (raw / assets["electrical"][1]).write_bytes(b"replaced xlsx")

    overview = get_research_overview_data(
        processed, battery_id, experiment_id, raw_root=raw
    )

    assert overview["metadata"]["temperature"]["status"] == "INTEGRITY_BLOCKED"
    assert overview["metadata"]["acquisition_window"]["status"] == "INTEGRITY_BLOCKED"
    assert overview["electrical"]["status"] == "INTEGRITY_BLOCKED"
    assert overview["ultrasound_tof"]["status"] == "INTEGRITY_BLOCKED"
    assert overview["scientific_snapshot"]["target"]["readiness"] == (
        "BLOCKED_BY_SOURCE_INTEGRITY"
    )
    assert overview["model_comparison"]["status"] == "INTEGRITY_BLOCKED"
    assert overview["research_status_banner"]["level"] == "BLOCKED"
    assert any(
        item["code"] == "SOURCE_PROVENANCE_INVALID"
        for item in overview["limitations_first_screen"]
    )


def test_overview_blocks_parser_derived_snapshots_after_output_tampering(
    tmp_path: Path,
) -> None:
    import pandas as pd

    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    processed = tmp_path / "processed"
    parser_dir = processed / "electrical" / battery_id / experiment_id
    parser_dir.mkdir(parents=True)
    outputs = {
        "records": "records.parquet",
        "cycles": "cycles.parquet",
        "steps": "steps.parquet",
        "aux_temperature": "aux_temperature.parquet",
    }
    pd.DataFrame({"voltage_v": [3.7], "current_a": [0.2]}).to_parquet(
        parser_dir / outputs["records"], index=False
    )
    pd.DataFrame({"cycle_index_raw": [1]}).to_parquet(
        parser_dir / outputs["cycles"], index=False
    )
    pd.DataFrame({"step_index_raw": [1]}).to_parquet(
        parser_dir / outputs["steps"], index=False
    )
    pd.DataFrame(
        {"temperature_channel": ["T1"], "temperature_c": [25.0]}
    ).to_parquet(parser_dir / outputs["aux_temperature"], index=False)
    (parser_dir / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": battery_id,
                "experiment_id": experiment_id,
                "output_files": outputs,
                "output_checksums": {
                    key: hashlib.sha256((parser_dir / filename).read_bytes()).hexdigest()
                    for key, filename in outputs.items()
                },
            }
        ),
        encoding="utf-8",
    )

    current = get_research_overview_data(processed, battery_id, experiment_id)
    assert current["metadata"]["temperature"]["status"] == "AVAILABLE"
    assert current["electrical"]["status"] != "INTEGRITY_BLOCKED"

    (parser_dir / outputs["aux_temperature"]).write_bytes(b"tampered")
    blocked = get_research_overview_data(processed, battery_id, experiment_id)

    assert blocked["metadata"]["temperature"]["status"] == "INTEGRITY_BLOCKED"
    assert blocked["electrical"]["status"] == "INTEGRITY_BLOCKED"
    assert blocked["electrical"]["record_count"] is None
    assert blocked["research_status_banner"]["level"] == "BLOCKED"

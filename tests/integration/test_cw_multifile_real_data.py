from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app
from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.electrical.service import parse_electrical_asset
from battery_workbench.io.ultrasound.service import parse_ultrasound_asset
from battery_workbench.multimodal.service import build_events_for_experiment
from battery_workbench.synchronization.m2k_evidence import read_m2k_acquisition_start
from battery_workbench.synchronization.persistence import write_time_anchor_state
from battery_workbench.synchronization.schemas import (
    AssetAnchorAssessment,
    TimeAnchorConfig,
    TimeAnchorState,
)
from battery_workbench.synchronization.service import assess_experiment_time_anchors
from battery_workbench.synchronization.sync_schemas import SynchronizationConfig
from battery_workbench.synchronization.sync_service import synchronize_ultrasound_to_electrical
from battery_workbench.synchronization.timestamp_engine import build_ultrasound_timestamps
from battery_workbench.synchronization.timestamp_schemas import TimestampEngineConfig

_SOURCE_MAP = Path(__file__).parents[1] / "golden" / "cw_multifile_source_map.csv"
_SOURCE_ROOT_ENV = "BRW_CW_RAW_ROOT"


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get(_SOURCE_ROOT_ENV), reason=f"set {_SOURCE_ROOT_ENV} to run")
def test_cw_multifile_real_data_association() -> None:
    """Replay the explicit 15-pair CW map through production time/sync services.

    Only small M2K evidence XML files and derived Parquets are written, all
    under a temporary directory. Source XLSX/TXT/M2K files remain read-only.
    """
    source_root = Path(os.environ[_SOURCE_ROOT_ENV]).resolve()
    battery_id = "CW_VALIDATION"
    experiment_id = "CW_MULTIFILE_TEST"
    with _SOURCE_MAP.open(encoding="utf-8", newline="") as handle:
        source_pairs = list(csv.DictReader(handle))
    assert len(source_pairs) == 15
    assert len({row["pair_id"] for row in source_pairs}) == len(source_pairs)

    with TemporaryDirectory(prefix="brw-cw-multifile-") as temporary:
        temporary_root = Path(temporary)
        raw_root = temporary_root / "raw"
        processed_root = temporary_root / "processed"
        manifest_root = raw_root / "manifests"
        manifest_root.mkdir(parents=True)

        with (manifest_root / "experiments.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["experiment_id", "battery_id", "start_time", "end_time", "protocol", "notes"]
            )
            writer.writerow(
                [experiment_id, battery_id, "", "", "", "CW explicit source-map validation"]
            )
        (manifest_root / "batteries.csv").write_text(
            "battery_id,chemistry,nominal_capacity_ah,notes\n"
            f"{battery_id},,,real CW integration fixture\n",
            encoding="utf-8",
        )

        records: list[pd.DataFrame] = []
        frame_rows: list[dict] = []
        manifest_rows: list[list[str]] = []
        asset_pair: dict[str, str] = {}
        asset_source_path: dict[str, str] = {}
        electrical_source_hashes: dict[str, str] = {}
        ultrasound_source_hashes: dict[str, str] = {}
        for index, source_pair in enumerate(source_pairs, start=1):
            pair_id = source_pair["pair_id"]
            electrical_id = f"E{index:03d}"
            ultrasound_id = f"U{index:03d}"
            asset_pair[electrical_id] = pair_id
            asset_pair[ultrasound_id] = pair_id

            electrical_relative = Path(source_pair["electrical_relative_path"])
            ultrasound_relative = Path(source_pair["ultrasound_relative_path"])
            evidence_relative = Path(source_pair["time_anchor_metadata_relative_path"])
            for relative in (electrical_relative, ultrasound_relative, evidence_relative):
                assert not relative.is_absolute()
                assert ".." not in relative.parts
                assert (source_root / relative).is_file()
            asset_source_path[electrical_id] = electrical_relative.as_posix()
            asset_source_path[ultrasound_id] = ultrasound_relative.as_posix()

            electrical_asset = DataAsset(
                asset_id=electrical_id,
                battery_id=battery_id,
                experiment_id=experiment_id,
                modality="electrical",
                relative_path=electrical_relative,
            )
            ultrasound_asset = DataAsset(
                asset_id=ultrasound_id,
                battery_id=battery_id,
                experiment_id=experiment_id,
                modality="ultrasound",
                relative_path=ultrasound_relative,
            )
            electrical_result = parse_electrical_asset(
                electrical_asset, source_root, battery_id=battery_id
            )
            ultrasound_result = parse_ultrasound_asset(
                ultrasound_asset, source_root, battery_id=battery_id
            )
            assert len(electrical_result.source_sha256) == 64
            assert len(ultrasound_result.source_sha256) == 64
            assert electrical_result.source_sha256 == source_pair["electrical_sha256"]
            assert ultrasound_result.source_sha256 == source_pair["ultrasound_sha256"]
            electrical_source_hashes[electrical_id] = electrical_result.source_sha256
            ultrasound_source_hashes[ultrasound_id] = ultrasound_result.source_sha256
            records.append(electrical_result.records)

            evidence_relative_in_raw = (
                Path("batteries")
                / battery_id
                / experiment_id
                / "timebase_evidence"
                / f"{ultrasound_id}.xml"
            )
            evidence_copy = raw_root / evidence_relative_in_raw
            evidence_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / evidence_relative, evidence_copy)
            assert (
                read_m2k_acquisition_start(evidence_copy).source_sha256
                == source_pair["time_anchor_metadata_sha256"]
            )

            manifest_rows.extend(
                [
                    [
                        electrical_id,
                        battery_id,
                        experiment_id,
                        "electrical",
                        electrical_relative.as_posix(),
                        "",
                        "",
                        "ElectricalAdapter",
                        "0.1.0",
                        "",
                    ],
                    [
                        ultrasound_id,
                        battery_id,
                        experiment_id,
                        "ultrasound",
                        ultrasound_relative.as_posix(),
                        "",
                        "",
                        "UltrasoundAdapter",
                        "0.1.0",
                        evidence_relative_in_raw.as_posix(),
                    ],
                ]
            )
            anchor = read_m2k_acquisition_start(evidence_copy).anchor_datetime
            for frame in ultrasound_result.frames:
                frame_rows.append(
                    {
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "ultrasound_asset_id": ultrasound_id,
                        "frame_index_raw": frame.frame_index_raw,
                        "source_file": ultrasound_relative.as_posix(),
                        "source_line_index": frame.source_line_index,
                        "waveform_group": f"{ultrasound_id}/waveform",
                        "waveform_row_index": frame.frame_index_raw,
                        "elapsed_time_s": frame.elapsed_time_s,
                        "expected_pair_id": pair_id,
                        "provisional_absolute_timestamp": anchor
                        + pd.to_timedelta(frame.elapsed_time_s, unit="s"),
                        "anchor_id": f"{ultrasound_id}-m2k-config",
                        "anchor_status": "PROVISIONAL",
                        "timestamp_available": True,
                    }
                )

        with (manifest_root / "data_assets.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "asset_id",
                    "battery_id",
                    "experiment_id",
                    "modality",
                    "relative_path",
                    "file_start_time",
                    "file_end_time",
                    "parser_name",
                    "parser_version",
                    "time_anchor_metadata_path",
                ]
            )
            writer.writerows(manifest_rows)

        records_frame = pd.concat(records, ignore_index=True)
        frames_frame = pd.DataFrame(frame_rows)
        electrical_ranges = {
            str(asset_id): (group["timestamp"].min(), group["timestamp"].max())
            for asset_id, group in records_frame.groupby("electrical_asset_id", sort=False)
        }
        for left_index, left_id in enumerate(electrical_ranges):
            left_start, left_end = electrical_ranges[left_id]
            for right_id in list(electrical_ranges)[left_index + 1 :]:
                right_start, right_end = electrical_ranges[right_id]
                assert min(left_end, right_end) <= max(left_start, right_start), (
                    f"unexpected electrical asset coverage overlap: {left_id}, {right_id}"
                )
        records_path = (
            processed_root / "electrical" / battery_id / experiment_id / "records.parquet"
        )
        frames_path = processed_root / "ultrasound" / battery_id / experiment_id / "frames.parquet"
        records_path.parent.mkdir(parents=True)
        frames_path.parent.mkdir(parents=True)
        records_frame.to_parquet(records_path, index=False)
        frames_frame.to_parquet(frames_path, index=False)
        electrical_parser_dir = records_path.parent
        (electrical_parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "source_sha256": electrical_source_hashes,
                    "source_asset_details": [
                        {"asset_id": asset_id, "relative_path": path}
                        for asset_id, path in asset_source_path.items()
                        if asset_id.startswith("E")
                    ],
                }
            ),
            encoding="utf-8",
        )
        ultrasound_parser_dir = frames_path.parent
        (ultrasound_parser_dir / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "source_sha256": ultrasound_source_hashes,
                    "assets": [
                        {"asset_id": asset_id, "source_file": path}
                        for asset_id, path in asset_source_path.items()
                        if asset_id.startswith("U")
                    ],
                }
            ),
            encoding="utf-8",
        )

        anchor_report = assess_experiment_time_anchors(
            experiment_id,
            battery_id=battery_id,
            processed_root=processed_root,
            manifest_root=manifest_root,
            config=TimeAnchorConfig(),
        )
        assert len(anchor_report.assets) == 15
        assert {row["anchor_status"] for row in anchor_report.assets} == {"PROVISIONAL"}
        assert all(
            any(
                evidence["source_type"] == "M2K_CONFIG_DATE_ACQUIS"
                and len(evidence["source_sha256"] or "") == 64
                for evidence in row["evidence"]
            )
            for row in anchor_report.assets
        )
        anchor_state = TimeAnchorState(
            battery_id=battery_id,
            experiment_id=experiment_id,
            anchor_version=anchor_report.anchor_version,
            experiment_reference={"battery_id": battery_id, "experiment_id": experiment_id},
            assets=[AssetAnchorAssessment.model_validate(row) for row in anchor_report.assets],
            warnings=anchor_report.warnings,
            limitations=anchor_report.limitations,
            validated_sync=False,
        )
        anchor_path = write_time_anchor_state(
            anchor_state,
            processed_root=processed_root,
            artifacts_root=temporary_root / "artifacts",
            html_report=anchor_report,
        )["time_anchors"]
        timestamp_report = build_ultrasound_timestamps(
            frames_path=frames_path,
            time_anchor_state_path=anchor_path,
            output_dir=processed_root,
            config=TimestampEngineConfig(),
        )
        assert timestamp_report.timestamp_available_count == len(frames_frame)

        sync_report = synchronize_ultrasound_to_electrical(
            timestamped_frames_path=Path(timestamp_report.artifacts["timestamped_frames"]),
            electrical_records_path=records_path,
            output_dir=processed_root,
            config=SynchronizationConfig(),
        )
        aligned = pd.read_parquet(Path(sync_report.artifacts["aligned"]))
        assert len(aligned) == len(frames_frame)
        assert aligned["ultrasound_asset_id"].nunique() == 15
        assert not sync_report.validated_sync  # timezone remains unverified

        unique = aligned[aligned["match_status"] == "MATCHED_UNIQUE"]
        record_lookup = {
            (str(row.electrical_asset_id), str(row.source_row_index)): row
            for row in records_frame.itertuples(index=False)
        }
        assert len(unique) == 58_475
        assert int((aligned["match_status"] == "MATCHED_AMBIGUOUS").sum()) == 17
        assert int((aligned["match_status"] == "OUT_OF_TOLERANCE").sum()) == 242
        non_unique = aligned[aligned["match_status"] != "MATCHED_UNIQUE"]
        assert non_unique["electrical_asset_id"].isna().all()
        assert non_unique["electrical_record_locator"].isna().all()
        assert non_unique["electrical_timestamp"].isna().all()
        assert non_unique["sync_error_s"].notna().all()
        assert unique["candidate_timestamp_count"].eq(1).all()
        assert unique["candidate_record_count"].eq(1).all()
        candidate_rows = pd.read_parquet(Path(sync_report.artifacts["candidates"]))
        pair_by_asset = {
            **{f"E{index:03d}": row["pair_id"] for index, row in enumerate(source_pairs, 1)},
            **{f"U{index:03d}": row["pair_id"] for index, row in enumerate(source_pairs, 1)},
        }
        assert not candidate_rows.empty
        assert all(
            pair_by_asset[str(row.ultrasound_asset_id)]
            == pair_by_asset[str(row.electrical_asset_id)]
            for row in candidate_rows.itertuples(index=False)
        )
        signed_deltas = (
            pd.to_datetime(candidate_rows["electrical_timestamp"])
            - pd.to_datetime(candidate_rows["ultrasound_timestamp"])
        ).dt.total_seconds()
        assert candidate_rows["signed_time_delta_s"].tolist() == pytest.approx(
            signed_deltas.tolist(), abs=1e-9
        )
        for row in unique.itertuples(index=False):
            record = record_lookup.get(
                (str(row.electrical_asset_id), str(row.electrical_record_locator))
            )
            assert record is not None
            assert record.source_file == asset_source_path[str(row.electrical_asset_id)]
            assert row.source_file == asset_source_path[str(row.ultrasound_asset_id)]
            assert row.source_line_index is not None
            assert (
                asset_pair[str(row.electrical_asset_id)] == asset_pair[str(row.ultrasound_asset_id)]
            )
        assert unique["sync_error_s"].notna().all()
        assert unique["sync_error_s"].median() == pytest.approx(0.031, abs=1e-9)
        if os.environ.get("BRW_CW_PRINT_DIAGNOSTICS") == "1":
            ambiguous = aligned[aligned["match_status"] == "MATCHED_AMBIGUOUS"]
            out_of_tolerance = aligned[aligned["match_status"] == "OUT_OF_TOLERANCE"]
            out_candidates = candidate_rows.merge(
                out_of_tolerance[
                    ["ultrasound_asset_id", "frame_index_raw"]
                ],
                on=["ultrasound_asset_id", "frame_index_raw"],
                how="inner",
            )
            out_candidates["signed_candidate_delta_s"] = (
                pd.to_datetime(out_candidates["electrical_timestamp"])
                - pd.to_datetime(out_candidates["ultrasound_timestamp"])
            ).dt.total_seconds()
            by_asset = {}
            for asset_id, group in out_of_tolerance.groupby("ultrasound_asset_id", sort=True):
                errors = group["sync_error_s"].astype(float)
                signed = out_candidates.loc[
                    out_candidates["ultrasound_asset_id"] == asset_id,
                    "signed_candidate_delta_s",
                ]
                by_asset[str(asset_id)] = {
                    "pair_id": pair_by_asset[str(asset_id)],
                    "frames": len(group),
                    "frame_index_min": int(group["frame_index_raw"].min()),
                    "frame_index_max": int(group["frame_index_raw"].max()),
                    "sync_error_s_p50_p95_max": [
                        float(errors.quantile(0.5)),
                        float(errors.quantile(0.95)),
                        float(errors.max()),
                    ],
                    "signed_candidate_delta_s_min_p50_max": [
                        float(signed.min()),
                        float(signed.median()),
                        float(signed.max()),
                    ],
                }
            print(
                "CW_MULTI_FILE_SYNC_DIAGNOSTICS "
                + json.dumps(
                    {
                        "ambiguous_by_type": ambiguous["ambiguity_type"]
                        .value_counts(dropna=False)
                        .to_dict(),
                        "ambiguous_by_ultrasound_asset": ambiguous.groupby(
                            "ultrasound_asset_id", sort=True
                        ).size().to_dict(),
                        "out_of_tolerance_by_ultrasound_asset": by_asset,
                    },
                    sort_keys=True,
                )
            )

        event_report = build_events_for_experiment(
            battery_id,
            experiment_id,
            processed_root=processed_root,
        )
        assert event_report.event_count == len(aligned)
        event_frame = pd.read_parquet(
            processed_root
            / "multimodal"
            / battery_id
            / experiment_id
            / "measurement_events.parquet"
        )
        event_unique = event_frame[event_frame["match_status"] == "MATCHED_UNIQUE"]
        assert len(event_unique) == len(unique)
        for row in event_unique.itertuples(index=False):
            assert row.source_file == asset_source_path[str(row.ultrasound_asset_id)]
            assert row.electrical_source_file == asset_source_path[str(row.electrical_asset_id)]

        client = TestClient(
            create_app(
                raw_root=raw_root,
                processed_root=processed_root,
                runs_root=temporary_root / "runs",
            )
        )
        sync_response = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/synchronization"
        )
        assert sync_response.status_code == 200, sync_response.text
        sync_data = sync_response.json()["data"]
        assert len(sync_data["electrical_assets"]) == 15
        assert sync_data["electrical_coverage_overlaps"] == []
        assert sync_data["electrical_incompatible_clock_pairs"] == []
        assert all(asset["timestamp_representation"] == "NAIVE" for asset in sync_data["electrical_assets"])
        assert all(asset["timezone_known"] is False for asset in sync_data["electrical_assets"])
        assert all(len(asset["source_files"]) == 1 for asset in sync_data["electrical_assets"])
        summary = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-summary"
        )
        assert summary.status_code == 200, summary.text
        summary_data = summary.json()["data"]
        assert summary_data["total_frames"] == len(aligned)
        assert summary_data["target_labels_available"] is False
        assert summary_data["target_valid"]["soc_reference_percent"] == 0
        sample_response = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples"
            "?filter=eligible&limit=1"
        )
        assert sample_response.status_code == 200, sample_response.text
        sample = sample_response.json()["data"]["samples"][0]
        assert sample["ultrasound_source_file"] == asset_source_path[
            str(sample["ultrasound_asset_id"])
        ]
        assert sample["electrical_source_file"] == asset_source_path[
            str(sample["electrical_asset_id"])
        ]
        ambiguous_response = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples"
            "?filter=ambiguous&limit=200"
        )
        assert ambiguous_response.status_code == 200, ambiguous_response.text
        ambiguous_samples = ambiguous_response.json()["data"]["samples"]
        assert len(ambiguous_samples) == 17
        assert sum(len(row["electrical_candidates"]) for row in ambiguous_samples) >= 34
        for row in ambiguous_samples:
            assert row["match_status"] == "MATCHED_AMBIGUOUS"
            assert row["electrical_asset_id"] is None
            assert row["electrical_record_locator"] is None
            assert row["candidate_record_count"] == len(row["electrical_candidates"])
            candidate_keys = {
                (candidate["electrical_asset_id"], candidate["electrical_record_locator"])
                for candidate in row["electrical_candidates"]
            }
            assert len(candidate_keys) == row["candidate_record_count"]
            assert all(candidate["electrical_source_file"] for candidate in row["electrical_candidates"])
            assert all(
                len(candidate["electrical_source_sha256"] or "") == 64
                for candidate in row["electrical_candidates"]
            )
        unmatched_response = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples"
            "?filter=unmatched&limit=200&cursor=0"
        )
        assert unmatched_response.status_code == 200, unmatched_response.text
        unmatched_second_page = client.get(
            f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples"
            "?filter=unmatched&limit=200&cursor=200"
        )
        assert unmatched_second_page.status_code == 200, unmatched_second_page.text
        out_of_tolerance_samples = (
            unmatched_response.json()["data"]["samples"]
            + unmatched_second_page.json()["data"]["samples"]
        )
        assert len(out_of_tolerance_samples) == 242
        for row in out_of_tolerance_samples:
            assert row["match_status"] == "OUT_OF_TOLERANCE"
            assert row["electrical_asset_id"] is None
            assert row["electrical_record_locator"] is None
            assert row["candidate_details_available"] is True
            assert row["sync_error_s"] > 1.0
            assert row["candidate_record_count"] == len(row["electrical_candidates"])
            assert all(candidate["electrical_asset_id"] for candidate in row["electrical_candidates"])
            assert all(candidate["electrical_record_locator"] for candidate in row["electrical_candidates"])


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get(_SOURCE_ROOT_ENV), reason=f"set {_SOURCE_ROOT_ENV} to run")
def test_cw_multiple_assets_intake_to_alignment_api(tmp_path: Path) -> None:
    """Exercise real multi-file M2K-bound intake through the Alignment API."""
    source_root = Path(os.environ[_SOURCE_ROOT_ENV]).resolve()
    with _SOURCE_MAP.open(encoding="utf-8", newline="") as handle:
        source_pairs = list(csv.DictReader(handle))[:2]
    battery_id = "CW_INTAKE"
    experiment_id = "MULTI_ASSET_INTAKE"
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    manifests = raw_root / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "batteries.csv").write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\n", encoding="utf-8"
    )
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "file_end_time,parser_name,parser_version,time_anchor_metadata_path\n",
        encoding="utf-8",
    )
    client = TestClient(
        create_app(raw_root=raw_root, processed_root=processed_root, runs_root=tmp_path / "runs")
    )
    expected_evidence: dict[str, str] = {}
    created = client.post(
        "/api/v1/experiments",
        json={"battery_id": battery_id, "experiment_id": experiment_id, "name": "CW multi-file"},
    )
    assert created.status_code == 200, created.text
    session = client.post(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/intake-sessions"
    ).json()["data"]
    for pair in source_pairs:
        electrical_path = source_root / pair["electrical_relative_path"]
        ultrasound_path = source_root / pair["ultrasound_relative_path"]
        evidence_path = source_root / pair["time_anchor_metadata_relative_path"]
        evidence_bytes = evidence_path.read_bytes()
        electrical = client.post(
            f"/api/v1/intake-sessions/{session['session_id']}/assets",
            files={"file": (electrical_path.name, electrical_path.read_bytes(), "application/octet-stream")},
            data={"role": "ELECTRICAL"},
        )
        assert electrical.status_code == 200, electrical.text
        ultrasound = client.post(
            f"/api/v1/intake-sessions/{session['session_id']}/assets",
            files={"file": (ultrasound_path.name, ultrasound_path.read_bytes(), "application/octet-stream")},
            data={"role": "ULTRASOUND"},
        )
        assert ultrasound.status_code == 200, ultrasound.text
        ultrasound_intake_id = ultrasound.json()["data"]["intake_asset_id"]
        evidence = client.post(
            f"/api/v1/intake-sessions/{session['session_id']}/assets",
            files={"file": (evidence_path.name, evidence_bytes, "application/xml")},
            data={
                "role": "EXPERIMENT_METADATA",
                "anchor_for_asset_id": ultrasound_intake_id,
            },
        )
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["data"]["anchor_for_asset_id"] == ultrasound_intake_id
        expected_evidence[evidence.json()["data"]["intake_asset_id"]] = hashlib.sha256(
            evidence_bytes
        ).hexdigest()

    detected = client.post(f"/api/v1/intake-sessions/{session['session_id']}/detect")
    assert detected.status_code == 200, detected.text
    validation = client.post(f"/api/v1/intake-sessions/{session['session_id']}/validate")
    assert validation.status_code == 200, validation.text
    assert validation.json()["data"]["overall_passed"] is True
    committed = client.post(f"/api/v1/intake-sessions/{session['session_id']}/commit")
    assert committed.status_code == 200, committed.text
    assert len(committed.json()["data"]["assets"]) == 4

    with (manifests / "data_assets.csv").open(encoding="utf-8", newline="") as handle:
        manifest_assets = list(csv.DictReader(handle))
    assert len(manifest_assets) == 4
    pair_by_committed_asset: dict[str, str] = {}
    source_path_by_asset: dict[str, str] = {}
    original_to_pair = {
        Path(pair[key]).name: pair["pair_id"]
        for pair in source_pairs
        for key in ("electrical_relative_path", "ultrasound_relative_path")
    }
    for asset in manifest_assets:
        pair_id = original_to_pair[Path(asset["relative_path"]).name]
        pair_by_committed_asset[asset["asset_id"]] = pair_id
        source_path_by_asset[asset["asset_id"]] = asset["relative_path"]
    assert sum(bool(row["time_anchor_metadata_path"]) for row in manifest_assets) == 2
    committed_anchor_by_asset = {
        row["asset_id"]: row["time_anchor_metadata_path"]
        for row in manifest_assets
        if row["time_anchor_metadata_path"]
    }
    assert len(committed_anchor_by_asset) == len(expected_evidence) == 2
    import_manifest = json.loads(
        (tmp_path / "artifacts" / "intake" / "import_manifests" / session["session_id"] / "import_manifest.json")
        .read_text(encoding="utf-8")
    )
    expected_hash_by_asset = {
        item["ultrasound_asset_id"]: item["sha256"]
        for item in import_manifest["time_anchor_evidence"]
    }
    assert expected_hash_by_asset == {
        item["ultrasound_asset_id"]: expected_evidence[item["intake_asset_id"]]
        for item in import_manifest["time_anchor_evidence"]
    }

    ingest = client.post(
        "/api/v1/runs",
        json={
            "profile": "INGEST_TO_MEASUREMENT_EVENTS",
            "battery_id": battery_id,
            "experiment_id": experiment_id,
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["data"]["status"] == "SUCCEEDED"
    anchors = json.loads(
        (processed_root / "synchronization" / battery_id / experiment_id / "time_anchors.json")
        .read_text(encoding="utf-8")
    )
    assert len(anchors["assets"]) == 2
    assert {asset["anchor_status"] for asset in anchors["assets"]} == {"PROVISIONAL"}
    assert all(
        any(
            evidence["source_type"] == "M2K_CONFIG_DATE_ACQUIS"
            and len(evidence["source_sha256"] or "") == 64
            for evidence in asset["evidence"]
        )
        for asset in anchors["assets"]
    )
    anchors_by_asset = {asset["asset_id"]: asset for asset in anchors["assets"]}
    assert set(anchors_by_asset) == set(committed_anchor_by_asset)
    for asset_id, relative_path in committed_anchor_by_asset.items():
        expected_hash = expected_hash_by_asset[asset_id]
        evidence_path = raw_root / relative_path
        assert evidence_path.is_file()
        assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == expected_hash
        evidence_item = next(
            item
            for item in anchors_by_asset[asset_id]["evidence"]
            if item["source_type"] == "M2K_CONFIG_DATE_ACQUIS"
        )
        assert evidence_item["source_ref"] == f"{relative_path}#M2kData/@dateAcquis"
        assert evidence_item["source_sha256"] == expected_hash

    aligned = pd.read_parquet(
        processed_root / "synchronization" / battery_id / experiment_id
        / "aligned_ultrasound_frames.parquet"
    )
    assert aligned["ultrasound_asset_id"].nunique() == 2
    for row in aligned.itertuples(index=False):
        assert row.source_file == source_path_by_asset[str(row.ultrasound_asset_id)]
        if row.match_status == "MATCHED_UNIQUE":
            assert row.electrical_asset_id is not None
            assert pair_by_committed_asset[str(row.ultrasound_asset_id)] == pair_by_committed_asset[
                str(row.electrical_asset_id)
            ]

    summary = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-summary"
    )
    assert summary.status_code == 200, summary.text
    summary_data = summary.json()["data"]
    assert summary_data["target_labels_available"] is False
    assert summary_data["total_frames"] == len(aligned)
    sample = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/alignment-samples"
        "?filter=eligible&limit=1"
    )
    assert sample.status_code == 200, sample.text
    sample_row = sample.json()["data"]["samples"][0]
    assert sample_row["ultrasound_source_file"] == source_path_by_asset[
        sample_row["ultrasound_asset_id"]
    ]
    assert sample_row["electrical_source_file"] == source_path_by_asset[
        sample_row["electrical_asset_id"]
    ]
    electrical_hashes = json.loads(
        (processed_root / "electrical" / battery_id / experiment_id / "parser_manifest.json")
        .read_text(encoding="utf-8")
    )["source_sha256"]
    ultrasound_hashes = json.loads(
        (processed_root / "ultrasound" / battery_id / experiment_id / "parser_manifest.json")
        .read_text(encoding="utf-8")
    )["source_sha256"]
    assert sample_row["electrical_source_sha256"] == electrical_hashes[
        sample_row["electrical_asset_id"]
    ]
    assert sample_row["ultrasound_source_sha256"] == ultrasound_hashes[
        sample_row["ultrasound_asset_id"]
    ]
    sync_response = client.get(
        f"/api/v1/experiments/{battery_id}/{experiment_id}/synchronization"
    )
    assert sync_response.status_code == 200, sync_response.text
    api_anchors = {
        anchor["asset_id"]: anchor
        for anchor in sync_response.json()["data"]["time_anchors"]
    }
    assert set(api_anchors) == set(committed_anchor_by_asset)
    for asset_id, relative_path in committed_anchor_by_asset.items():
        expected_hash = expected_hash_by_asset[asset_id]
        api_evidence = next(
            item
            for item in api_anchors[asset_id]["evidence"]
            if item["source_type"] == "M2K_CONFIG_DATE_ACQUIS"
        )
        assert api_evidence["source_ref"] == f"{relative_path}#M2kData/@dateAcquis"
        assert api_evidence["source_sha256"] == expected_hash

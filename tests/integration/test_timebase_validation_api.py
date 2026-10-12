from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]


def _app_with_evidence_root(tmp_path: Path):
    raw_root = tmp_path / "raw"
    manifest_root = raw_root / "manifests"
    manifest_root.mkdir(parents=True)
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
        writer.writerow(
            ["U001", "CELL_001", "EXP_001", "ultrasound", "frames.txt", "", "", "", "", ""]
        )
    evidence = raw_root / "batteries" / "CELL_001" / "EXP_001" / "timebase_evidence"
    evidence.mkdir(parents=True)
    (raw_root / "frames.txt").write_bytes(b"original waveform asset")
    (evidence / "clock-log.csv").write_bytes(b"timestamp,reference\n2024-01-06T13:03:01Z,pulse\n")
    (evidence / "pulse-review.csv").write_bytes(b"asset,error_s\nU001,0.2\n")
    return create_app(
        raw_root=raw_root,
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    ), evidence


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_timebase_evidence_preflight_returns_server_hash_without_writing_state(
    tmp_path: Path,
) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    clock_log = evidence / "clock-log.csv"
    reference = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()

    response = TestClient(app).post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-evidence-preflight",
        json={
            "contract_version": "timebase-evidence-preflight/1.0",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "evidence_refs": [reference],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "SOURCE_FILES_VERIFIED",
        "source_integrity": "VERIFIED",
        "verified_evidence": {
            reference: {"sha256": _sha256(clock_log), "size_bytes": clock_log.stat().st_size}
        },
    }
    assert response.json()["meta"]["read_only"] is True
    assert not list((tmp_path / "processed").rglob("timebase_validations"))


def test_timebase_evidence_preflight_rejects_wrong_identity_missing_and_escaping_paths(
    tmp_path: Path,
) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    reference = (evidence / "clock-log.csv").relative_to(
        app.state.workbench_service.raw_root
    ).as_posix()
    base = {
        "contract_version": "timebase-evidence-preflight/1.0",
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "evidence_refs": [reference],
    }

    mismatch = client.post(
        "/api/v1/experiments/CELL_OTHER/EXP_001/timebase-evidence-preflight",
        json=base,
    )
    missing = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-evidence-preflight",
        json={**base, "evidence_refs": ["batteries/CELL_001/EXP_001/timebase_evidence/missing.csv"]},
    )
    escaping = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-evidence-preflight",
        json={**base, "evidence_refs": ["../outside.csv"]},
    )

    assert mismatch.status_code == 400
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert escaping.status_code == 409
    assert escaping.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_timebase_submission_verifies_anchor_file_and_checksum(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": clock_log.relative_to(
                        app.state.workbench_service.raw_root
                    ).as_posix(),
                    "source_sha256": "a" * 64,
                }
            ],
            "evidence_refs": [
                clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_timebase_submission_rejects_missing_or_escaping_evidence(tmp_path: Path) -> None:
    app, _ = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    missing_ref = "batteries/CELL_001/EXP_001/timebase_evidence/missing.csv"
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": missing_ref,
                    "source_sha256": "a" * 64,
                }
            ],
            "evidence_refs": [missing_ref],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_timebase_acceptance_rejects_missing_review_evidence(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    created = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": clock_ref,
                    "source_sha256": _sha256(clock_log),
                }
            ],
            "evidence_refs": [clock_ref],
        },
    )
    validation_id = created.json()["data"]["validation_id"]
    response = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "reviewer",
            "rationale": "Attempted acceptance without a stored review artifact.",
            "evidence_refs": ["batteries/CELL_001/EXP_001/timebase_evidence/missing-review.csv"],
            "error_by_asset_s": {"U001": 0.2},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_timebase_submission_rejects_path_escape(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    outside = tmp_path / "outside.csv"
    outside.write_text("not a raw evidence file", encoding="utf-8")
    escape_ref = Path("..").joinpath(outside.name).as_posix()
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": escape_ref,
                    "source_sha256": _sha256(outside),
                }
            ],
            "evidence_refs": [escape_ref],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"

    symlink = evidence / "outside-link.csv"
    symlink.symlink_to(outside)
    symlink_ref = symlink.relative_to(app.state.workbench_service.raw_root).as_posix()
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": symlink_ref,
                    "source_sha256": _sha256(outside),
                }
            ],
            "evidence_refs": [symlink_ref],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_timebase_validation_submission_and_review_are_audited(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    pulse_review = evidence / "pulse-review.csv"
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    pulse_ref = pulse_review.relative_to(app.state.workbench_service.raw_root).as_posix()
    body = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "timezone": "Asia/Shanghai",
        "anchors": [
            {
                "asset_id": "U001",
                "absolute_start_time": "2024-01-06T21:03:01+08:00",
                "source_reference": clock_ref,
                "source_sha256": _sha256(clock_log),
            }
        ],
        "evidence_refs": [clock_ref],
        "maximum_allowed_error_s": 0.5,
    }
    created = client.post("/api/v1/experiments/CELL_001/EXP_001/timebase-validations", json=body)
    assert created.status_code == 200
    validation_id = created.json()["data"]["validation_id"]
    assert created.json()["data"]["validated_sync"] is False

    accepted = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "researcher@example.org",
            "rationale": "Checked the recorded synchronization pulse.",
            "evidence_refs": [pulse_ref],
            "error_by_asset_s": {"U001": 0.2},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "ACCEPTED_PENDING_RECOMPUTE"
    assert accepted.json()["data"]["validated_sync"] is False
    assert accepted.json()["data"]["evidence_integrity"] == "VERIFIED"

    detail = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}"
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "ACCEPTED_PENDING_RECOMPUTE"
    assert detail.json()["data"]["source_integrity_status"] == "NOT_ASSESSED"
    assert detail.json()["data"]["effective_status"] == "NOT_ASSESSED"
    assert len(detail.json()["data"]["events"]) == 2
    assert detail.json()["data"]["evidence_integrity"] == "VERIFIED"
    assert detail.json()["data"]["latest_review_evidence_integrity"] == "VERIFIED"
    assert detail.json()["data"]["latest_review_verified_evidence"][pulse_ref]["sha256"] == _sha256(pulse_review)
    assert detail.json()["data"]["verified_evidence"][clock_ref]["sha256"] == _sha256(clock_log)
    assert detail.json()["data"]["events"][-1]["verified_evidence"][pulse_ref]["sha256"] == _sha256(
        pulse_review
    )
    assert detail.json()["data"]["events"][-1]["review_evidence_separation"] == (
        "VERIFIED_DISTINCT_REFERENCES_AND_CHECKSUMS"
    )
    listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")
    assert listing.status_code == 200
    assert listing.json()["data"]["validations"][0]["status"] == "ACCEPTED_PENDING_RECOMPUTE"

    service = app.state.workbench_service
    ultrasound_source = service.raw_root / "frames.txt"
    parser_manifest = (
        service.processed_root
        / "ultrasound"
        / "CELL_001"
        / "EXP_001"
        / "parser_manifest.json"
    )
    parser_manifest.parent.mkdir(parents=True)
    frames_output = parser_manifest.parent / "frames.parquet"
    waveform_output = parser_manifest.parent / "waveforms.zarr"
    frames_output.write_bytes(b"frames")
    waveform_output.mkdir()
    (waveform_output / "chunk.bin").write_bytes(b"waveforms")
    from battery_workbench.provenance.processed_manifest import content_sha256

    parser_manifest.write_text(
        json.dumps(
            {
                "battery_id": "CELL_001",
                "experiment_id": "EXP_001",
                "source_sha256": {"U001": _sha256(ultrasound_source)},
                "assets": [{"asset_id": "U001", "source_file": "frames.txt"}],
                "output_files": {
                    "frames": "frames.parquet",
                    "waveforms": "waveforms.zarr",
                },
                "output_checksums": {
                    "frames": content_sha256(frames_output),
                    "waveforms": content_sha256(waveform_output),
                },
            }
        ),
        encoding="utf-8",
    )
    current_listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")
    assert current_listing.json()["data"]["validations"][0]["source_integrity_status"] == (
        "CURRENT"
    )
    assert current_listing.json()["data"]["validations"][0]["effective_status"] == (
        "ACCEPTED_PENDING_RECOMPUTE"
    )
    ultrasound_source.write_bytes(b"replaced waveform asset")

    stale_listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")
    stale_detail = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}"
    )
    assert stale_listing.status_code == stale_detail.status_code == 200
    assert stale_listing.json()["data"]["validations"][0]["status"] == (
        "ACCEPTED_PENDING_RECOMPUTE"
    )
    assert stale_listing.json()["data"]["validations"][0]["source_integrity_status"] == (
        "STALE_SOURCE"
    )
    assert stale_listing.json()["data"]["validations"][0]["effective_status"] == "STALE_SOURCE"
    assert stale_detail.json()["data"]["source_integrity_status"] == "STALE_SOURCE"

    from battery_workbench.synchronization.timebase_registry import accepted_timebase_overrides

    with pytest.raises(ValueError, match="anchored DataAsset source changed"):
        accepted_timebase_overrides(
            processed_root=service.processed_root,
            raw_root=service.raw_root,
            battery_id="CELL_001",
            experiment_id="EXP_001",
            validation_id=validation_id,
        )
    pending = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations", json=body
    )
    assert pending.status_code == 200
    pending_id = pending.json()["data"]["validation_id"]
    stale_acceptance = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{pending_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "researcher@example.org",
            "rationale": "Attempt to accept against changed source data.",
            "evidence_refs": [pulse_ref],
            "error_by_asset_s": {"U001": 0.2},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert stale_acceptance.status_code == 409
    assert stale_acceptance.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"

    revoked = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "REVOKE",
            "operator_identity": "researcher@example.org",
            "rationale": "Revoke the stale accepted proposal.",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "REVOKED_PROVISIONAL"
    clock_log.write_bytes(b"replaced calibration evidence after review")
    evidence_stale = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}"
    )
    assert evidence_stale.json()["data"]["evidence_integrity_status"] == "STALE_EVIDENCE"


def test_timebase_acceptance_requires_review_evidence_distinct_from_proposal(
    tmp_path: Path,
) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    duplicate_content = evidence / "clock-log-review-copy.csv"
    duplicate_content.write_bytes(clock_log.read_bytes())
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    duplicate_ref = duplicate_content.relative_to(app.state.workbench_service.raw_root).as_posix()
    base = {
        "battery_id": "CELL_001",
        "experiment_id": "EXP_001",
        "timezone": "Asia/Shanghai",
        "anchors": [{
            "asset_id": "U001",
            "absolute_start_time": "2024-01-06T21:03:01+08:00",
            "source_reference": clock_ref,
            "source_sha256": _sha256(clock_log),
        }],
        "evidence_refs": [clock_ref],
        "maximum_allowed_error_s": 0.5,
    }
    same_file = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations", json=base
    )
    same_content = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations", json=base
    )
    assert same_file.status_code == same_content.status_code == 200

    def accept(validation_id: str, reference: str):
        return client.post(
            f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
            json={
                "decision": "ACCEPT",
                "operator_identity": "researcher@example.org",
                "rationale": "Checked timing against an independent audit record.",
                "evidence_refs": [reference],
                "error_by_asset_s": {"U001": 0.2},
                "ambiguity_free_assets": ["U001"],
            },
        )

    same_reference_review = accept(same_file.json()["data"]["validation_id"], clock_ref)
    same_checksum_review = accept(same_content.json()["data"]["validation_id"], duplicate_ref)
    assert same_reference_review.status_code == 409
    assert same_checksum_review.status_code == 409
    assert same_reference_review.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"
    assert same_checksum_review.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


def test_timebase_acceptance_does_not_silently_pass_excess_error(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    pulse_review = evidence / "pulse-review.csv"
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    pulse_ref = pulse_review.relative_to(app.state.workbench_service.raw_root).as_posix()
    created = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U001",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": clock_ref,
                    "source_sha256": _sha256(clock_log),
                }
            ],
            "evidence_refs": [clock_ref],
            "maximum_allowed_error_s": 0.5,
        },
    )
    validation_id = created.json()["data"]["validation_id"]
    response = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "researcher@example.org",
            "rationale": "Review attempted.",
            "evidence_refs": [pulse_ref],
            "error_by_asset_s": {"U001": 0.6},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


def test_timebase_submission_rejects_asset_not_registered_to_experiment(tmp_path: Path) -> None:
    app = create_app(
        raw_root=REPO / "data" / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [
                {
                    "asset_id": "U_NOT_REGISTERED",
                    "absolute_start_time": "2024-01-06T21:03:01+08:00",
                    "source_reference": "clock-log.csv",
                    "source_sha256": "a" * 64,
                }
            ],
            "evidence_refs": ["clock-log.csv"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_corrupt_timebase_registry_returns_integrity_error_not_internal_error(
    tmp_path: Path,
) -> None:
    app, _evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    registry = (
        tmp_path
        / "processed"
        / "synchronization"
        / "CELL_001"
        / "EXP_001"
        / "timebase_validations"
    )
    registry.mkdir(parents=True)
    (registry / "TBV__bad.json").write_text("{truncated", encoding="utf-8")

    listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")

    assert listing.status_code == 409
    assert listing.json()["error"]["code"] == "INTEGRITY_ERROR"
    detail = client.get(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations/TBV::bad"
    )
    assert detail.status_code == 409
    assert detail.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_changed_proposal_evidence_is_visible_and_cannot_be_accepted(tmp_path: Path) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    pulse_review = evidence / "pulse-review.csv"
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    pulse_ref = pulse_review.relative_to(app.state.workbench_service.raw_root).as_posix()
    created = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [{
                "asset_id": "U001",
                "absolute_start_time": "2024-01-06T21:03:01+08:00",
                "source_reference": clock_ref,
                "source_sha256": _sha256(clock_log),
            }],
            "evidence_refs": [clock_ref],
            "maximum_allowed_error_s": 0.5,
        },
    )
    assert created.status_code == 200
    validation_id = created.json()["data"]["validation_id"]
    clock_log.write_bytes(b"replaced clock evidence")

    listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")
    detail = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}"
    )
    assert listing.status_code == detail.status_code == 200
    assert listing.json()["data"]["validations"][0]["evidence_integrity_status"] == (
        "STALE_EVIDENCE"
    )
    assert detail.json()["data"]["evidence_integrity_status"] == "STALE_EVIDENCE"

    accepted = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "researcher@example.org",
            "rationale": "Checked the recorded synchronization pulse.",
            "evidence_refs": [pulse_ref],
            "error_by_asset_s": {"U001": 0.2},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert accepted.status_code == 409
    assert accepted.json()["error"]["code"] == "SCIENTIFIC_READINESS_BLOCKED"


@pytest.mark.parametrize("integrity_status", ["INVALID_RECORD", "NOT_VERIFIED"])
def test_timebase_effective_status_blocks_corrupt_review_evidence(
    tmp_path: Path, integrity_status: str
) -> None:
    app, evidence = _app_with_evidence_root(tmp_path)
    client = TestClient(app)
    clock_log = evidence / "clock-log.csv"
    pulse_review = evidence / "pulse-review.csv"
    clock_ref = clock_log.relative_to(app.state.workbench_service.raw_root).as_posix()
    pulse_ref = pulse_review.relative_to(app.state.workbench_service.raw_root).as_posix()
    created = client.post(
        "/api/v1/experiments/CELL_001/EXP_001/timebase-validations",
        json={
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "timezone": "Asia/Shanghai",
            "anchors": [{
                "asset_id": "U001",
                "absolute_start_time": "2024-01-06T21:03:01+08:00",
                "source_reference": clock_ref,
                "source_sha256": _sha256(clock_log),
            }],
            "evidence_refs": [clock_ref],
            "maximum_allowed_error_s": 0.5,
        },
    )
    validation_id = created.json()["data"]["validation_id"]
    accepted = client.post(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}/review",
        json={
            "decision": "ACCEPT",
            "operator_identity": "reviewer@example.org",
            "rationale": "Checked the recorded pulse against independent evidence.",
            "evidence_refs": [pulse_ref],
            "error_by_asset_s": {"U001": 0.2},
            "ambiguity_free_assets": ["U001"],
        },
    )
    assert accepted.status_code == 200
    audit_path = next(app.state.workbench_service.processed_root.rglob("*.events.jsonl"))
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    if integrity_status == "INVALID_RECORD":
        events[-1]["verified_evidence"][pulse_ref]["sha256"] = "bad"
    else:
        events[-1]["verified_evidence"] = {}
    audit_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )

    listing = client.get("/api/v1/experiments/CELL_001/EXP_001/timebase-validations")
    detail = client.get(
        f"/api/v1/experiments/CELL_001/EXP_001/timebase-validations/{validation_id}"
    )

    assert listing.status_code == detail.status_code == 200
    listed = listing.json()["data"]["validations"][0]
    detailed = detail.json()["data"]
    assert listed["status"] == detailed["status"] == "ACCEPTED_PENDING_RECOMPUTE"
    assert listed["evidence_integrity_status"] == integrity_status
    assert detailed["evidence_integrity_status"] == integrity_status
    assert listed["effective_status"] == detailed["effective_status"] == integrity_status

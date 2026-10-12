from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from battery_workbench.provenance.cohort_pair_review import (
    PAIR_REVIEW_CONTRACT_VERSION,
    PAIR_REVIEW_FIELDS,
    PairReviewValidationError,
    main,
    validate_cohort_pair_review,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    raw_root = tmp_path / "raw"
    manifest_dir = raw_root / "manifests"
    manifest_dir.mkdir(parents=True)
    electrical = raw_root / "batteries/CELL_A/EXP_1/electrical.xlsx"
    ultrasound = raw_root / "batteries/CELL_A/EXP_1/ultrasound.txt"
    time_evidence = raw_root / "evidence/clock.csv"
    identity_evidence = raw_root / "evidence/battery-id.txt"
    pairing_evidence = raw_root / "evidence/pair-log.txt"
    for path, content in (
        (electrical, b"electrical source"),
        (ultrasound, b"ultrasound source"),
        (time_evidence, b"clock source"),
        (identity_evidence, b"battery identity source"),
        (pairing_evidence, b"acquisition pairing source"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with (manifest_dir / "data_assets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["asset_id", "battery_id", "experiment_id", "modality", "relative_path"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "asset_id": "E001", "battery_id": "CELL_A", "experiment_id": "EXP_1",
                "modality": "electrical", "relative_path": "batteries/CELL_A/EXP_1/electrical.xlsx",
            }
        )
        writer.writerow(
            {
                "asset_id": "U001", "battery_id": "CELL_A", "experiment_id": "EXP_1",
                "modality": "ultrasound", "relative_path": "batteries/CELL_A/EXP_1/ultrasound.txt",
            }
        )
    paths = [electrical, ultrasound, time_evidence, identity_evidence, pairing_evidence]
    refs = [path.relative_to(raw_root).as_posix() for path in paths]
    row = dict.fromkeys(PAIR_REVIEW_FIELDS, "")
    row.update(
        {
            "contract_version": PAIR_REVIEW_CONTRACT_VERSION,
            "study_id": "STUDY_1", "review_id": "REV_1", "pair_id": "PAIR_1",
            "battery_id": "CELL_A", "experiment_id": "EXP_1",
            "electrical_asset_id": "E001", "electrical_relative_path": refs[0],
            "electrical_sha256": _sha(electrical), "ultrasound_asset_id": "U001",
            "ultrasound_relative_path": refs[1], "ultrasound_sha256": _sha(ultrasound),
            "time_reference_asset_id": "U001", "time_reference_evidence_relative_path": refs[2],
            "time_reference_evidence_sha256": _sha(time_evidence),
            "battery_identity_evidence_ref": refs[3],
            "battery_identity_evidence_sha256": _sha(identity_evidence),
            "pairing_evidence_ref": refs[4], "pairing_evidence_sha256": _sha(pairing_evidence),
            "battery_identity_review": "ACCEPTED", "pairing_review": "ACCEPTED",
            "clock_evidence_review": "ACCEPTED", "decision": "INCLUDE",
            "reviewer": "reviewer-1", "reviewer_role": "PI",
            "reviewed_at": "2026-10-07T10:00:00+08:00", "rationale": "Evidence reviewed.",
        }
    )
    review_csv = tmp_path / "pair-review.csv"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return raw_root, review_csv, row


def test_valid_review_reports_integrity_without_scientific_authorization(tmp_path: Path) -> None:
    raw_root, review_csv, _ = _fixture(tmp_path)

    result = validate_cohort_pair_review(review_csv, raw_root=raw_root)

    assert result["status"] == "STRUCTURALLY_VALID"
    assert result["contract_version"] == PAIR_REVIEW_CONTRACT_VERSION
    assert result["review_row_count"] == result["pair_count"] == 1
    assert result["latest_decision_counts"]["INCLUDE"] == 1
    assert result["cohort_admission_authorized"] is False
    assert result["reviewer_identity_trust"] == "OPERATOR_ASSERTED_UNAUTHENTICATED"
    assert result["scientific_identity_status"] == "NOT_ASSESSED"
    assert result["timebase_validation_status"] == "NOT_ASSESSED"


def test_include_fails_closed_when_any_review_is_not_accepted(tmp_path: Path) -> None:
    raw_root, review_csv, row = _fixture(tmp_path)
    row["clock_evidence_review"] = "NOT_REVIEWED"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(PairReviewValidationError, match="INCLUDE requires"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_hold_can_record_missing_review_evidence_without_false_acceptance(tmp_path: Path) -> None:
    raw_root, review_csv, row = _fixture(tmp_path)
    row.update(
        {
            "battery_identity_review": "NOT_REVIEWED",
            "pairing_review": "NOT_REVIEWED",
            "clock_evidence_review": "NOT_REVIEWED",
            "decision": "HOLD",
            "time_reference_asset_id": "",
            "time_reference_evidence_relative_path": "",
            "time_reference_evidence_sha256": "",
            "battery_identity_evidence_ref": "",
            "battery_identity_evidence_sha256": "",
            "pairing_evidence_ref": "",
            "pairing_evidence_sha256": "",
        }
    )
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    result = validate_cohort_pair_review(review_csv, raw_root=raw_root)

    assert result["latest_decision_counts"]["HOLD"] == 1
    assert result["cohort_admission_authorized"] is False


def test_published_blank_template_must_be_filled_before_preflight(tmp_path: Path) -> None:
    raw_root, _, _ = _fixture(tmp_path)
    template = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "templates"
        / "cohort-pair-review.csv"
    )

    with pytest.raises(PairReviewValidationError, match="study_id is required"):
        validate_cohort_pair_review(template, raw_root=raw_root)


def test_checksum_mismatch_and_raw_path_escape_are_rejected(tmp_path: Path) -> None:
    raw_root, review_csv, row = _fixture(tmp_path)
    row["electrical_sha256"] = "0" * 64
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(PairReviewValidationError, match="SHA-256 mismatch"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)

    row["electrical_sha256"] = _sha(raw_root / row["electrical_relative_path"])
    row["pairing_evidence_ref"] = "../outside.txt"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(PairReviewValidationError, match="raw-relative"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_revision_must_supersede_latest_review_for_same_pair(tmp_path: Path) -> None:
    raw_root, review_csv, first = _fixture(tmp_path)
    second = dict(
        first,
        review_id="REV_2",
        decision="HOLD",
        reviewed_at="2026-10-07T10:01:00+08:00",
        supersedes_review_id="REV_UNKNOWN",
    )
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows([first, second])

    with pytest.raises(PairReviewValidationError, match="revision must supersede"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_revision_cannot_repoint_pair_id_to_different_source_assets(tmp_path: Path) -> None:
    raw_root, review_csv, first = _fixture(tmp_path)
    alternate = raw_root / "batteries/CELL_A/EXP_1/electrical-replacement.xlsx"
    alternate.write_bytes(b"replacement electrical source")
    manifest = raw_root / "manifests/data_assets.csv"
    with manifest.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "E002",
                "CELL_A",
                "EXP_1",
                "electrical",
                "batteries/CELL_A/EXP_1/electrical-replacement.xlsx",
            ]
        )

    second = dict(
        first,
        review_id="REV_2",
        reviewed_at="2026-10-07T10:01:00+08:00",
        electrical_asset_id="E002",
        electrical_relative_path="batteries/CELL_A/EXP_1/electrical-replacement.xlsx",
        electrical_sha256=_sha(alternate),
        supersedes_review_id="REV_1",
    )
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows([first, second])

    with pytest.raises(PairReviewValidationError, match="source pair identity changed"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_revision_timestamp_must_follow_the_superseded_review(tmp_path: Path) -> None:
    raw_root, review_csv, first = _fixture(tmp_path)
    second = dict(
        first,
        review_id="REV_2",
        decision="HOLD",
        reviewed_at="2026-10-07T09:59:59+08:00",
        supersedes_review_id="REV_1",
    )
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows([first, second])

    with pytest.raises(PairReviewValidationError, match="reviewed_at must be later"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_unknown_contract_version_is_rejected(tmp_path: Path) -> None:
    raw_root, review_csv, row = _fixture(tmp_path)
    row["contract_version"] = "cohort-pair-review/0.9"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(PairReviewValidationError, match="unsupported contract_version"):
        validate_cohort_pair_review(review_csv, raw_root=raw_root)


def test_cli_prints_structural_validation_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw_root, review_csv, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["cohort-pair-review", str(review_csv), "--raw-root", str(raw_root)],
    )

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["cohort_admission_authorized"] is False

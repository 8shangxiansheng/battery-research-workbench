"""Validate a human-reviewed electrical/ultrasound pair audit CSV.

This checks traceability and file integrity only. It cannot authenticate a
reviewer, establish physical battery identity, or validate clock accuracy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from battery_workbench.io.experiment.manifest_loader import data_asset_matches, load_data_assets

PAIR_REVIEW_CONTRACT_VERSION = "cohort-pair-review/1.0"
PAIR_REVIEW_FIELDS = (
    "contract_version",
    "study_id",
    "review_id",
    "pair_id",
    "battery_id",
    "experiment_id",
    "electrical_asset_id",
    "electrical_relative_path",
    "electrical_sha256",
    "ultrasound_asset_id",
    "ultrasound_relative_path",
    "ultrasound_sha256",
    "time_reference_asset_id",
    "time_reference_evidence_relative_path",
    "time_reference_evidence_sha256",
    "battery_identity_evidence_ref",
    "battery_identity_evidence_sha256",
    "pairing_evidence_ref",
    "pairing_evidence_sha256",
    "battery_identity_review",
    "pairing_review",
    "clock_evidence_review",
    "decision",
    "exclusion_rule_id",
    "reviewer",
    "reviewer_role",
    "reviewed_at",
    "rationale",
    "supersedes_review_id",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_REVIEW_STATES = {"NOT_REVIEWED", "ACCEPTED", "REJECTED"}
_DECISIONS = {"HOLD", "INCLUDE", "EXCLUDE"}


class PairReviewValidationError(ValueError):
    """The pair-review audit is malformed or inconsistent with source files."""


def _required(row: dict[str, str], name: str, row_number: int) -> str:
    value = (row.get(name) or "").strip()
    if not value:
        raise PairReviewValidationError(f"row {row_number}: {name} is required")
    return value


def _raw_file(raw_root: Path, reference: str, row_number: int) -> Path:
    relative = PurePosixPath(reference.strip())
    windows = PureWindowsPath(reference.strip())
    if (
        not reference.strip()
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in reference
        or ".." in relative.parts
        or not relative.parts
    ):
        raise PairReviewValidationError(f"row {row_number}: evidence path must be raw-relative")
    root = raw_root.resolve()
    try:
        path = root.joinpath(*relative.parts).resolve(strict=True)
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PairReviewValidationError(
            f"row {row_number}: raw evidence is missing or escapes raw root"
        ) from exc
    if not path.is_file():
        raise PairReviewValidationError(f"row {row_number}: evidence reference is not a file")
    return path


def _verify_hash(raw_root: Path, reference: str, expected: str, row_number: int) -> None:
    if not _SHA256.fullmatch(expected.strip()):
        raise PairReviewValidationError(f"row {row_number}: invalid SHA-256 for {reference}")
    path = _raw_file(raw_root, reference, row_number)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    if digest.lower() != expected.strip().lower():
        raise PairReviewValidationError(f"row {row_number}: SHA-256 mismatch for {reference}")


def _verify_asset(
    *,
    assets: list[Any],
    battery_id: str,
    experiment_id: str,
    asset_id: str,
    modality: str,
    relative_path: str,
    sha256: str,
    raw_root: Path,
    row_number: int,
) -> None:
    matches = [
        asset
        for asset in assets
        if asset.asset_id == asset_id and data_asset_matches(asset, battery_id, experiment_id)
    ]
    if len(matches) != 1:
        raise PairReviewValidationError(
            f"row {row_number}: {asset_id} must resolve to exactly one registered DataAsset"
        )
    asset = matches[0]
    if asset.modality != modality or asset.relative_path.as_posix() != relative_path:
        raise PairReviewValidationError(
            f"row {row_number}: {asset_id} modality/path differs from data_assets.csv"
        )
    _verify_hash(raw_root, relative_path, sha256, row_number)


def validate_cohort_pair_review(
    review_csv: str | Path,
    *,
    raw_root: str | Path,
) -> dict[str, Any]:
    """Check pair-review rows against registered assets and immutable raw bytes."""
    raw_path = Path(raw_root).resolve()
    manifest_path = raw_path / "manifests" / "data_assets.csv"
    if not manifest_path.is_file():
        raise PairReviewValidationError("data_assets.csv is missing under raw root")
    assets = load_data_assets(manifest_path)
    pair_reviews: dict[tuple[str, str], str] = {}
    review_ids: dict[str, tuple[str, str]] = {}
    latest_by_pair: dict[tuple[str, str], dict[str, str]] = {}
    pair_source_identity: dict[tuple[str, str], tuple[str, ...]] = {}
    reviewed_at_by_pair: dict[tuple[str, str], datetime] = {}
    row_count = 0

    with Path(review_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PAIR_REVIEW_FIELDS:
            raise PairReviewValidationError("pair-review CSV header does not match the contract")
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise PairReviewValidationError(f"row {row_number}: unexpected extra CSV fields")
            row = {key: (value or "").strip() for key, value in raw_row.items() if key}
            if not any(row.values()):
                continue
            row_count += 1
            required = {
                key: _required(row, key, row_number)
                for key in (
                    "contract_version", "study_id", "review_id", "pair_id", "battery_id", "experiment_id",
                    "electrical_asset_id", "electrical_relative_path", "electrical_sha256",
                    "ultrasound_asset_id", "ultrasound_relative_path", "ultrasound_sha256",
                    "battery_identity_review", "pairing_review", "clock_evidence_review",
                    "decision", "reviewer", "reviewer_role", "reviewed_at", "rationale",
                )
            }
            if required["contract_version"] != PAIR_REVIEW_CONTRACT_VERSION:
                raise PairReviewValidationError(
                    f"row {row_number}: unsupported contract_version"
                )
            decision = required["decision"]
            states = [
                required["battery_identity_review"],
                required["pairing_review"],
                required["clock_evidence_review"],
            ]
            review_states = dict(
                zip(
                    ("battery_identity_review", "pairing_review", "clock_evidence_review"),
                    states,
                    strict=True,
                )
            )
            if decision not in _DECISIONS or any(state not in _REVIEW_STATES for state in states):
                raise PairReviewValidationError(f"row {row_number}: invalid review status/decision")
            try:
                reviewed_at = datetime.fromisoformat(required["reviewed_at"])
            except ValueError as exc:
                raise PairReviewValidationError(
                    f"row {row_number}: reviewed_at must be ISO-8601 with UTC offset"
                ) from exc
            if reviewed_at.utcoffset() is None:
                raise PairReviewValidationError(
                    f"row {row_number}: reviewed_at must include a UTC offset"
                )
            if decision == "INCLUDE" and states != ["ACCEPTED"] * 3:
                raise PairReviewValidationError(
                    f"row {row_number}: INCLUDE requires all three reviews to be ACCEPTED"
                )
            if decision == "EXCLUDE" and not (row.get("exclusion_rule_id") or "").strip():
                raise PairReviewValidationError(
                    f"row {row_number}: EXCLUDE requires exclusion_rule_id"
                )

            battery_id = required["battery_id"]
            experiment_id = required["experiment_id"]
            _verify_asset(
                assets=assets, battery_id=battery_id, experiment_id=experiment_id,
                asset_id=required["electrical_asset_id"], modality="electrical",
                relative_path=required["electrical_relative_path"],
                sha256=required["electrical_sha256"], raw_root=raw_path, row_number=row_number,
            )
            _verify_asset(
                assets=assets, battery_id=battery_id, experiment_id=experiment_id,
                asset_id=required["ultrasound_asset_id"], modality="ultrasound",
                relative_path=required["ultrasound_relative_path"],
                sha256=required["ultrasound_sha256"], raw_root=raw_path, row_number=row_number,
            )
            optional_evidence = (
                ("battery_identity_review", "battery_identity_evidence_ref", "battery_identity_evidence_sha256"),
                ("pairing_review", "pairing_evidence_ref", "pairing_evidence_sha256"),
                ("clock_evidence_review", "time_reference_evidence_relative_path", "time_reference_evidence_sha256"),
            )
            for status_key, ref_key, hash_key in optional_evidence:
                reference = (row.get(ref_key) or "").strip()
                digest = (row.get(hash_key) or "").strip()
                if (reference or digest) and not (reference and digest):
                    raise PairReviewValidationError(
                        f"row {row_number}: {ref_key} and {hash_key} must be supplied together"
                    )
                if review_states[status_key] == "ACCEPTED" and not (reference and digest):
                    raise PairReviewValidationError(
                        f"row {row_number}: {status_key}=ACCEPTED requires hashed evidence"
                    )
                if reference and digest:
                    _verify_hash(raw_path, reference, digest, row_number)

            clock_asset_id = (row.get("time_reference_asset_id") or "").strip()
            if clock_asset_id:
                if clock_asset_id not in {
                    required["electrical_asset_id"], required["ultrasound_asset_id"]
                }:
                    raise PairReviewValidationError(
                        f"row {row_number}: time reference must be one of the paired DataAssets"
                    )
            elif required["clock_evidence_review"] == "ACCEPTED":
                raise PairReviewValidationError(
                    f"row {row_number}: accepted clock review requires time_reference_asset_id"
                )

            pair_key = (required["study_id"], required["pair_id"])
            previous_reviewed_at = reviewed_at_by_pair.get(pair_key)
            if previous_reviewed_at is not None and reviewed_at <= previous_reviewed_at:
                raise PairReviewValidationError(
                    f"row {row_number}: revision reviewed_at must be later than superseded review"
                )
            source_identity = (
                battery_id,
                experiment_id,
                required["electrical_asset_id"],
                required["electrical_relative_path"],
                required["electrical_sha256"].lower(),
                required["ultrasound_asset_id"],
                required["ultrasound_relative_path"],
                required["ultrasound_sha256"].lower(),
            )
            previous_identity = pair_source_identity.get(pair_key)
            if previous_identity is not None and source_identity != previous_identity:
                raise PairReviewValidationError(
                    f"row {row_number}: source pair identity changed; create a new pair_id"
                )
            review_id = required["review_id"]
            if review_id in review_ids:
                raise PairReviewValidationError(f"row {row_number}: duplicate review_id")
            previous_id = pair_reviews.get(pair_key)
            supersedes = row.get("supersedes_review_id", "")
            if previous_id is None and supersedes:
                raise PairReviewValidationError(
                    f"row {row_number}: first review cannot supersede another review"
                )
            if previous_id is not None and supersedes != previous_id:
                raise PairReviewValidationError(
                    f"row {row_number}: revision must supersede the latest review for this pair"
                )
            pair_reviews[pair_key] = review_id
            pair_source_identity[pair_key] = source_identity
            reviewed_at_by_pair[pair_key] = reviewed_at
            review_ids[review_id] = pair_key
            latest_by_pair[pair_key] = row

    if row_count == 0:
        raise PairReviewValidationError("pair-review CSV contains no review rows")
    decisions = [row["decision"] for row in latest_by_pair.values()]
    return {
        "status": "STRUCTURALLY_VALID",
        "contract_version": PAIR_REVIEW_CONTRACT_VERSION,
        "review_row_count": row_count,
        "pair_count": len(latest_by_pair),
        "latest_decision_counts": {key: decisions.count(key) for key in sorted(_DECISIONS)},
        "cohort_admission_authorized": False,
        "reviewer_identity_trust": "OPERATOR_ASSERTED_UNAUTHENTICATED",
        "scientific_identity_status": "NOT_ASSESSED",
        "timebase_validation_status": "NOT_ASSESSED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a cohort pair-review CSV against raw assets.")
    parser.add_argument("review_csv", type=Path)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    try:
        result = validate_cohort_pair_review(args.review_csv, raw_root=args.raw_root)
    except (OSError, PairReviewValidationError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

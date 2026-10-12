"""Read-only integrity preflight for externally supplied multimodal source maps.

Passing verifies that declared paths and checksums resolve to current bytes. It
does not verify that files belong to the same physical battery or acquisition.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SOURCE_MAP_CONTRACT_VERSION = "declared-source-map/1.0"
SOURCE_MAP_FIELDS = (
    "pair_id",
    "electrical_relative_path",
    "ultrasound_relative_path",
    "time_anchor_metadata_relative_path",
    "electrical_sha256",
    "ultrasound_sha256",
    "time_anchor_metadata_sha256",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class SourceMapPreflightError(ValueError):
    """A declared source map is malformed or its source bytes do not match."""


def _resolve_source(root: Path, reference: str, pair_id: str) -> Path:
    normalized = reference.strip()
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if (
        not normalized
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in normalized
        or ".." in posix.parts
        or not posix.parts
    ):
        raise SourceMapPreflightError(f"{pair_id}: source reference must be relative and confined")
    resolved_root = root.resolve()
    try:
        source = resolved_root.joinpath(*posix.parts).resolve(strict=True)
        source.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SourceMapPreflightError(
            f"{pair_id}: source is missing, unreadable, or escapes the source root"
        ) from exc
    if not source.is_file():
        raise SourceMapPreflightError(f"{pair_id}: source reference is not a file")
    return source


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size_bytes += len(block)
    return digest.hexdigest(), size_bytes


def _verify_source(
    *,
    root: Path,
    pair_id: str,
    reference: str,
    expected_sha256: str,
    modality: str,
) -> dict[str, Any]:
    source = _resolve_source(root, reference, pair_id)
    suffix = source.suffix.lower()
    allowed_suffixes = {
        "electrical": {".xlsx"},
        "ultrasound": {".txt"},
        "time_evidence": {".xml", ".m2k"},
    }
    if suffix not in allowed_suffixes[modality]:
        raise SourceMapPreflightError(
            f"{pair_id}: {modality} source has unsupported extension {suffix!r}"
        )
    if not _SHA256.fullmatch(expected_sha256.strip()):
        raise SourceMapPreflightError(f"{pair_id}: invalid {modality} SHA-256")
    actual_sha256, size_bytes = _file_digest(source)
    if actual_sha256.lower() != expected_sha256.strip().lower():
        raise SourceMapPreflightError(f"{pair_id}: {modality} source SHA-256 mismatch")
    return {
        "source_reference": reference,
        "sha256": actual_sha256,
        "size_bytes": size_bytes,
    }


def validate_declared_source_map(
    source_map_csv: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    """Verify all source files in a declared pair map without assigning identities."""
    map_path = Path(source_map_csv)
    source_root_path = Path(source_root)
    pairs: list[dict[str, Any]] = []
    pair_ids: set[str] = set()
    with map_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        if len(fields) != len(set(fields)) or fields != SOURCE_MAP_FIELDS:
            raise SourceMapPreflightError("source-map header does not match declared-source-map/1.0")
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise SourceMapPreflightError(f"row {row_number}: unexpected extra CSV fields")
            row = {key: (value or "").strip() for key, value in raw_row.items() if key}
            if not any(row.values()):
                continue
            pair_id = row["pair_id"]
            if not pair_id:
                raise SourceMapPreflightError(f"row {row_number}: pair_id is required")
            if pair_id in pair_ids:
                raise SourceMapPreflightError(f"row {row_number}: duplicate pair_id {pair_id}")
            pair_ids.add(pair_id)
            pairs.append(
                {
                    "pair_id": pair_id,
                    "electrical": _verify_source(
                        root=source_root_path,
                        pair_id=pair_id,
                        reference=row["electrical_relative_path"],
                        expected_sha256=row["electrical_sha256"],
                        modality="electrical",
                    ),
                    "ultrasound": _verify_source(
                        root=source_root_path,
                        pair_id=pair_id,
                        reference=row["ultrasound_relative_path"],
                        expected_sha256=row["ultrasound_sha256"],
                        modality="ultrasound",
                    ),
                    "time_reference_evidence": _verify_source(
                        root=source_root_path,
                        pair_id=pair_id,
                        reference=row["time_anchor_metadata_relative_path"],
                        expected_sha256=row["time_anchor_metadata_sha256"],
                        modality="time_evidence",
                    ),
                }
            )
    if not pairs:
        raise SourceMapPreflightError("source map contains no declared pairs")
    map_hash, _ = _file_digest(map_path)
    return {
        "contract_version": SOURCE_MAP_CONTRACT_VERSION,
        "status": "SOURCE_MAP_INTEGRITY_VERIFIED",
        "source_map_filename": map_path.name,
        "source_map_sha256": map_hash,
        "declared_pair_count": len(pairs),
        "pairing_truth_status": "NOT_ASSESSED",
        "battery_identity_status": "NOT_ASSESSED",
        "experiment_identity_status": "NOT_ASSESSED",
        "timebase_validation_status": "NOT_ASSESSED",
        "cohort_admission_authorized": False,
        "pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only checksum preflight for a declared multimodal source map."
    )
    parser.add_argument("source_map_csv", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_declared_source_map(args.source_map_csv, source_root=args.source_root)
    except (OSError, SourceMapPreflightError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

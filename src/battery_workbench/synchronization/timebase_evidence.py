"""Confine timebase evidence references to immutable raw files and verify bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


class TimebaseEvidenceError(ValueError):
    """A timebase evidence reference cannot be verified safely."""


def verify_timebase_evidence_files(
    raw_root: Path,
    references: list[str],
    *,
    expected_sha256: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return hashes/sizes for raw-root-relative evidence refs, rejecting escapes."""
    root = Path(raw_root).resolve()
    expected_sha256 = expected_sha256 or {}
    verified: dict[str, dict[str, Any]] = {}
    for reference in references:
        normalized = reference.strip()
        relative = PurePosixPath(normalized)
        windows_relative = PureWindowsPath(normalized)
        if (
            not normalized
            or relative.is_absolute()
            or windows_relative.is_absolute()
            or windows_relative.drive
            or "\\" in normalized
            or ".." in relative.parts
            or not relative.parts
        ):
            raise TimebaseEvidenceError(
                "timebase evidence reference must be a safe raw-relative path"
            )
        try:
            source_path = root.joinpath(*relative.parts).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TimebaseEvidenceError("timebase evidence file is missing or unreadable") from exc
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise TimebaseEvidenceError(
                "timebase evidence file resolves outside the raw root"
            ) from exc
        if not source_path.is_file():
            raise TimebaseEvidenceError("timebase evidence reference must resolve to a file")
        digest = hashlib.sha256()
        try:
            with source_path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            size_bytes = source_path.stat().st_size
        except OSError as exc:
            raise TimebaseEvidenceError("timebase evidence file is unreadable") from exc
        actual_sha256 = digest.hexdigest()
        expected = expected_sha256.get(normalized)
        if expected is not None and actual_sha256.lower() != expected.lower():
            raise TimebaseEvidenceError("timebase evidence checksum does not match the raw file")
        verified[normalized] = {"sha256": actual_sha256, "size_bytes": size_bytes}
    unexpected_hashes = set(expected_sha256) - set(verified)
    if unexpected_hashes:
        raise TimebaseEvidenceError("expected checksum references were not verified")
    return verified

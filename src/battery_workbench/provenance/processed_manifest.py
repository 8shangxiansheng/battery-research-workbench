"""Integrity verification for processed manifests with declared file lineage."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


def content_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    if path.is_dir():
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
            if item.is_symlink():
                return ""
            relative = item.relative_to(path).as_posix().encode("utf-8")
            digest.update(relative)
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_waveform_store_sha256(path: Path) -> str:
    """Hash waveform-store contents with the FeatureSet manifest contract."""
    if not path.exists() or not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            return ""
        if not item.is_file():
            continue
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    root = Path(root).resolve()
    path = Path(reference)
    if path.is_absolute():
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            # Rebase only known repository data paths for manifests created in
            # another checkout/container; arbitrary host paths are not trusted.
            parts = PurePosixPath(reference.replace("\\", "/")).parts
            anchor = next(
                (
                    index
                    for index in range(len(parts) - 1)
                    if parts[index : index + 2] == ("data", "processed")
                ),
                None,
            )
            if anchor is None:
                return None
            suffix = parts[anchor + 2 :]
    else:
        suffix = path.parts
        if suffix[:2] == ("data", "processed"):
            suffix = suffix[2:]
    if not suffix or any(part in {"", ".", ".."} for part in suffix):
        return None
    resolved = root.joinpath(*suffix).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def verify_manifest_inputs(
    processed_root: Path,
    manifest: Any,
    *,
    required_inputs: set[str] | None = None,
) -> list[str]:
    """Verify declared input paths/checksums, optionally requiring named inputs."""
    if not isinstance(manifest, dict):
        return ["MANIFEST_INVALID"]
    input_paths = manifest.get("input_paths")
    input_checksums = manifest.get("input_checksums")
    if not isinstance(input_paths, dict) or not isinstance(input_checksums, dict):
        return ["INPUT_MANIFEST_INVALID"]

    reasons: list[str] = []
    for key in sorted(required_inputs or set()):
        if not input_paths.get(key) or not input_checksums.get(key):
            reasons.append(f"INPUT_CHECKSUM_MISSING:{key}")
    for key, expected in sorted(input_checksums.items()):
        if not expected:
            continue
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected)
        ):
            reasons.append(f"INPUT_CHECKSUM_INVALID:{key}")
            continue
        path = _resolve_path(processed_root, input_paths.get(key))
        if path is None:
            reasons.append(f"INPUT_PATH_INVALID:{key}")
        elif not path.exists() or not (path.is_file() or path.is_dir()):
            reasons.append(f"INPUT_MISSING:{key}")
        elif content_sha256(path) != expected.lower():
            reasons.append(f"INPUT_CHECKSUM_MISMATCH:{key}")
    return list(dict.fromkeys(reasons))


def verify_manifest_files(
    processed_root: Path,
    manifest: Any,
    *,
    battery_id: str,
    experiment_id: str,
    required_outputs: set[str],
    required_inputs: set[str] | None = None,
) -> list[str]:
    """Return deterministic integrity reasons for declared inputs/outputs.

    Output keys are mandatory because those files are the artifact being
    served. Optional inputs may be absent, but every non-empty declared input
    checksum is verified. No host paths are returned in reason strings.
    """
    if not isinstance(manifest, dict):
        return ["MANIFEST_INVALID"]
    reasons: list[str] = []
    if manifest.get("battery_id") != battery_id:
        reasons.append("MANIFEST_BATTERY_ID_MISMATCH")
    if manifest.get("experiment_id") != experiment_id:
        reasons.append("MANIFEST_EXPERIMENT_ID_MISMATCH")

    output_paths = manifest.get("output_paths")
    output_checksums = manifest.get("output_checksums")
    if not isinstance(output_paths, dict) or not isinstance(output_checksums, dict):
        return [*reasons, "OUTPUT_MANIFEST_INVALID"]
    for key in sorted(required_outputs):
        reference = output_paths.get(key)
        expected = output_checksums.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            reasons.append(f"OUTPUT_CHECKSUM_MISSING:{key}")
            continue
        path = _resolve_path(processed_root, reference)
        if path is None:
            reasons.append(f"OUTPUT_PATH_INVALID:{key}")
        elif not path.is_file():
            reasons.append(f"OUTPUT_MISSING:{key}")
        elif content_sha256(path) != expected.lower():
            reasons.append(f"OUTPUT_CHECKSUM_MISMATCH:{key}")

    reasons.extend(
        verify_manifest_inputs(
            processed_root,
            manifest,
            required_inputs=required_inputs,
        )
    )
    return list(dict.fromkeys(reasons))


def verify_output_checksums_in_directory(
    processed_root: Path,
    output_directory: Path,
    output_checksums: Any,
    required_files: dict[str, str],
) -> list[str]:
    """Verify manifest checksums for known files under a confined artifact directory."""
    root = Path(processed_root).resolve()
    directory = Path(output_directory)
    try:
        directory = directory.resolve(strict=True)
        directory.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return ["OUTPUT_DIRECTORY_INVALID"]
    if not isinstance(output_checksums, dict):
        return ["OUTPUT_CHECKSUMS_INVALID"]

    reasons: list[str] = []
    for key, filename in sorted(required_files.items()):
        expected = output_checksums.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            reasons.append(f"OUTPUT_CHECKSUM_MISSING:{key}")
            continue
        try:
            path = (directory / filename).resolve(strict=True)
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            reasons.append(f"OUTPUT_PATH_INVALID:{key}")
            continue
        if not path.is_file():
            reasons.append(f"OUTPUT_MISSING:{key}")
        elif content_sha256(path) != expected.lower():
            reasons.append(f"OUTPUT_CHECKSUM_MISMATCH:{key}")
    return reasons

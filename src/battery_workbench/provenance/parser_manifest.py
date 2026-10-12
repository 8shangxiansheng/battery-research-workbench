"""Structural and confinement checks for processed parser source manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from battery_workbench.provenance.processed_manifest import content_sha256

_PARSER_OUTPUTS: dict[str, dict[str, str]] = {
    "electrical": {
        "records": "records.parquet",
        "cycles": "cycles.parquet",
        "steps": "steps.parquet",
        "aux_temperature": "aux_temperature.parquet",
        "aux_voltage": "aux_voltage.parquet",
    },
    "ultrasound": {
        "frames": "frames.parquet",
        "waveforms": "waveforms.zarr",
    },
}


def parser_output_integrity_reasons(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
) -> dict[str, list[str]]:
    """Verify canonical parser outputs against checksums recorded at parse time.

    Legacy parser manifests without output checksums are reported as unverifiable;
    their historical checksums are never reconstructed from current bytes.
    """
    root = Path(processed_root).resolve()
    result: dict[str, list[str]] = {}
    for modality, known_outputs in _PARSER_OUTPUTS.items():
        directory = root / modality / battery_id / experiment_id
        manifest_path = directory / "parser_manifest.json"
        has_output = any(
            (directory / filename).exists() or (directory / filename).is_symlink()
            for filename in known_outputs.values()
        )
        if not manifest_path.exists() and not manifest_path.is_symlink():
            if has_output:
                result[modality] = ["PARSER_MANIFEST_MISSING"]
            continue
        reasons: list[str] = []
        try:
            resolved_directory = directory.resolve(strict=True)
            resolved_directory.relative_to(root)
            resolved_manifest = manifest_path.resolve(strict=True)
            resolved_manifest.relative_to(resolved_directory)
            manifest: Any = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            result[modality] = ["PARSER_MANIFEST_UNREADABLE_OR_PATH_INVALID"]
            continue
        if not isinstance(manifest, dict):
            result[modality] = ["PARSER_MANIFEST_INVALID"]
            continue
        if manifest.get("battery_id") != battery_id:
            reasons.append("PARSER_BATTERY_ID_MISMATCH")
        if manifest.get("experiment_id") != experiment_id:
            reasons.append("PARSER_EXPERIMENT_ID_MISMATCH")
        output_files = manifest.get("output_files")
        output_checksums = manifest.get("output_checksums")
        if not isinstance(output_files, dict) or not isinstance(output_checksums, dict):
            reasons.append("OUTPUT_CHECKSUMS_INVALID")
            result[modality] = reasons
            continue
        required = {"records", "cycles", "steps"} if modality == "electrical" else set(known_outputs)
        selected_keys = required | (set(output_files) & set(known_outputs))
        for key in sorted(selected_keys):
            expected_filename = known_outputs[key]
            filename = output_files.get(key)
            if filename != expected_filename:
                reasons.append(f"OUTPUT_PATH_INVALID:{key}")
                continue
            expected_checksum = output_checksums.get(key)
            if (
                not isinstance(expected_checksum, str)
                or len(expected_checksum) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in expected_checksum)
            ):
                reasons.append(f"OUTPUT_CHECKSUM_MISSING:{key}")
                continue
            candidate = directory / expected_filename
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_directory)
            except (OSError, RuntimeError, ValueError):
                reasons.append(f"OUTPUT_MISSING_OR_PATH_INVALID:{key}")
                continue
            if not (resolved.is_file() or resolved.is_dir()):
                reasons.append(f"OUTPUT_MISSING_OR_PATH_INVALID:{key}")
            elif content_sha256(resolved) != expected_checksum.lower():
                reasons.append(f"OUTPUT_CHECKSUM_MISMATCH:{key}")
        result[modality] = list(dict.fromkeys(reasons))
    return result


def invalid_parser_output_modalities(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
) -> list[str]:
    """Return modalities whose canonical outputs are missing or unverifiable."""
    return sorted(
        modality
        for modality, reasons in parser_output_integrity_reasons(
            processed_root, battery_id, experiment_id
        ).items()
        if reasons
    )


def invalid_parser_manifest_modalities(
    processed_root: Path, battery_id: str, experiment_id: str
) -> list[str]:
    """Return modalities with invalid parser manifests or unverifiable outputs."""
    invalid: list[str] = []
    root = Path(processed_root).resolve()
    for modality in ("electrical", "ultrasound"):
        path = root / modality / battery_id / experiment_id / "parser_manifest.json"
        if not path.exists() and not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            invalid.append(modality)
            continue
        if not resolved.is_file():
            invalid.append(modality)
            continue
        try:
            manifest: Any = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            invalid.append(modality)
            continue
        if not isinstance(manifest, dict):
            invalid.append(modality)
            continue
        source_hashes = manifest.get("source_sha256")
        if source_hashes is not None and (
            not isinstance(source_hashes, dict)
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in value)
                for value in source_hashes.values()
            )
        ):
            invalid.append(modality)
            continue
        details_key = "source_asset_details" if modality == "electrical" else "assets"
        details = manifest.get(details_key)
        if details is not None and (
            not isinstance(details, list)
            or any(not isinstance(item, dict) for item in details)
        ):
            invalid.append(modality)
    invalid.extend(
        modality
        for modality in invalid_parser_output_modalities(
            root, battery_id, experiment_id
        )
        if modality not in invalid
    )
    return invalid


def parser_manifest_raw_source_mismatches(
    processed_root: Path, raw_root: Path, battery_id: str, experiment_id: str
) -> list[str]:
    """Return modalities whose parser provenance no longer matches registered raw bytes.

    This is intentionally stricter than structural validation: a model or other
    downstream artifact is not current if the DataAsset manifest, parser source
    mapping, source path, or current raw file bytes differ from the parse record.
    """
    from battery_workbench.io.experiment.manifest_loader import (
        data_asset_matches,
        load_data_assets,
    )

    processed = Path(processed_root).resolve()
    raw = Path(raw_root).resolve()
    assets_manifest = raw / "manifests" / "data_assets.csv"
    parsed_modalities = [
        modality
        for modality in ("electrical", "ultrasound")
        if (
            processed / modality / battery_id / experiment_id / "parser_manifest.json"
        ).exists()
        or (
            processed / modality / battery_id / experiment_id / "parser_manifest.json"
        ).is_symlink()
    ]
    try:
        resolved_assets_manifest = assets_manifest.resolve(strict=True)
        resolved_assets_manifest.relative_to(raw)
    except (OSError, RuntimeError, ValueError):
        return parsed_modalities
    if not resolved_assets_manifest.is_file():
        return parsed_modalities
    try:
        assets = [
            asset
            for asset in load_data_assets(resolved_assets_manifest)
            if data_asset_matches(asset, battery_id, experiment_id)
        ]
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        return parsed_modalities

    mismatches: list[str] = []
    for modality in ("electrical", "ultrasound"):
        modality_assets = [asset for asset in assets if asset.modality == modality]
        manifest_path = processed / modality / battery_id / experiment_id / "parser_manifest.json"
        if not manifest_path.exists() and not manifest_path.is_symlink():
            # A source asset with no processed modality output is a first parse,
            # not stale provenance. Missing manifests alongside existing
            # canonical files remain invalid and require parser recovery.
            modality_dir = manifest_path.parent
            if modality_assets and (modality_dir.exists() or modality_dir.is_symlink()):
                try:
                    resolved_dir = modality_dir.resolve(strict=True)
                    resolved_dir.relative_to(processed)
                    if not resolved_dir.is_dir() or any(resolved_dir.iterdir()):
                        mismatches.append(modality)
                except (OSError, RuntimeError, ValueError):
                    mismatches.append(modality)
            continue
        try:
            resolved_manifest = manifest_path.resolve(strict=True)
            resolved_manifest.relative_to(processed)
            manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            mismatches.append(modality)
            continue
        if not isinstance(manifest, dict):
            mismatches.append(modality)
            continue
        hashes = manifest.get("source_sha256")
        details_key = "source_asset_details" if modality == "electrical" else "assets"
        path_key = "relative_path" if modality == "electrical" else "source_file"
        details = manifest.get(details_key)
        expected_ids = {asset.asset_id for asset in modality_assets}
        if (
            manifest.get("battery_id") != battery_id
            or manifest.get("experiment_id") != experiment_id
            or not isinstance(hashes, dict)
            or set(hashes) != expected_ids
            or not isinstance(details, list)
            or any(not isinstance(item, dict) for item in details)
        ):
            mismatches.append(modality)
            continue
        details_by_id = {
            str(item.get("asset_id")): item for item in details if item.get("asset_id")
        }
        if len(details_by_id) != len(details) or set(details_by_id) != expected_ids:
            mismatches.append(modality)
            continue
        valid = True
        for asset in modality_assets:
            expected_path = asset.relative_path.as_posix()
            if details_by_id[asset.asset_id].get(path_key) != expected_path:
                valid = False
                break
            try:
                source_path = (raw / asset.relative_path).resolve(strict=True)
                source_path.relative_to(raw)
                if not source_path.is_file() or not isinstance(hashes.get(asset.asset_id), str):
                    valid = False
                    break
                digest = hashlib.sha256()
                with source_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest().lower() != hashes[asset.asset_id].lower():
                    valid = False
                    break
            except (OSError, RuntimeError, ValueError):
                valid = False
                break
        if not valid:
            mismatches.append(modality)
    return mismatches


def invalid_parser_source_modalities(
    processed_root: Path,
    raw_root: Path,
    battery_id: str,
    experiment_id: str,
) -> list[str]:
    """Combine parser manifest, derived-output, and current raw-byte integrity checks."""
    return sorted(
        set(invalid_parser_manifest_modalities(processed_root, battery_id, experiment_id))
        | set(invalid_parser_output_modalities(processed_root, battery_id, experiment_id))
        | set(
            parser_manifest_raw_source_mismatches(
                processed_root, raw_root, battery_id, experiment_id
            )
        )
    )

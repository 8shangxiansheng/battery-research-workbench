"""Input fingerprints for provisional experiment time-anchor artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_time_anchor_config(raw_root: Path) -> Path:
    """Match the config selection used by the TimeAnchor node."""
    config_path = Path(raw_root).parent.parent / "configs" / "time_anchor.yaml"
    if config_path.is_file():
        return config_path
    return Path(__file__).resolve().parents[3] / "configs" / "time_anchor.yaml"


def time_anchor_input_fingerprint(
    *,
    raw_root: Path,
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    config_path: Path,
    validation_id: str | None,
) -> dict[str, dict[str, str]]:
    """Hash every file that can affect TimeAnchor assessment or accepted overrides.

    Missing optional inputs are represented explicitly so a later file arrival
    invalidates a cached state. Paths are recorded relative to their owning root
    where possible; external config paths retain their absolute local path.
    """
    from battery_workbench.io.experiment.manifest_loader import (
        data_asset_matches,
        load_data_assets,
    )

    raw = Path(raw_root).resolve()
    processed = Path(processed_root).resolve()
    experiment_dir = processed / "synchronization" / battery_id / experiment_id
    raw_files: dict[str, Path] = {
        "raw:experiments_manifest": raw / "manifests" / "experiments.csv",
        "raw:data_assets_manifest": raw / "manifests" / "data_assets.csv",
    }
    processed_files: dict[str, Path] = {
        "processed:ultrasound_frames": (
            processed / "ultrasound" / battery_id / experiment_id / "frames.parquet"
        ),
        "processed:electrical_records": (
            processed / "electrical" / battery_id / experiment_id / "records.parquet"
        ),
        "processed:ultrasound_parser_manifest": (
            processed / "ultrasound" / battery_id / experiment_id / "parser_manifest.json"
        ),
        "processed:electrical_parser_manifest": (
            processed / "electrical" / battery_id / experiment_id / "parser_manifest.json"
        ),
    }
    raw_manifest = raw_files["raw:data_assets_manifest"]
    if raw_manifest.is_file():
        try:
            assets = [
                asset
                for asset in load_data_assets(raw_manifest)
                if data_asset_matches(asset, battery_id, experiment_id)
                and asset.modality == "ultrasound"
            ]
        except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            assets = []
        for asset in assets:
            if asset.time_anchor_metadata_path is not None:
                raw_files[f"raw:time_anchor_metadata:{asset.asset_id}"] = (
                    raw / asset.time_anchor_metadata_path
                )

    config_path = Path(config_path)
    try:
        resolved_config = config_path.resolve(strict=False)
        resolved_config.relative_to(raw)
        raw_files["raw:time_anchor_config"] = resolved_config
    except ValueError:
        try:
            resolved_config.relative_to(processed)
            processed_files["processed:time_anchor_config"] = resolved_config
        except ValueError:
            pass
    external_files: dict[str, Path] = {}
    if not any(path == config_path.resolve(strict=False) for path in raw_files.values()) and not any(
        path == config_path.resolve(strict=False) for path in processed_files.values()
    ):
        external_files["external:time_anchor_config"] = config_path

    if validation_id:
        registry_dir = experiment_dir / "timebase_validations"
        safe_id = validation_id.replace(":", "_")
        submission_path = registry_dir / f"{safe_id}.json"
        event_path = registry_dir / f"{safe_id}.events.jsonl"
        processed_files["processed:timebase_validation_submission"] = submission_path
        processed_files["processed:timebase_validation_events"] = event_path
        try:
            submission: Any = json.loads(submission_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            submission = None
        evidence_refs: set[str] = set()
        if isinstance(submission, dict):
            evidence_refs.update(str(ref) for ref in submission.get("evidence_refs", []))
            for ref in (submission.get("verified_evidence") or {}):
                evidence_refs.add(str(ref))
        try:
            events = [
                json.loads(line)
                for line in event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            events = []
        for event in events:
            evidence_refs.update(str(ref) for ref in event.get("evidence_refs", []))
            for ref in (event.get("verified_evidence") or {}):
                evidence_refs.add(str(ref))
        for reference in sorted(evidence_refs):
            raw_files[f"raw:timebase_evidence:{reference}"] = raw / reference

    result: dict[str, dict[str, str]] = {}
    for key, path in sorted({**raw_files, **processed_files, **external_files}.items()):
        if key.startswith("raw:"):
            root = raw
            scope = "raw"
        elif key.startswith("processed:"):
            root = processed
            scope = "processed"
        else:
            root = None
            scope = "external"
        try:
            resolved = path.resolve(strict=False)
            relative = resolved.relative_to(root).as_posix() if root is not None else str(resolved)
        except (OSError, RuntimeError, ValueError):
            result[key] = {"scope": scope, "path": "INVALID", "sha256": "INVALID_PATH"}
            continue
        if root is not None:
            try:
                resolved.relative_to(root)
            except ValueError:
                result[key] = {"scope": scope, "path": "INVALID", "sha256": "INVALID_PATH"}
                continue
        if path.is_file():
            try:
                checksum = _sha256(path.resolve(strict=True))
            except (OSError, RuntimeError, ValueError):
                checksum = "UNREADABLE"
        else:
            checksum = "MISSING"
        result[key] = {"scope": scope, "path": relative, "sha256": checksum}
    return result


def time_anchor_artifact_integrity_reasons(
    *,
    raw_root: Path,
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
) -> list[str]:
    """Return reasons a persisted TimeAnchor cannot be treated as current."""
    from battery_workbench.provenance.processed_manifest import (
        verify_output_checksums_in_directory,
    )

    root = Path(processed_root).resolve()
    artifact_dir = root / "synchronization" / battery_id / experiment_id
    state_path = artifact_dir / "time_anchors.json"
    manifest_path = artifact_dir / "time_anchor_manifest.json"
    for path, missing_reason in (
        (state_path, "TIME_ANCHOR_STATE_MISSING"),
        (manifest_path, "TIME_ANCHOR_MANIFEST_MISSING"),
    ):
        try:
            path.resolve(strict=True).relative_to(root)
        except FileNotFoundError:
            return [missing_reason]
        except (OSError, RuntimeError, ValueError):
            return ["TIME_ANCHOR_PATH_INVALID"]

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["TIME_ANCHOR_ARTIFACT_UNREADABLE"]
    if not isinstance(state, dict) or not isinstance(manifest, dict):
        return ["TIME_ANCHOR_ARTIFACT_INVALID"]
    if state.get("battery_id") != battery_id or manifest.get("battery_id") != battery_id:
        return ["TIME_ANCHOR_BATTERY_ID_MISMATCH"]
    if state.get("experiment_id") != experiment_id or manifest.get("experiment_id") != experiment_id:
        return ["TIME_ANCHOR_EXPERIMENT_ID_MISMATCH"]
    if state.get("anchor_version") != manifest.get("anchor_version"):
        return ["TIME_ANCHOR_VERSION_MISMATCH"]

    validation_id = state.get("timebase_validation_id")
    if manifest.get("timebase_validation_id") != validation_id:
        return ["TIMEBASE_VALIDATION_ID_MISMATCH"]
    if validation_id:
        from battery_workbench.synchronization.timebase_registry import (
            TimebaseRegistryError,
            accepted_timebase_overrides,
        )

        try:
            overrides = accepted_timebase_overrides(
                processed_root=root,
                battery_id=battery_id,
                experiment_id=experiment_id,
                validation_id=str(validation_id),
                raw_root=Path(raw_root),
            )
        except (OSError, ValueError, TimebaseRegistryError):
            return ["TIMEBASE_VALIDATION_INVALID"]
        if not overrides:
            return ["TIMEBASE_VALIDATION_NOT_ACCEPTED"]

    expected_fingerprint = time_anchor_input_fingerprint(
        raw_root=Path(raw_root),
        processed_root=root,
        battery_id=battery_id,
        experiment_id=experiment_id,
        config_path=resolve_time_anchor_config(Path(raw_root)),
        validation_id=str(validation_id) if validation_id else None,
    )
    if manifest.get("input_fingerprint") != expected_fingerprint:
        return ["TIME_ANCHOR_SOURCE_STALE"]
    output_reasons = verify_output_checksums_in_directory(
        root,
        artifact_dir,
        manifest.get("output_checksums"),
        {"time_anchors": "time_anchors.json"},
    )
    return [f"TIME_ANCHOR_{reason}" for reason in output_reasons]

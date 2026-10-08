"""Read-only validation for explicitly reviewed source Cycle/Step mappings.

Validation proves declaration completeness and byte-level lineage only. The
mapping is not consumed by label generation, dataset construction, or analysis.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pandas as pd

from battery_workbench.provenance.parser_manifest import invalid_parser_source_modalities

CYCLE_STEP_MAPPING_VERSION = "cycle-step-mapping/1.0"
CYCLE_STEP_MAPPING_FIELDS = (
    "contract_version",
    "mapping_id",
    "battery_id",
    "experiment_id",
    "electrical_asset_id",
    "cycle_index_raw",
    "step_index_raw",
    "canonical_cycle_index",
    "canonical_step_index",
    "parser_manifest_sha256",
    "evidence_relative_path",
    "evidence_sha256",
    "review_status",
    "reviewer",
    "reviewed_at",
    "rationale",
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CycleStepMappingError(ValueError):
    """A mapping is malformed, incomplete, stale, or ambiguous."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required(row: dict[str, str], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise CycleStepMappingError(f"row {row_number}: {field} is required")
    return value


def _integer(value: Any, *, field: str, row_number: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CycleStepMappingError(f"row {row_number}: {field} must be an integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise CycleStepMappingError(f"row {row_number}: {field} must be an integer")
    return int(number)


def _raw_evidence(raw_root: Path, reference: str, expected_sha256: str, row_number: int) -> None:
    relative = PurePosixPath(reference)
    windows = PureWindowsPath(reference)
    if (
        not reference
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in reference
        or ".." in relative.parts
    ):
        raise CycleStepMappingError(f"row {row_number}: evidence path must be raw-relative")
    root = raw_root.resolve()
    try:
        evidence = root.joinpath(*relative.parts).resolve(strict=True)
        evidence.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise CycleStepMappingError(
            f"row {row_number}: evidence file is missing or escapes raw root"
        ) from exc
    if not evidence.is_file() or not _SHA256_RE.fullmatch(expected_sha256):
        raise CycleStepMappingError(f"row {row_number}: evidence file/hash is invalid")
    if _sha256(evidence) != expected_sha256.lower():
        raise CycleStepMappingError(f"row {row_number}: evidence SHA-256 mismatch")


def _source_keys(
    frame: pd.DataFrame,
    *,
    artifact: str,
    battery_id: str,
    experiment_id: str,
) -> set[tuple[str, int, int | None]]:
    required = {"battery_id", "experiment_id", "electrical_asset_id", "cycle_index_raw"}
    if artifact == "steps":
        required.add("step_index_raw")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CycleStepMappingError(f"{artifact} artifact missing columns: {', '.join(missing)}")
    if frame.empty or frame[list(required)].isna().any().any():
        raise CycleStepMappingError(f"{artifact} artifact has empty/null source identity")
    if set(frame["battery_id"].astype(str)) != {battery_id}:
        raise CycleStepMappingError(f"{artifact} Battery identity mismatch")
    if set(frame["experiment_id"].astype(str)) != {experiment_id}:
        raise CycleStepMappingError(f"{artifact} Experiment identity mismatch")

    keys: set[tuple[str, int, int | None]] = set()
    for row in frame.itertuples(index=False):
        values = row._asdict()
        asset_id = str(values["electrical_asset_id"]).strip()
        if not asset_id:
            raise CycleStepMappingError(f"{artifact} artifact has blank electrical_asset_id")
        cycle = _integer(values["cycle_index_raw"], field="cycle_index_raw", row_number=0)
        step = (
            _integer(values["step_index_raw"], field="step_index_raw", row_number=0)
            if artifact == "steps"
            else None
        )
        keys.add((asset_id, cycle, step))
    if len(keys) != len(frame):
        raise CycleStepMappingError(f"{artifact} artifact has duplicate source identity rows")
    return keys


def _read_mapping(path: Path) -> tuple[list[dict[str, str]], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CycleStepMappingError("mapping CSV is missing or unreadable") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CycleStepMappingError("mapping CSV must be UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    if tuple(reader.fieldnames or ()) != CYCLE_STEP_MAPPING_FIELDS:
        raise CycleStepMappingError("mapping CSV header does not match cycle-step-mapping/1.0")
    rows: list[dict[str, str]] = []
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise CycleStepMappingError(f"row {row_number}: unexpected extra CSV fields")
        row = {key: (value or "").strip() for key, value in raw_row.items() if key}
        if any(row.values()):
            rows.append(row)
    if not rows:
        raise CycleStepMappingError("mapping CSV has no reviewed source steps")
    return rows, hashlib.sha256(raw).hexdigest()


def validate_cycle_step_mapping(
    mapping_csv: str | Path,
    *,
    raw_root: str | Path,
    processed_root: str | Path,
    battery_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    """Validate complete source-step coverage and a one-to-one canonical map.

    Distinct source steps may be assigned to one canonical Cycle (for an
    operator-declared cross-asset continuation), but two source steps may not
    collapse to the same canonical Cycle/Step in V1.0.
    """
    raw = Path(raw_root).resolve()
    processed = Path(processed_root).resolve()
    electrical_dir = processed / "electrical" / battery_id / experiment_id
    manifest_path = electrical_dir / "parser_manifest.json"
    cycles_path = electrical_dir / "cycles.parquet"
    steps_path = electrical_dir / "steps.parquet"
    try:
        manifest_resolved = manifest_path.resolve(strict=True)
        manifest_resolved.relative_to(electrical_dir.resolve(strict=True))
        manifest = json.loads(manifest_resolved.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CycleStepMappingError(
            "canonical Electrical parser manifest is missing/invalid"
        ) from exc
    if not isinstance(manifest, dict):
        raise CycleStepMappingError("canonical Electrical parser manifest must be an object")
    if manifest.get("battery_id") != battery_id or manifest.get("experiment_id") != experiment_id:
        raise CycleStepMappingError("parser manifest Battery/Experiment identity mismatch")
    invalid_modalities = invalid_parser_source_modalities(processed, raw, battery_id, experiment_id)
    if "electrical" in invalid_modalities:
        raise CycleStepMappingError(
            "Electrical parser sources/outputs are not current/integrity-verified"
        )

    rows, mapping_sha256 = _read_mapping(Path(mapping_csv))
    parser_manifest_sha256 = _sha256(manifest_resolved)
    source_keys: set[tuple[str, int, int]] = set()
    target_keys: set[tuple[int, int]] = set()
    canonical_cycle_by_source_cycle: dict[tuple[str, int], int] = {}
    context: dict[str, str] | None = None

    for row_number, row in enumerate(rows, start=2):
        required = {
            field: _required(row, field, row_number)
            for field in (
                "contract_version",
                "mapping_id",
                "battery_id",
                "experiment_id",
                "electrical_asset_id",
                "parser_manifest_sha256",
                "evidence_relative_path",
                "evidence_sha256",
                "review_status",
                "reviewer",
                "reviewed_at",
                "rationale",
            )
        }
        if required["contract_version"] != CYCLE_STEP_MAPPING_VERSION:
            raise CycleStepMappingError(f"row {row_number}: unsupported contract_version")
        if required["review_status"] != "ACCEPTED":
            raise CycleStepMappingError(f"row {row_number}: review_status must be ACCEPTED")
        if required["battery_id"] != battery_id or required["experiment_id"] != experiment_id:
            raise CycleStepMappingError(f"row {row_number}: mapping Battery/Experiment mismatch")
        reviewed_at = required["reviewed_at"]
        try:
            parsed_reviewed_at = datetime.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise CycleStepMappingError(f"row {row_number}: reviewed_at must be ISO-8601") from exc
        if parsed_reviewed_at.utcoffset() is None:
            raise CycleStepMappingError(f"row {row_number}: reviewed_at must include a UTC offset")
        if not _SHA256_RE.fullmatch(required["parser_manifest_sha256"]):
            raise CycleStepMappingError(f"row {row_number}: parser_manifest_sha256 is invalid")
        if required["parser_manifest_sha256"].lower() != parser_manifest_sha256:
            raise CycleStepMappingError(f"row {row_number}: parser manifest changed after review")
        _raw_evidence(
            raw, required["evidence_relative_path"], required["evidence_sha256"], row_number
        )

        current_context = {
            key: required[key] for key in ("mapping_id", "reviewer", "reviewed_at", "rationale")
        }
        if context is None:
            context = current_context
        elif current_context != context:
            raise CycleStepMappingError("review metadata must be consistent across mapping rows")

        source = (
            required["electrical_asset_id"],
            _integer(row.get("cycle_index_raw"), field="cycle_index_raw", row_number=row_number),
            _integer(row.get("step_index_raw"), field="step_index_raw", row_number=row_number),
        )
        target = (
            _integer(
                row.get("canonical_cycle_index"),
                field="canonical_cycle_index",
                row_number=row_number,
            ),
            _integer(
                row.get("canonical_step_index"), field="canonical_step_index", row_number=row_number
            ),
        )
        if target[0] < 1 or target[1] < 1:
            raise CycleStepMappingError(f"row {row_number}: canonical indices must be positive")
        if source in source_keys:
            raise CycleStepMappingError(f"row {row_number}: duplicate source Cycle/Step mapping")
        if target in target_keys:
            raise CycleStepMappingError(
                f"row {row_number}: multiple source steps map to one canonical Cycle/Step"
            )
        source_cycle = (source[0], source[1])
        prior_cycle = canonical_cycle_by_source_cycle.setdefault(source_cycle, target[0])
        if prior_cycle != target[0]:
            raise CycleStepMappingError(
                f"row {row_number}: one source Cycle maps to multiple canonical Cycles"
            )
        source_keys.add(source)
        target_keys.add(target)

    cycles = pd.read_parquet(cycles_path)
    steps = pd.read_parquet(steps_path)
    cycle_keys = _source_keys(
        cycles, artifact="cycles", battery_id=battery_id, experiment_id=experiment_id
    )
    step_keys = _source_keys(
        steps, artifact="steps", battery_id=battery_id, experiment_id=experiment_id
    )
    step_cycle_keys = {(asset, cycle, None) for asset, cycle, _ in step_keys}
    if cycle_keys != step_cycle_keys:
        raise CycleStepMappingError("cycles and steps source identities do not agree")
    expected_sources = {(asset, cycle, step) for asset, cycle, step in step_keys}
    if source_keys != expected_sources:
        missing = len(expected_sources - source_keys)
        extra = len(source_keys - expected_sources)
        raise CycleStepMappingError(
            f"mapping must cover every parsed source step exactly once (missing={missing}, extra={extra})"
        )

    return {
        "status": "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED",
        "contract_version": CYCLE_STEP_MAPPING_VERSION,
        "mapping_id": context["mapping_id"] if context else None,
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "mapping_sha256": mapping_sha256,
        "parser_manifest_sha256": parser_manifest_sha256,
        "source_cycle_count": len(cycle_keys),
        "source_step_count": len(source_keys),
        "canonical_cycle_count": len({cycle for cycle, _ in target_keys}),
        "review_status": "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED",
        "mapping_application_status": "PROJECTION_AVAILABLE_NOT_INTEGRATED",
        "label_generation_authorized": False,
        "scientific_cycle_continuity": "NOT_ASSESSED",
    }


def project_canonical_cycle_step(
    frame: pd.DataFrame,
    mapping_csv: str | Path,
    *,
    raw_root: str | Path,
    processed_root: str | Path,
    battery_id: str,
    experiment_id: str,
) -> pd.DataFrame:
    """Add canonical Cycle/Step columns without changing source-local values.

    The full declaration and current parser artifacts are revalidated before
    projection. This is an in-memory identity adapter only; callers still
    need their own scientific readiness checks before creating labels.
    """
    validation = validate_cycle_step_mapping(
        mapping_csv,
        raw_root=raw_root,
        processed_root=processed_root,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    required = {
        "battery_id",
        "experiment_id",
        "electrical_asset_id",
        "cycle_index_raw",
        "step_index_raw",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CycleStepMappingError("projection frame missing columns: " + ", ".join(missing))
    if frame[list(required)].isna().any().any():
        raise CycleStepMappingError("projection frame has null source identity")
    if set(frame["battery_id"].astype(str)) != {battery_id}:
        raise CycleStepMappingError("projection frame Battery identity mismatch")
    if set(frame["experiment_id"].astype(str)) != {experiment_id}:
        raise CycleStepMappingError("projection frame Experiment identity mismatch")

    rows, mapping_sha256 = _read_mapping(Path(mapping_csv))
    if mapping_sha256 != validation["mapping_sha256"]:
        raise CycleStepMappingError("mapping CSV changed during projection")
    mapping: dict[tuple[str, int, int], tuple[int, int]] = {}
    for row_number, row in enumerate(rows, start=2):
        source = (
            _required(row, "electrical_asset_id", row_number),
            _integer(row.get("cycle_index_raw"), field="cycle_index_raw", row_number=row_number),
            _integer(row.get("step_index_raw"), field="step_index_raw", row_number=row_number),
        )
        target = (
            _integer(
                row.get("canonical_cycle_index"),
                field="canonical_cycle_index",
                row_number=row_number,
            ),
            _integer(
                row.get("canonical_step_index"),
                field="canonical_step_index",
                row_number=row_number,
            ),
        )
        mapping[source] = target

    projected = frame.copy(deep=True)
    canonical_cycles: list[int] = []
    canonical_steps: list[int] = []
    for row_number, row in enumerate(
        projected[["electrical_asset_id", "cycle_index_raw", "step_index_raw"]].itertuples(
            index=False, name=None
        ),
        start=1,
    ):
        asset_id, raw_cycle, raw_step = row
        source = (
            str(asset_id).strip(),
            _integer(raw_cycle, field="cycle_index_raw", row_number=row_number),
            _integer(raw_step, field="step_index_raw", row_number=row_number),
        )
        target = mapping.get(source)
        if target is None:
            raise CycleStepMappingError(
                f"projection row {row_number}: source Cycle/Step is not in reviewed mapping"
            )
        canonical_cycles.append(target[0])
        canonical_steps.append(target[1])
    projected["canonical_cycle_index"] = canonical_cycles
    projected["canonical_step_index"] = canonical_steps
    return projected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an explicit Cycle/Step mapping against current parser outputs. "
            "Does not apply the mapping or authorize label generation."
        )
    )
    parser.add_argument("mapping_csv", type=Path)
    parser.add_argument("--battery-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_cycle_step_mapping(
            args.mapping_csv,
            raw_root=args.raw_root,
            processed_root=args.processed_root,
            battery_id=args.battery_id,
            experiment_id=args.experiment_id,
        )
    except CycleStepMappingError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

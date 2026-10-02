"""BRW-024R intake engine — staging / detection / validation / commit.

- Detection reuses the BRW-007 ``DataAdapterRegistry`` (no route-level sniffing).
- Validation separates FORMAT_VALIDITY from SCIENTIFIC_METADATA_COMPLETENESS (§11).
- Commit is atomic-or-recoverable: manifest append + staging→raw move + asset
  registry append; repeated commit of the same session is idempotent (§14).
- Committed raw is immutable; staging cleanup never touches committed raw (§22).
- ``sampling_rate_hz`` stays UNKNOWN unless scientifically resolved; the
  ~10 s frame cadence is never promoted to waveform fs (§12).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from battery_workbench.intake.models import (
    AdapterDetectionRecord,
    AssetRole,
    ExperimentRecord,
    ImportValidationRecord,
    IntakeAssetRecord,
    IntakePolicyError,
    IntakeSession,
    utc_now_iso,
)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB per asset (§21)
MAX_ASSETS_PER_SESSION = 20
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
ELECTRICAL_SUFFIXES = {".xlsx"}
ULTRASOUND_SUFFIXES = {".txt"}
IMMUTABLE_SESSION_STATES = {"COMMITTED", "CANCELLED", "EXPIRED", "FAILED"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stored_filename(original: str, intake_asset_id: str) -> str:
    """Original filename stays metadata; the stored name is server-generated (§8)."""
    if not SAFE_FILENAME.match(original) or ".." in original or "/" in original:
        raise IntakePolicyError(f"unsafe filename rejected: {original!r}")
    suffix = Path(original).suffix.lower().lstrip(".")
    return f"{intake_asset_id}.{suffix}" if suffix else intake_asset_id


class IntakeEngine:
    """Owns staging/detection/validation/commit for one workspace."""

    def __init__(
        self,
        *,
        raw_root: Path,
        work_root: Path,
    ) -> None:
        self.raw_root = Path(raw_root)
        self.work_root = Path(work_root)
        self.staging_root = self.work_root / "staging" / "intake"
        self.registry_root = self.work_root / "intake"
        self.manifests_dir = self.raw_root / "manifests"

    # ---------- paths ----------
    def experiments_library_path(self) -> Path:
        return self.registry_root / "experiments_library.json"

    def session_path(self, session_id: str) -> Path:
        return self.registry_root / "sessions" / f"{session_id}.json"

    def staging_dir(self, session_id: str) -> Path:
        return self.staging_root / session_id

    def events_path(self) -> Path:
        return self.registry_root / "lifecycle_events.jsonl"

    # ---------- persistence ----------
    def _ensure_dirs(self) -> None:
        self.registry_root.mkdir(parents=True, exist_ok=True)
        (self.registry_root / "sessions").mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: IntakeSession) -> None:
        self._ensure_dirs()
        session.updated_at = utc_now_iso()
        self.session_path(session.session_id).write_text(
            session.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_session(self, session_id: str) -> IntakeSession:
        path = self.session_path(session_id)
        if not path.is_file():
            raise KeyError(session_id)
        return IntakeSession.model_validate_json(path.read_text(encoding="utf-8"))

    def save_experiment(self, record: ExperimentRecord) -> None:
        self._ensure_dirs()
        library = self.load_library()
        library[record.composite_id] = record.model_dump(mode="json")
        self.experiments_library_path().write_text(
            json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def load_library(self) -> dict[str, dict[str, Any]]:
        path = self.experiments_library_path()
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def load_experiment(self, battery_id: str, experiment_id: str) -> ExperimentRecord:
        record = self.load_library().get(f"{battery_id}/{experiment_id}")
        if record is None:
            raise KeyError(f"{battery_id}/{experiment_id}")
        return ExperimentRecord.model_validate(record)

    def append_event(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_dirs()
        line = json.dumps(
            {
                "event_type": event_type,
                "occurred_at": utc_now_iso(),
                "session_id": session_id,
                "detail": detail or {},
            },
            ensure_ascii=False,
        )
        with self.events_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    # ---------- experiment lifecycle ----------
    def create_experiment(
        self,
        *,
        battery_id: str,
        experiment_id: str | None,
        name: str,
        is_demo: bool = False,
        notes: str = "",
    ) -> ExperimentRecord:
        from battery_workbench.io.experiment.manifest_loader import load_experiments

        self._ensure_dirs()
        if experiment_id is None:
            # deterministic ID policy: EXP_%03d sequence per battery
            existing_ids = set(self.load_library().keys())
            experiments_csv = self.manifests_dir / "experiments.csv"
            if experiments_csv.is_file():
                existing_ids.update(
                    f"{e.battery_id}/{e.experiment_id}" for e in load_experiments(experiments_csv)
                )
            seq = 1
            while f"{battery_id}/EXP_{seq:03d}" in existing_ids:
                seq += 1
            experiment_id = f"EXP_{seq:03d}"
        composite = f"{battery_id}/{experiment_id}"
        library = self.load_library()
        if composite in library:
            raise IntakePolicyError(f"experiment already exists: {composite}")
        # also refuse identity collision with the canonical demo manifests
        experiments_csv = self.manifests_dir / "experiments.csv"
        if experiments_csv.is_file() and any(
            e.battery_id == battery_id and e.experiment_id == experiment_id
            for e in load_experiments(experiments_csv)
        ):
            raise IntakePolicyError(f"experiment already exists: {composite}")
        now = utc_now_iso()
        record = ExperimentRecord(
            battery_id=battery_id,
            experiment_id=experiment_id,
            name=name,
            status="AWAITING_DATA",
            is_demo=is_demo,
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        library[composite] = record.model_dump(mode="json")
        self.experiments_library_path().write_text(
            json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.append_event("EXPERIMENT_CREATED", detail={"composite_id": composite})
        return record

    def archive_experiment(self, battery_id: str, experiment_id: str) -> ExperimentRecord:
        record = self.load_experiment(battery_id, experiment_id)
        record.status = "ARCHIVED"
        record.updated_at = utc_now_iso()
        self.save_experiment(record)
        self.append_event("EXPERIMENT_ARCHIVED", detail={"composite_id": record.composite_id})
        return record

    # ---------- intake sessions ----------
    def create_session(self, battery_id: str, experiment_id: str) -> IntakeSession:
        self.load_experiment(battery_id, experiment_id)  # existence check
        session = IntakeSession(
            session_id=f"INTAKE::{uuid.uuid4().hex[:16]}",
            experiment_composite_id=f"{battery_id}/{experiment_id}",
            battery_id=battery_id,
            experiment_id=experiment_id,
            status="DRAFT",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        self.save_session(session)
        self.append_event("INTAKE_STARTED", session_id=session.session_id)
        return session

    def _require_mutatable(self, session: IntakeSession) -> None:
        if session.status in IMMUTABLE_SESSION_STATES:
            raise IntakePolicyError(
                f"session {session.session_id} is {session.status} and cannot be modified"
            )

    # ---------- upload ----------
    def store_asset(
        self,
        session: IntakeSession,
        *,
        role: AssetRole,
        original_filename: str,
        content: bytes,
        file_start_time: str | None = None,
        file_end_time: str | None = None,
        anchor_for_asset_id: str | None = None,
    ) -> IntakeAssetRecord:
        self._require_mutatable(session)
        for field_name, value in (
            ("file_start_time", file_start_time),
            ("file_end_time", file_end_time),
        ):
            if value:
                try:
                    datetime.fromisoformat(value)
                except ValueError as exc:
                    raise IntakePolicyError(f"invalid {field_name}: expected ISO-8601") from exc
        if len(session.assets) >= MAX_ASSETS_PER_SESSION:
            raise IntakePolicyError(f"session asset limit reached ({MAX_ASSETS_PER_SESSION})")
        if role == "EXPERIMENT_METADATA":
            if not anchor_for_asset_id:
                raise IntakePolicyError(
                    "M2K time evidence must be explicitly bound to an Ultrasound DataAsset"
                )
            target = next(
                (a for a in session.assets if a.intake_asset_id == anchor_for_asset_id), None
            )
            if target is None or target.role != "ULTRASOUND":
                raise IntakePolicyError(
                    "anchor_for_asset_id must reference an uploaded ULTRASOUND asset"
                )
            if Path(original_filename).suffix.lower() != ".xml":
                raise IntakePolicyError("M2K time evidence must be an .xml configuration file")
            if any(a.anchor_for_asset_id == anchor_for_asset_id for a in session.assets):
                raise IntakePolicyError(
                    "an M2K time evidence file is already bound to this Ultrasound DataAsset"
                )
        elif anchor_for_asset_id is not None:
            raise IntakePolicyError("anchor_for_asset_id is only valid for EXPERIMENT_METADATA")
        if len(content) > MAX_FILE_SIZE:
            raise IntakePolicyError(f"asset too large: {len(content)} bytes")
        if not content:
            raise IntakePolicyError("empty asset rejected")
        stored = safe_stored_filename(original_filename, uuid.uuid4().hex[:12])
        staging = self.staging_dir(session.session_id)
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / stored
        # guard: resolved path must stay inside staging (§21 traversal defense)
        if not target.resolve().is_relative_to(staging.resolve()):
            raise IntakePolicyError("staging path traversal rejected")
        target.write_bytes(content)
        record = IntakeAssetRecord(
            intake_asset_id=stored.split(".")[0],
            session_id=session.session_id,
            role=role,
            original_filename=original_filename,
            stored_filename=stored,
            size=len(content),
            sha256=sha256_file(target),
            received_at=utc_now_iso(),
            content_kind=Path(original_filename).suffix.lower().lstrip(".") or None,
            file_start_time=file_start_time or None,
            file_end_time=file_end_time or None,
            anchor_for_asset_id=anchor_for_asset_id,
        )
        session.assets.append(record)
        session.status = "ASSETS_RECEIVED"
        self.save_session(session)
        self.append_event(
            "ASSET_UPLOADED",
            session_id=session.session_id,
            detail={
                "intake_asset_id": record.intake_asset_id,
                "role": role,
                "sha256": record.sha256,
                "anchor_for_asset_id": record.anchor_for_asset_id,
            },
        )
        return record

    def list_assets(self, session: IntakeSession) -> list[IntakeAssetRecord]:
        return list(session.assets)

    def staged_path(self, session: IntakeSession, asset: IntakeAssetRecord) -> Path:
        return self.staging_dir(session.session_id) / asset.stored_filename

    # ---------- detection (BRW-007 reuse) ----------
    def detect(self, session: IntakeSession) -> list[AdapterDetectionRecord]:
        self._require_mutatable(session)
        if not session.assets:
            raise IntakePolicyError("no staged assets to detect")
        from battery_workbench.io.adapters.registry import build_default_adapter_registry

        registry = build_default_adapter_registry()
        detections: list[AdapterDetectionRecord] = []
        for asset in session.assets:
            path = self.staged_path(session, asset)
            suffix = path.suffix.lower()
            if asset.role == "EXPERIMENT_METADATA":
                try:
                    from battery_workbench.synchronization.m2k_evidence import (
                        read_m2k_acquisition_start,
                    )

                    parsed = read_m2k_acquisition_start(path)
                    target = next(
                        (
                            item
                            for item in session.assets
                            if item.intake_asset_id == asset.anchor_for_asset_id
                        ),
                        None,
                    )
                    if target is None or target.role != "ULTRASOUND":
                        raise IntakePolicyError(
                            "M2K evidence target must be an uploaded ULTRASOUND asset"
                        )
                    record = AdapterDetectionRecord(
                        intake_asset_id=asset.intake_asset_id,
                        state="DETECTED_UNIQUE",
                        modality=None,
                        adapter_id="M2KTimeEvidence",
                        adapter_version="0.1.0",
                        asset_role=asset.role,
                        detection_reason=(
                            "explicit M2K dateAcquis time evidence for "
                            f"{target.original_filename}: "
                            f"{parsed.anchor_datetime.isoformat()} (timezone unknown)"
                        ),
                        matched_signatures=["xml:M2kData/@dateAcquis", f"sha256:{asset.sha256}"],
                    )
                except Exception as exc:  # noqa: BLE001 — report invalid evidence at detect
                    record = AdapterDetectionRecord(
                        intake_asset_id=asset.intake_asset_id,
                        state="UNSUPPORTED",
                        adapter_id="M2KTimeEvidence",
                        asset_role=asset.role,
                        detection_reason=f"invalid M2K time evidence: {exc}",
                        matched_signatures=[f"suffix:{suffix}"],
                    )
                detections.append(record)
                continue

            matches: list[dict[str, Any]] = []
            if suffix in ELECTRICAL_SUFFIXES:
                matches.append(
                    {
                        "modality": "electrical",
                        "adapter_id": "ElectricalAdapter",
                        "adapter_version": registry.get("electrical").adapter_version,
                    }
                )
            if suffix in ULTRASOUND_SUFFIXES:
                matches.append(
                    {
                        "modality": "ultrasound",
                        "adapter_id": "UltrasoundAdapter",
                        "adapter_version": registry.get("ultrasound").adapter_version,
                    }
                )
            if len(matches) == 1:
                m = matches[0]
                record = AdapterDetectionRecord(
                    intake_asset_id=asset.intake_asset_id,
                    state="DETECTED_UNIQUE",
                    modality=m["modality"],
                    adapter_id=m["adapter_id"],
                    adapter_version=m["adapter_version"],
                    asset_role=asset.role,
                    detection_reason=f"content/signature matched {m['modality']} adapter via BRW-007 registry",
                    matched_signatures=[f"suffix:{suffix}", f"registry:{m['adapter_id']}"],
                )
            elif len(matches) > 1:
                record = AdapterDetectionRecord(
                    intake_asset_id=asset.intake_asset_id,
                    state="DETECTED_AMBIGUOUS",
                    detection_reason="multiple registry adapters matched; user must select",
                    candidates=matches,
                )
            else:
                record = AdapterDetectionRecord(
                    intake_asset_id=asset.intake_asset_id,
                    state="UNSUPPORTED",
                    detection_reason="no registered adapter matches this content",
                    matched_signatures=[f"suffix:{suffix}"],
                )
            detections.append(record)
        session.detections = detections
        ambiguous = any(d.state == "DETECTED_AMBIGUOUS" for d in detections)
        unsupported = any(d.state == "UNSUPPORTED" for d in detections)
        if ambiguous or unsupported:
            session.status = "FAILED" if unsupported else "DETECTED"
            session.failure_reason = (
                "unsupported format present"
                if unsupported
                else "ambiguous adapter match requires user confirmation"
            )
        else:
            session.status = "DETECTED"
        self.save_session(session)
        self.append_event(
            "ADAPTER_DETECTED",
            session_id=session.session_id,
            detail={"states": [d.state for d in detections]},
        )
        return detections

    # ---------- validation (§11: format vs metadata separated) ----------
    def validate(
        self,
        session: IntakeSession,
        *,
        level: Literal["STRUCTURE_ONLY", "FULL_PARSE"] = "STRUCTURE_ONLY",
    ) -> ImportValidationRecord:
        self._require_mutatable(session)
        if session.status not in ("DETECTED", "VALIDATED"):
            raise IntakePolicyError("run detect before validate")
        checks: list[dict[str, Any]] = []
        electrical_ok = True
        ultrasound_ok = True
        time_evidence_ok = True
        frames_meta: dict[str, int] = {}

        for asset in session.assets:
            detection = next(
                (d for d in session.detections if d.intake_asset_id == asset.intake_asset_id),
                None,
            )
            if detection is None or detection.state != "DETECTED_UNIQUE":
                raise IntakePolicyError(
                    f"asset {asset.intake_asset_id} has no unique adapter detection"
                )
            path = self.staged_path(session, asset)
            if asset.role == "EXPERIMENT_METADATA":
                try:
                    from battery_workbench.synchronization.m2k_evidence import (
                        read_m2k_acquisition_start,
                    )

                    parsed = read_m2k_acquisition_start(path)
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "FULL_PARSE",
                            "passed": True,
                            "detail": (
                                f"M2K dateAcquis={parsed.anchor_datetime.isoformat()} "
                                "(timezone UNKNOWN; provisional anchor evidence only)"
                            ),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — evidence parse failures block commit
                    time_evidence_ok = False
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "FULL_PARSE",
                            "passed": False,
                            "detail": f"M2K time evidence invalid: {exc}",
                        }
                    )
            elif detection.modality == "electrical":
                try:
                    from battery_workbench.io.electrical.custom_excel import (
                        read_electrical_workbook,
                    )

                    workbook = read_electrical_workbook(path)
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "FULL_PARSE" if level == "FULL_PARSE" else "STRUCTURE_ONLY",
                            "passed": True,
                            "detail": f"electrical sheets: {sorted(workbook.sheets.keys())}",
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — parse errors become validation checks
                    electrical_ok = False
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "STRUCTURE_ONLY",
                            "passed": False,
                            "detail": f"electrical parse failed: {exc}",
                        }
                    )
            elif detection.modality == "ultrasound":
                try:
                    from battery_workbench.io.ultrasound.custom_txt import (
                        inspect_ultrasound_txt,
                    )

                    inspection = inspect_ultrasound_txt(path)
                    frames_meta[asset.intake_asset_id] = inspection.frame_count
                    waveform_lengths = inspection.waveform_lengths
                    ok = len(waveform_lengths) == 1 and inspection.frame_count > 0
                    ultrasound_ok = ultrasound_ok and ok
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "STRUCTURE_ONLY",
                            "passed": ok,
                            "detail": (
                                f"ultrasound frames={inspection.frame_count} "
                                f"samples/frame={sorted(waveform_lengths)}"
                            ),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — parse errors become validation checks
                    ultrasound_ok = False
                    checks.append(
                        {
                            "dimension": "FORMAT_VALIDITY",
                            "level": "STRUCTURE_ONLY",
                            "passed": False,
                            "detail": f"ultrasound parse failed: {exc}",
                        }
                    )

        roles = {a.role for a in session.assets}
        required_roles_present = "ELECTRICAL" in roles and "ULTRASOUND" in roles
        checks.append(
            {
                "dimension": "PIPELINE_READINESS",
                "level": "STRUCTURE_ONLY",
                "passed": required_roles_present,
                "detail": f"roles={sorted(roles)} (need ELECTRICAL+ULTRASOUND for ingest pipeline)",
            }
        )
        metadata_passed = required_roles_present
        checks.append(
            {
                "dimension": "SCIENTIFIC_METADATA_COMPLETENESS",
                "level": "STRUCTURE_ONLY",
                "passed": metadata_passed,
                "detail": (
                    "sampling_rate_hz UNKNOWN — unknown stays unknown; "
                    "10s frame cadence is NOT a waveform fs"
                ),
            }
        )

        overall = electrical_ok and ultrasound_ok and time_evidence_ok and required_roles_present
        from battery_workbench.intake.models import ValidationCheck

        validation = ImportValidationRecord(
            session_id=session.session_id,
            validation_level=level,
            overall_passed=overall,
            checks=[ValidationCheck.model_validate(c) for c in checks],
            sampling_rate_hz=None,
            sampling_rate_status="UNKNOWN",
            timebase_status=(
                "PROVISIONAL"
                if any(asset.role == "EXPERIMENT_METADATA" for asset in session.assets)
                else "UNKNOWN"
            ),
        )
        session.validation = validation
        session.status = "VALIDATED" if overall else session.status
        if not overall:
            session.failure_reason = "validation failed; see checks"
        self.save_session(session)
        self.append_event(
            "VALIDATION_COMPLETED",
            session_id=session.session_id,
            detail={"overall_passed": overall},
        )
        return validation

    # ---------- commit (§13/§14: atomic-or-recoverable + idempotent) ----------
    def commit(self, session: IntakeSession) -> dict[str, Any]:
        if session.commit is not None:
            # idempotent repeated commit
            return session.commit.model_dump(mode="json")
        if session.validation is None or not session.validation.overall_passed:
            raise IntakePolicyError("session is not validated; commit blocked")
        self._require_mutatable(session)

        battery_id, experiment_id = (
            session.battery_id,
            session.experiment_id,
        )
        canonical_base = self.raw_root / "batteries" / battery_id / experiment_id
        manifest_assets: list[dict[str, str]] = []
        import_manifest: dict[str, Any] = {
            "session_id": session.session_id,
            "policy_version": session.policy_version,
            "import_policy_version": "0.1.0",
            "source_type": "INTAKE_STAGING",
            "sampling_rate_hz": None,
            "sampling_rate_status": "UNKNOWN",
            "timebase_status": "UNKNOWN",
            "assets": [],
            "time_anchor_evidence": [],
        }
        try:
            committed_asset_ids: dict[str, str] = {}
            committed_manifest_rows: dict[str, dict[str, str]] = {}
            for asset in session.assets:
                if asset.role == "EXPERIMENT_METADATA":
                    continue
                detection = next(
                    d for d in session.detections if d.intake_asset_id == asset.intake_asset_id
                )
                modality = detection.modality
                if modality is None:
                    raise IntakePolicyError(
                        f"asset {asset.original_filename} has no supported modality"
                    )
                role_dir = {"ELECTRICAL": "electrical", "ULTRASOUND": "ultrasound"}.get(
                    asset.role, "auxiliary"
                )
                dest_dir = canonical_base / role_dir
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / asset.original_filename
                if dest.exists():
                    existing_checksum = sha256_file(dest)
                    if existing_checksum != asset.sha256:
                        raise IntakePolicyError(
                            f"committed raw is immutable; checksum conflict for {dest.name}"
                        )
                    # same bytes already committed → idempotent reuse
                else:
                    shutil.move(str(self.staged_path(session, asset)), str(dest))
                asset_id = ("E" if modality == "electrical" else "U") + f"_{uuid.uuid4().hex[:8]}"
                manifest_assets.append(
                    {
                        "asset_id": asset_id,
                        "battery_id": battery_id,
                        "experiment_id": experiment_id,
                        "modality": modality,
                        "relative_path": str(dest.relative_to(self.raw_root)),
                        "file_start_time": asset.file_start_time or "",
                        "file_end_time": asset.file_end_time or "",
                        "parser_name": detection.adapter_id or "",
                        "parser_version": detection.adapter_version or "",
                        "sha256": asset.sha256,
                        "role": asset.role,
                        "original_filename": asset.original_filename,
                        "source_type": "INTAKE_STAGING",
                        "intake_session_id": session.session_id,
                        "adapter_id": detection.adapter_id or "",
                        "adapter_version": detection.adapter_version or "",
                        "time_anchor_metadata_path": "",
                    }
                )
                committed_asset_ids[asset.intake_asset_id] = asset_id
                committed_manifest_rows[asset.intake_asset_id] = manifest_assets[-1]
                import_manifest["assets"].append(
                    {
                        "asset_id": asset_id,
                        "sha256": asset.sha256,
                        "role": asset.role,
                        "adapter_id": detection.adapter_id,
                        "adapter_version": detection.adapter_version,
                    }
                )
            for asset in session.assets:
                if asset.role != "EXPERIMENT_METADATA":
                    continue
                target_asset_id = committed_asset_ids.get(asset.anchor_for_asset_id or "")
                target_row = committed_manifest_rows.get(asset.anchor_for_asset_id or "")
                if not target_asset_id or target_row is None:
                    raise IntakePolicyError(
                        "M2K time evidence binding does not resolve to a committed Ultrasound asset"
                    )
                dest_dir = canonical_base / "timebase_evidence"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / asset.stored_filename
                if dest.exists():
                    if sha256_file(dest) != asset.sha256:
                        raise IntakePolicyError(
                            f"committed time evidence is immutable; checksum conflict for {dest.name}"
                        )
                else:
                    shutil.move(str(self.staged_path(session, asset)), str(dest))
                relative_path = str(dest.relative_to(self.raw_root))
                target_row["time_anchor_metadata_path"] = relative_path
                import_manifest["time_anchor_evidence"].append(
                    {
                        "intake_asset_id": asset.intake_asset_id,
                        "ultrasound_asset_id": target_asset_id,
                        "relative_path": relative_path,
                        "sha256": asset.sha256,
                        "source_ref": "M2kData/@dateAcquis",
                    }
                )
            if import_manifest["time_anchor_evidence"]:
                import_manifest["timebase_status"] = "PROVISIONAL"
            self._append_manifest_rows(manifest_assets, battery_id=battery_id)
        except IntakePolicyError:
            session.status = "FAILED"
            session.failure_reason = "commit failed; staging preserved for recovery"
            self.save_session(session)
            raise

        manifest_checksum = hashlib.sha256(
            json.dumps(import_manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        import_manifest["manifest_checksum"] = manifest_checksum
        import_dir = self.work_root / "intake" / "import_manifests" / session.session_id
        import_dir.mkdir(parents=True, exist_ok=True)
        (import_dir / "import_manifest.json").write_text(
            json.dumps(import_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        from battery_workbench.intake.models import IntakeCommitRecord

        session.commit = IntakeCommitRecord(
            session_id=session.session_id,
            committed_at=utc_now_iso(),
            experiment_composite_id=session.experiment_composite_id,
            assets=manifest_assets,
            import_manifest_checksum=manifest_checksum,
        )
        session.status = "COMMITTED"
        self.save_session(session)

        # experiment lifecycle → READY_FOR_PIPELINE
        record = self.load_experiment(battery_id, experiment_id)
        record.status = "READY_FOR_PIPELINE"
        record.updated_at = utc_now_iso()
        self.save_experiment(record)
        self.append_event("INTAKE_COMMITTED", session_id=session.session_id)
        self._cleanup_staging(session)
        return session.commit.model_dump(mode="json")

    def _append_manifest_rows(self, assets: list[dict[str, str]], *, battery_id: str) -> None:
        """Append committed assets to the canonical manifests (Orchestrator-compatible)."""
        assets_csv = self.manifests_dir / "data_assets.csv"
        experiments_csv = self.manifests_dir / "experiments.csv"
        batteries_csv = self.manifests_dir / "batteries.csv"
        fieldnames = [
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
        if not assets_csv.exists():
            assets_csv.write_text(",".join(fieldnames) + "\n", encoding="utf-8")
        else:
            with assets_csv.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                existing_header = list(reader.fieldnames or [])
                existing_rows = list(reader)
            if "battery_id" not in existing_header:
                with assets_csv.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in existing_rows:
                        relative = Path(row.get("relative_path", "")).parts
                        inferred = (
                            relative[1] if len(relative) >= 3 and relative[0] == "batteries" else ""
                        )
                        writer.writerow({**row, "battery_id": inferred})
            elif "time_anchor_metadata_path" not in existing_header:
                migrated_header = [*existing_header, "time_anchor_metadata_path"]
                temporary = assets_csv.with_suffix(".csv.tmp")
                with temporary.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=migrated_header)
                    writer.writeheader()
                    writer.writerows(existing_rows)
                temporary.replace(assets_csv)
        existing_checksum_keys = set()
        if assets_csv.is_file():
            for line in assets_csv.read_text(encoding="utf-8").splitlines()[1:]:
                existing_checksum_keys.add(line)
        with assets_csv.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            for asset in assets:
                row = {k: asset.get(k, "") for k in fieldnames}
                line = ",".join(str(v) for v in row.values())
                if line not in existing_checksum_keys:
                    writer.writerow(row)
                    existing_checksum_keys.add(line)
        if not experiments_csv.exists():
            experiments_csv.write_text(
                "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
            )
        with experiments_csv.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not any(
            r["experiment_id"] == assets[0]["experiment_id"] and r.get("battery_id") == battery_id
            for r in rows
        ):
            with experiments_csv.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "experiment_id",
                        "battery_id",
                        "start_time",
                        "end_time",
                        "protocol",
                        "notes",
                    ],
                )
                writer.writerow(
                    {
                        "experiment_id": assets[0]["experiment_id"],
                        "battery_id": battery_id,
                        "start_time": "",
                        "end_time": "",
                        "protocol": "",
                        "notes": "created via intake",
                    }
                )
        if not batteries_csv.exists():
            batteries_csv.write_text(
                "battery_id,chemistry,nominal_capacity_ah,notes\n", encoding="utf-8"
            )
        with batteries_csv.open("r", encoding="utf-8", newline="") as handle:
            battery_rows = list(csv.DictReader(handle))
        if not any(row.get("battery_id") == battery_id for row in battery_rows):
            with batteries_csv.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["battery_id", "chemistry", "nominal_capacity_ah", "notes"],
                )
                writer.writerow(
                    {
                        "battery_id": battery_id,
                        "chemistry": "",
                        "nominal_capacity_ah": "",
                        "notes": "created via intake",
                    }
                )

    # ---------- cancel / cleanup (§22) ----------
    def cancel(self, session: IntakeSession) -> IntakeSession:
        self._require_mutatable(session)
        session.status = "CANCELLED"
        self.save_session(session)
        self._cleanup_staging(session)
        return session

    def _cleanup_staging(self, session: IntakeSession) -> None:
        staging = self.staging_dir(session.session_id)
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)

    def cleanup_expired(self, *, older_than_iso: str) -> list[str]:
        """Expired/abandoned staging cleanup; committed raw is never touched (§22)."""
        removed: list[str] = []
        if not (self.registry_root / "sessions").is_dir():
            return removed
        for path in sorted((self.registry_root / "sessions").glob("*.json")):
            session = IntakeSession.model_validate_json(path.read_text(encoding="utf-8"))
            if session.status in IMMUTABLE_SESSION_STATES:
                continue
            if session.updated_at < older_than_iso:
                session.status = "EXPIRED"
                self.save_session(session)
                self._cleanup_staging(session)
                removed.append(session.session_id)
        return removed

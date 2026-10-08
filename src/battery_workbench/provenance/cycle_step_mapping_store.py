"""Content-addressed storage for explicitly reviewed Cycle/Step sidecars."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from battery_workbench.provenance.cycle_step_mapping import (
    CycleStepMappingError,
    validate_cycle_step_mapping,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]+$")


class CycleStepMappingConflict(RuntimeError):
    """The active mapping changed since the caller last inspected it."""


class CycleStepMappingStoreError(RuntimeError):
    """The annotation sidecar path is unsafe or its history is inconsistent."""


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_ids(battery_id: str, experiment_id: str) -> None:
    for name, value in (("battery_id", battery_id), ("experiment_id", experiment_id)):
        if not _SAFE_ID_RE.fullmatch(value) or ".." in value:
            raise CycleStepMappingStoreError(f"invalid {name}")


def _ensure_child_directory(parent: Path, child: Path, *, root: Path) -> None:
    """Create one directory component without accepting symlink traversal."""
    if child.parent != parent:
        raise CycleStepMappingStoreError("annotation directory hierarchy is invalid")
    if child.is_symlink():
        raise CycleStepMappingStoreError("annotation directories must not be symlinks")
    try:
        child.mkdir(exist_ok=True)
    except OSError as exc:
        raise CycleStepMappingStoreError("could not create annotation directory") from exc
    if child.is_symlink() or not child.is_dir():
        raise CycleStepMappingStoreError("annotation path is not a regular directory")
    try:
        child.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CycleStepMappingStoreError("annotation directory escapes its root") from exc


def _revision_count(revisions_dir: Path) -> int:
    if not revisions_dir.exists():
        return 0
    if revisions_dir.is_symlink() or not revisions_dir.is_dir():
        raise CycleStepMappingStoreError("mapping revisions path is not a regular directory")
    count = 0
    for path in revisions_dir.iterdir():
        if path.suffix != ".csv":
            continue
        if path.is_symlink() or not path.is_file():
            raise CycleStepMappingStoreError("mapping revision is not a regular file")
        if not _SHA256_RE.fullmatch(path.stem) or _sha256_bytes(path.read_bytes()) != path.stem:
            raise CycleStepMappingStoreError("content-addressed mapping revision is inconsistent")
        count += 1
    return count


def _annotation_paths(
    raw_root: Path, battery_id: str, experiment_id: str
) -> tuple[Path, Path, Path]:
    _validate_ids(battery_id, experiment_id)
    raw = raw_root.resolve()
    data_root = raw.parent
    annotation_root = data_root / "annotations"
    if annotation_root.exists() and annotation_root.is_symlink():
        raise CycleStepMappingStoreError("annotations root must not be a symlink")
    resolved_annotation_root = annotation_root.resolve()
    try:
        resolved_annotation_root.relative_to(data_root)
    except ValueError as exc:
        raise CycleStepMappingStoreError("annotations root escapes the data directory") from exc
    try:
        resolved_annotation_root.relative_to(raw)
    except ValueError:
        pass
    else:
        raise CycleStepMappingStoreError(
            "annotations root must be separate from immutable raw data"
        )

    battery_dir = annotation_root / battery_id
    experiment_dir = battery_dir / experiment_id
    _ensure_child_directory(data_root, annotation_root, root=data_root)
    _ensure_child_directory(annotation_root, battery_dir, root=resolved_annotation_root)
    _ensure_child_directory(battery_dir, experiment_dir, root=resolved_annotation_root)
    resolved_experiment_dir = experiment_dir.resolve()
    try:
        resolved_experiment_dir.relative_to(resolved_annotation_root)
    except ValueError as exc:
        raise CycleStepMappingStoreError(
            "annotation experiment directory escapes its root"
        ) from exc
    if experiment_dir.is_symlink():
        raise CycleStepMappingStoreError("annotation experiment directory must not be a symlink")

    active_path = experiment_dir / "cycle-step-mapping.csv"
    revisions_dir = experiment_dir / "cycle-step-mapping.revisions"
    if active_path.is_symlink() or revisions_dir.is_symlink():
        raise CycleStepMappingStoreError("mapping sidecar paths must not be symlinks")
    if revisions_dir.exists() or revisions_dir.is_symlink():
        if revisions_dir.is_symlink() or not revisions_dir.is_dir():
            raise CycleStepMappingStoreError("mapping revisions path is not a regular directory")
    else:
        revisions_dir.mkdir()
    try:
        revisions_dir.resolve().relative_to(resolved_experiment_dir)
    except ValueError as exc:
        raise CycleStepMappingStoreError("mapping revisions directory escapes its root") from exc
    return active_path, revisions_dir, resolved_annotation_root


def _existing_revision_paths(
    raw_root: str | Path, battery_id: str, experiment_id: str
) -> tuple[Path, Path] | None:
    """Resolve annotation history for read-only access without creating paths."""
    _validate_ids(battery_id, experiment_id)
    raw = Path(raw_root).resolve()
    data_root = raw.parent
    annotation_root = data_root / "annotations"
    if annotation_root.is_symlink():
        raise CycleStepMappingStoreError("annotations root must not be a symlink")
    if not annotation_root.exists():
        return None
    resolved_root = annotation_root.resolve()
    try:
        resolved_root.relative_to(data_root)
    except ValueError:
        raise CycleStepMappingStoreError("annotations root escapes the data directory")
    try:
        resolved_root.relative_to(raw)
    except ValueError:
        pass
    else:
        raise CycleStepMappingStoreError(
            "annotations root must be separate from immutable raw data"
        )

    battery_dir = annotation_root / battery_id
    experiment_dir = battery_dir / experiment_id
    for directory, boundary in (
        (battery_dir, resolved_root),
        (experiment_dir, resolved_root),
    ):
        if directory.is_symlink():
            raise CycleStepMappingStoreError("annotation directories must not be symlinks")
        if not directory.exists():
            return None
        if not directory.is_dir():
            raise CycleStepMappingStoreError("annotation path is not a regular directory")
        try:
            directory.resolve(strict=True).relative_to(boundary)
        except (OSError, ValueError) as exc:
            raise CycleStepMappingStoreError(
                "annotation directory escapes its root"
            ) from exc

    active_path = experiment_dir / "cycle-step-mapping.csv"
    revisions_dir = experiment_dir / "cycle-step-mapping.revisions"
    if active_path.is_symlink() or revisions_dir.is_symlink():
        raise CycleStepMappingStoreError("mapping sidecar paths must not be symlinks")
    if revisions_dir.exists():
        if not revisions_dir.is_dir():
            raise CycleStepMappingStoreError("mapping revisions path is not a regular directory")
        try:
            revisions_dir.resolve(strict=True).relative_to(experiment_dir.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise CycleStepMappingStoreError(
                "mapping revisions directory escapes its root"
            ) from exc
    return active_path, revisions_dir


def list_cycle_step_mapping_revisions(
    *, raw_root: str | Path, battery_id: str, experiment_id: str
) -> list[dict[str, Any]]:
    """Return verified immutable revision metadata, newest-independent by hash."""
    paths = _existing_revision_paths(raw_root, battery_id, experiment_id)
    if paths is None:
        return []
    active_path, revisions_dir = paths
    active_digest: str | None = None
    if active_path.exists():
        if not active_path.is_file():
            raise CycleStepMappingStoreError("active mapping path is not a regular file")
        active_digest = _sha256_bytes(active_path.read_bytes())
    if not revisions_dir.exists():
        return []

    revisions: list[dict[str, Any]] = []
    for path in sorted(revisions_dir.glob("*.csv"), key=lambda item: item.stem):
        if path.is_symlink() or not path.is_file():
            raise CycleStepMappingStoreError("mapping revision is not a regular file")
        content = path.read_bytes()
        if not _SHA256_RE.fullmatch(path.stem) or _sha256_bytes(content) != path.stem:
            raise CycleStepMappingStoreError("content-addressed mapping revision is inconsistent")
        revisions.append(
            {
                "sha256": path.stem,
                "size_bytes": len(content),
                "is_active": path.stem == active_digest,
            }
        )
    return revisions


def read_cycle_step_mapping_revision(
    revision_sha256: str, *, raw_root: str | Path, battery_id: str, experiment_id: str
) -> bytes:
    """Read a revision only when its path and content-address checksum are valid."""
    if not _SHA256_RE.fullmatch(revision_sha256):
        raise CycleStepMappingError("revision_sha256 must be a lowercase SHA-256")
    paths = _existing_revision_paths(raw_root, battery_id, experiment_id)
    if paths is None:
        raise FileNotFoundError("Cycle/Step mapping revision not found")
    _, revisions_dir = paths
    revision_path = revisions_dir / f"{revision_sha256}.csv"
    if revision_path.is_symlink():
        raise CycleStepMappingStoreError("mapping revision must not be a symlink")
    if not revision_path.exists():
        raise FileNotFoundError("Cycle/Step mapping revision not found")
    if not revision_path.is_file():
        raise CycleStepMappingStoreError("mapping revision is not a regular file")
    content = revision_path.read_bytes()
    if _sha256_bytes(content) != revision_sha256:
        raise CycleStepMappingStoreError("content-addressed mapping revision is inconsistent")
    return content


def get_cycle_step_mapping_status(
    *,
    raw_root: str | Path,
    processed_root: str | Path,
    battery_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    """Inspect the active sidecar without creating annotation directories."""
    _validate_ids(battery_id, experiment_id)
    raw = Path(raw_root).resolve()
    data_root = raw.parent
    annotation_root = data_root / "annotations"
    if annotation_root.is_symlink():
        raise CycleStepMappingStoreError("annotations root must not be a symlink")
    resolved_annotation_root = annotation_root.resolve()
    try:
        resolved_annotation_root.relative_to(data_root)
    except ValueError as exc:
        raise CycleStepMappingStoreError("annotations root escapes the data directory") from exc
    experiment_dir = annotation_root / battery_id / experiment_id
    if not experiment_dir.exists():
        return {
            "status": "MISSING",
            "active_mapping_sha256": None,
            "revision_count": 0,
            "reason": None,
        }
    if experiment_dir.is_symlink():
        raise CycleStepMappingStoreError("annotation experiment directory must not be a symlink")
    resolved_experiment_dir = experiment_dir.resolve()
    try:
        resolved_experiment_dir.relative_to(resolved_annotation_root)
    except ValueError as exc:
        raise CycleStepMappingStoreError(
            "annotation experiment directory escapes its root"
        ) from exc
    active_path = experiment_dir / "cycle-step-mapping.csv"
    revisions_dir = experiment_dir / "cycle-step-mapping.revisions"
    if revisions_dir.is_symlink() or active_path.is_symlink():
        raise CycleStepMappingStoreError("mapping sidecar paths must not be symlinks")
    revision_count = _revision_count(revisions_dir)
    if not active_path.exists():
        return {
            "status": "MISSING",
            "active_mapping_sha256": None,
            "revision_count": revision_count,
            "reason": None,
        }
    if not active_path.is_file():
        raise CycleStepMappingStoreError("active mapping path is not a regular file")
    content = active_path.read_bytes()
    digest = _sha256_bytes(content)
    try:
        with tempfile.TemporaryDirectory(prefix="brw-cycle-step-status-") as temp_dir:
            candidate = Path(temp_dir) / "cycle-step-mapping.csv"
            candidate.write_bytes(content)
            validation = validate_cycle_step_mapping(
                candidate,
                raw_root=raw_root,
                processed_root=processed_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
    except CycleStepMappingError as exc:
        return {
            "status": "INVALID",
            "active_mapping_sha256": digest,
            "revision_count": revision_count,
            "reason": str(exc),
        }
    return {
        "status": "VALIDATED",
        "active_mapping_sha256": digest,
        "revision_count": revision_count,
        "mapping_id": validation["mapping_id"],
        "source_cycle_count": validation["source_cycle_count"],
        "source_step_count": validation["source_step_count"],
        "canonical_cycle_count": validation["canonical_cycle_count"],
        "review_status": validation["review_status"],
        "scientific_cycle_continuity": "NOT_ASSESSED",
    }


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    """Serialize read/check/archive/replace across API worker processes."""
    if lock_path.is_symlink():
        raise CycleStepMappingStoreError("mapping lock path must not be a symlink")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise CycleStepMappingStoreError("could not atomically save mapping sidecar") from exc


def _archive_revision(revisions_dir: Path, content: bytes, digest: str) -> None:
    revision_path = revisions_dir / f"{digest}.csv"
    if revision_path.exists():
        if revision_path.is_symlink() or _sha256_bytes(revision_path.read_bytes()) != digest:
            raise CycleStepMappingStoreError("content-addressed mapping revision is inconsistent")
        return
    _atomic_write(revision_path, content)


def save_cycle_step_mapping(
    mapping_csv: str,
    *,
    confirm_reviewed: bool,
    expected_active_sha256: str | None,
    raw_root: str | Path,
    processed_root: str | Path,
    battery_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    """Validate, archive and atomically activate a reviewed mapping revision.

    ``expected_active_sha256=None`` means the caller expects no active mapping.
    A non-null value provides optimistic concurrency for replacing an existing
    mapping. The CSV's ACCEPTED declaration remains unauthenticated.
    """
    if not confirm_reviewed:
        raise CycleStepMappingError("explicit confirm_reviewed=true is required to save a mapping")
    if expected_active_sha256 is not None and not _SHA256_RE.fullmatch(expected_active_sha256):
        raise CycleStepMappingError("expected_active_sha256 must be a lowercase SHA-256 or null")
    try:
        content = mapping_csv.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CycleStepMappingError("mapping CSV must be valid UTF-8") from exc
    digest = _sha256_bytes(content)

    def validate_content() -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="brw-cycle-step-save-") as temp_dir:
            candidate = Path(temp_dir) / "cycle-step-mapping.csv"
            candidate.write_bytes(content)
            return validate_cycle_step_mapping(
                candidate,
                raw_root=raw_root,
                processed_root=processed_root,
                battery_id=battery_id,
                experiment_id=experiment_id,
            )

    validation = validate_content()

    active_path, revisions_dir, annotation_root = _annotation_paths(
        Path(raw_root), battery_id, experiment_id
    )
    lock_path = active_path.parent / ".cycle-step-mapping.lock"
    with _exclusive_lock(lock_path):
        # Revalidate inside the lock so parser/raw inputs cannot change between
        # preflight and activation without being detected.
        validation = validate_content()
        # Fail closed on damaged history before changing the active mapping.
        _revision_count(revisions_dir)

        if active_path.is_symlink():
            raise CycleStepMappingStoreError("active mapping path must not be a symlink")
        if active_path.exists() and not active_path.is_file():
            raise CycleStepMappingStoreError("active mapping path is not a regular file")
        active_content = active_path.read_bytes() if active_path.exists() else None
        active_digest = _sha256_bytes(active_content) if active_content is not None else None
        if active_digest != expected_active_sha256:
            raise CycleStepMappingConflict(
                "active Cycle/Step mapping changed; reload before saving"
            )
        if active_digest == digest:
            _archive_revision(revisions_dir, content, digest)
            return {
                **validation,
                "save_status": "ALREADY_CURRENT",
                "previous_mapping_sha256": active_digest,
                "revision_count": _revision_count(revisions_dir),
                "active_mapping_relative_path": (
                    Path("annotations") / battery_id / experiment_id / "cycle-step-mapping.csv"
                ).as_posix(),
            }

        if active_content is not None and active_digest is not None:
            _archive_revision(revisions_dir, active_content, active_digest)
        _archive_revision(revisions_dir, content, digest)
        _atomic_write(active_path, content)
        try:
            active_path.resolve(strict=True).relative_to(annotation_root)
        except (OSError, ValueError) as exc:
            raise CycleStepMappingStoreError(
                "saved mapping sidecar escaped annotations root"
            ) from exc

    return {
        **validation,
        "save_status": "SAVED",
        "previous_mapping_sha256": active_digest,
        "revision_count": _revision_count(revisions_dir),
        "active_mapping_relative_path": (
            Path("annotations") / battery_id / experiment_id / "cycle-step-mapping.csv"
        ).as_posix(),
    }

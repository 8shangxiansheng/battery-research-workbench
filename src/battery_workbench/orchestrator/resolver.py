"""BRW-019 artifact resolver.

An existing artifact is REUSABLE only when a manifest exists, declares the
expected artifact id / identity / status / producer version, and its input
provenance matches. A directory (or file) without a valid manifest is never
enough. Manifest input paths recorded as repo-relative ``data/processed/...``
are resolved against the active processed root.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from battery_workbench.orchestrator.schemas import ArtifactRef as ArtifactRefModel


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_tree(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(path)).encode())
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def content_hash(path: Path) -> str:
    return _sha256_tree(path) if path.is_dir() else _sha256_file(path)


def _resolve_manifest_path(manifest_root: Path, raw: str) -> Path:
    """Manifest paths are repo-relative (data/processed/...).

    ``manifest_root`` here is the *processed root* (data/processed), and the
    marker-stripped suffix is joined onto it so sandboxed runs resolve inside
    their own tree.
    """
    raw_str = str(raw)
    marker = "data/processed/"
    if marker in raw_str:
        return manifest_root / raw_str.split(marker, 1)[1]
    return manifest_root / raw_str


class ArtifactIdentity(BaseModel):
    battery_id: str
    experiment_id: str


class ArtifactRequirements(BaseModel):
    artifact_type: str
    manifest_name: str
    identity: ArtifactIdentity
    output_rel_dir: str = ""  # e.g. "parameters/CELL_001/EXP_001"
    id_key: str = ""  # manifest key carrying the artifact id (empty: no id)
    status_key: str = ""  # manifest key carrying status
    acceptable_statuses: set[str] = Field(default_factory=set)
    version_key: str = ""  # manifest producer-version key
    expected_version: str = ""  # node's module version; "" = don't check
    provenance: dict[str, Any] = Field(default_factory=dict)
    extra_match: dict[str, Any] = Field(default_factory=dict)
    scan: bool = True  # whether to scan sibling dirs when no id pinned


def _manifest_matches(
    manifest: dict[str, Any],
    requirements: ArtifactRequirements,
    artifact_id: str | None,
) -> tuple[bool, str]:
    if requirements.id_key and not manifest.get(requirements.id_key):
        return False, "manifest missing artifact id key"
    if artifact_id and requirements.id_key and manifest.get(requirements.id_key) != artifact_id:
        return False, f"artifact id mismatch: {manifest.get(requirements.id_key)} != {artifact_id}"
    ident = requirements.identity
    if manifest.get("battery_id") is not None or manifest.get("experiment_id") is not None:
        for key, expected in (
            ("battery_id", ident.battery_id),
            ("experiment_id", ident.experiment_id),
        ):
            if manifest.get(key) != expected:
                return False, f"identity mismatch on {key}"
    status = ""
    if requirements.status_key:
        status = str(manifest.get(requirements.status_key, ""))
    elif manifest.get("status") is not None:
        status = str(manifest["status"])
    if (
        requirements.acceptable_statuses
        and status
        and status not in requirements.acceptable_statuses
    ):
        return False, f"status not reusable: {status or 'missing'}"
    if status == "FAILED":
        return False, "status FAILED"
    if (
        requirements.version_key
        and requirements.expected_version
        and str(manifest.get(requirements.version_key, "")) != requirements.expected_version
    ):
        return False, "producer version mismatch"
    for key, expected in requirements.extra_match.items():
        if manifest.get(key) != expected:
            return False, f"selection mismatch on {key}"
    if requirements.provenance:
        got = manifest.get("input_checksums") or {}
        prov = requirements.provenance
        expected_checks = prov.get("input_checksums") if "input_checksums" in prov else prov
        for key, expected_hash in (expected_checks or {}).items():
            if got.get(key) != expected_hash:
                return False, f"provenance mismatch on input {key!r}"
    return True, "manifest+identity+status+provenance verified"


def verify_manifest_provenance(
    manifest: dict[str, Any],
    manifest_path: Path,
    processed_root: Path | None = None,
) -> tuple[bool, str]:
    """Recompute a manifest's declared input checksums against current files."""
    current = current_input_checksums(manifest, manifest_path, processed_root=processed_root)
    declared = manifest.get("input_checksums") or {}
    for key, declared_hash in declared.items():
        if key not in current:
            continue  # input not present here (optional/external) — skip
        if not declared_hash:
            continue  # checksum not recorded at production time — cannot verify
        if current[key] != declared_hash:
            return False, f"input {key!r} changed since the artifact was produced"
    return True, "declared input checksums verified"


def find_existing_artifact(
    processed_root: Path,
    *,
    requirements: ArtifactRequirements,
    artifact_id: str | None,
    provenance: dict[str, Any] | None = None,
) -> ArtifactRefModel | None:
    """Resolve a reusable artifact ref, or None.

    ``provenance`` (optional) carries checksums of the *current* upstream
    inputs; a manifest whose input checksums differ is not reused.
    """
    root = Path(processed_root)
    req = requirements.model_copy(deep=True)
    if provenance:
        req.provenance = provenance

    from battery_workbench.orchestrator.schemas import ArtifactRef

    if artifact_id and req.output_rel_dir:
        manifest_path = root / req.output_rel_dir / artifact_id / req.manifest_name
        candidates = [(root / req.output_rel_dir / artifact_id, manifest_path)]
        if not manifest_path.is_file():
            # nested layouts (features/{b}/{e}/AS::../FS::../manifest)
            base_dir = root / req.output_rel_dir
            candidates = [
                (p.parent, p)
                for p in sorted(base_dir.rglob(req.manifest_name))
                if p.parent.name == artifact_id
            ]
    else:
        base = root / req.output_rel_dir if req.output_rel_dir else root
        candidates = []
        if req.scan:
            # directory-scoped artifacts (manifest directly in rel_dir)…
            if req.output_rel_dir and (base / req.manifest_name).is_file():
                candidates.append((base, base / req.manifest_name))
            # …and id-scoped children, including nested (one or more levels)
            candidates.extend((p.parent, p / req.manifest_name) for p in sorted(base.glob("*/")))
            if req.output_rel_dir:
                candidates.extend(
                    (p.parent, p)
                    for p in sorted(base.rglob(req.manifest_name))
                    if p.parent not in {c[0] for c in candidates}
                )

    for out_dir, manifest_path in candidates:
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        ok, reason = _manifest_matches(manifest, req, artifact_id)
        if not ok:
            continue
        return ArtifactRef(
            artifact_type=req.artifact_type,
            artifact_id=str(manifest.get(req.id_key, "")) if req.id_key else out_dir.name,
            battery_id=req.identity.battery_id,
            experiment_id=req.identity.experiment_id,
            path=str(out_dir),
            manifest_path=str(manifest_path),
            producer_version=str(manifest.get(req.version_key, "")) if req.version_key else "",
            content_hash=content_hash(out_dir),
            status=str(manifest.get(req.status_key, "")) if req.status_key else "",
            reuse_reason=reason,
        )
    return None


def current_input_checksums(
    manifest: dict[str, Any], manifest_path: Path, processed_root: Path | None = None
) -> dict[str, str]:
    """Recompute checksums of a manifest's declared input files."""
    manifest_root = processed_root if processed_root is not None else manifest_path.parent
    result: dict[str, str] = {}
    inputs = manifest.get("input_checksums") or {}
    paths = manifest.get("input_paths") or {}
    for key in inputs:
        raw = paths.get(key)
        if not raw:
            continue
        p = _resolve_manifest_path(manifest_root, raw)
        if p.is_file():
            result[key] = _sha256_file(p)
        elif p.is_dir():
            result[key] = _sha256_tree(p)
    return result

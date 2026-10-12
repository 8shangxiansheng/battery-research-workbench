from __future__ import annotations

import hashlib
import json
from pathlib import Path

from battery_workbench.provenance.parser_manifest import parser_output_integrity_reasons


def _write_parser_manifest(
    root: Path,
    modality: str,
    *,
    output_checksums: bool = True,
) -> dict[str, Path]:
    directory = root / modality / "CELL_A" / "EXP_A"
    directory.mkdir(parents=True)
    outputs = (
        {"records": "records.parquet", "cycles": "cycles.parquet", "steps": "steps.parquet"}
        if modality == "electrical"
        else {"frames": "frames.parquet", "waveforms": "waveforms.zarr"}
    )
    paths: dict[str, Path] = {}
    for key, filename in outputs.items():
        path = directory / filename
        if key == "waveforms":
            path.mkdir()
            (path / "chunk.bin").write_bytes(b"waveform")
        else:
            path.write_bytes(f"{key}-bytes".encode())
        paths[key] = path
    manifest: dict[str, object] = {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "output_files": {**outputs, "parser_manifest": "parser_manifest.json"},
    }
    if output_checksums:
        manifest["output_checksums"] = {
            key: hashlib.sha256(
                b"".join(
                    relative.as_posix().encode() + (path / relative).read_bytes()
                    for relative in sorted(
                        p.relative_to(path) for p in path.rglob("*") if p.is_file()
                    )
                )
            ).hexdigest()
            if path.is_dir()
            else hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in paths.items()
        }
    (directory / "parser_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return paths


def test_parser_outputs_are_current_when_files_and_tree_hashes_match(tmp_path: Path) -> None:
    _write_parser_manifest(tmp_path, "electrical")
    _write_parser_manifest(tmp_path, "ultrasound")

    assert parser_output_integrity_reasons(
        tmp_path, "CELL_A", "EXP_A"
    ) == {"electrical": [], "ultrasound": []}


def test_parser_output_tampering_and_legacy_manifests_fail_closed(tmp_path: Path) -> None:
    electrical = _write_parser_manifest(tmp_path, "electrical")
    ultrasound = _write_parser_manifest(tmp_path, "ultrasound")
    electrical["records"].write_bytes(b"tampered")
    (ultrasound["waveforms"] / "chunk.bin").write_bytes(b"tampered")

    reasons = parser_output_integrity_reasons(tmp_path, "CELL_A", "EXP_A")

    assert "OUTPUT_CHECKSUM_MISMATCH:records" in reasons["electrical"]
    assert "OUTPUT_CHECKSUM_MISMATCH:waveforms" in reasons["ultrasound"]


def test_legacy_parser_manifest_without_output_checksums_is_unverified(
    tmp_path: Path,
) -> None:
    _write_parser_manifest(tmp_path, "electrical", output_checksums=False)

    reasons = parser_output_integrity_reasons(tmp_path, "CELL_A", "EXP_A")

    assert "OUTPUT_CHECKSUMS_INVALID" in reasons["electrical"]


def test_canonical_parser_output_without_manifest_is_unverifiable(tmp_path: Path) -> None:
    output = tmp_path / "electrical" / "CELL_A" / "EXP_A" / "records.parquet"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"untracked output")

    reasons = parser_output_integrity_reasons(tmp_path, "CELL_A", "EXP_A")

    assert reasons == {"electrical": ["PARSER_MANIFEST_MISSING"]}


def test_parser_manifest_cannot_escape_modality_directory(tmp_path: Path) -> None:
    paths = _write_parser_manifest(tmp_path, "electrical")
    manifest_path = tmp_path / "electrical" / "CELL_A" / "EXP_A" / "parser_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_files"]["records"] = "../../../../outside.parquet"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reasons = parser_output_integrity_reasons(tmp_path, "CELL_A", "EXP_A")

    assert "OUTPUT_PATH_INVALID:records" in reasons["electrical"]
    assert paths["cycles"].is_file()

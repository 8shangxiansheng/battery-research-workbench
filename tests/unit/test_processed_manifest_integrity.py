from __future__ import annotations

import hashlib
from pathlib import Path

from battery_workbench.provenance.processed_manifest import (
    feature_waveform_store_sha256,
    verify_manifest_files,
)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: Path) -> dict:
    sync_dir = root / "synchronization" / "CELL_A" / "EXP_A"
    event_dir = root / "multimodal" / "CELL_A" / "EXP_A"
    sync_dir.mkdir(parents=True)
    event_dir.mkdir(parents=True)
    files = {
        "ultrasound_timestamped": sync_dir / "timestamped.parquet",
        "electrical_records": root / "electrical" / "CELL_A" / "EXP_A" / "records.parquet",
        "aligned": sync_dir / "aligned.parquet",
        "candidates": sync_dir / "candidates.parquet",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    return {
        "battery_id": "CELL_A",
        "experiment_id": "EXP_A",
        "input_paths": {key: str(path) for key, path in files.items() if key in {
            "ultrasound_timestamped", "electrical_records"
        }},
        "input_checksums": {key: _checksum(files[key]) for key in (
            "ultrasound_timestamped", "electrical_records"
        )},
        "output_paths": {key: str(files[key]) for key in ("aligned", "candidates")},
        "output_checksums": {key: _checksum(files[key]) for key in ("aligned", "candidates")},
    }


def test_verified_manifest_files_accept_current_inputs_and_outputs(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)

    assert verify_manifest_files(
        tmp_path,
        manifest,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        required_outputs={"aligned", "candidates"},
        required_inputs={"ultrasound_timestamped", "electrical_records"},
    ) == []


def test_modified_derived_output_is_detected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    Path(manifest["output_paths"]["aligned"]).write_bytes(b"tampered")

    reasons = verify_manifest_files(
        tmp_path,
        manifest,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        required_outputs={"aligned", "candidates"},
    )

    assert reasons == ["OUTPUT_CHECKSUM_MISMATCH:aligned"]


def test_changed_processed_input_invalidates_derived_artifact(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    Path(manifest["input_paths"]["electrical_records"]).write_bytes(b"changed")

    reasons = verify_manifest_files(
        tmp_path,
        manifest,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        required_outputs={"aligned", "candidates"},
        required_inputs={"electrical_records"},
    )

    assert reasons == ["INPUT_CHECKSUM_MISMATCH:electrical_records"]


def test_missing_legacy_checksums_and_identity_fail_closed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["battery_id"] = "CELL_OTHER"
    del manifest["output_checksums"]["candidates"]
    del manifest["input_checksums"]["electrical_records"]

    reasons = verify_manifest_files(
        tmp_path,
        manifest,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        required_outputs={"aligned", "candidates"},
        required_inputs={"electrical_records"},
    )

    assert "MANIFEST_BATTERY_ID_MISMATCH" in reasons
    assert "OUTPUT_CHECKSUM_MISSING:candidates" in reasons
    assert "INPUT_CHECKSUM_MISSING:electrical_records" in reasons


def test_paths_outside_processed_root_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    outside = tmp_path.parent / "outside.parquet"
    outside.write_bytes(b"outside")
    manifest["output_paths"]["aligned"] = str(outside)
    manifest["output_checksums"]["aligned"] = _checksum(outside)

    reasons = verify_manifest_files(
        tmp_path,
        manifest,
        battery_id="CELL_A",
        experiment_id="EXP_A",
        required_outputs={"aligned"},
    )

    assert reasons == ["OUTPUT_PATH_INVALID:aligned"]


def test_feature_waveform_tree_checksum_uses_stable_path_and_bytes(tmp_path: Path) -> None:
    store = tmp_path / "waveforms.zarr"
    nested = store / "0" / "0"
    nested.mkdir(parents=True)
    (nested / "chunk.bin").write_bytes(b"waveform bytes")
    expected = hashlib.sha256(b"0/0/chunk.bin\0waveform bytes").hexdigest()

    assert feature_waveform_store_sha256(store) == expected


def test_feature_waveform_tree_checksum_rejects_symlink_files(tmp_path: Path) -> None:
    store = tmp_path / "waveforms.zarr"
    store.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"external")
    (store / "chunk.bin").symlink_to(outside)

    assert feature_waveform_store_sha256(store) == ""

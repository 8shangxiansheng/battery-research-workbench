"""BRW-019 T08-T14: artifact resolver semantics.

Resolver contract: an artifact is REUSABLE only when a manifest exists,
declares the expected artifact/identity, has a valid status, and its input
provenance matches. A directory (or file) without a valid manifest is never
enough.
"""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.orchestrator.resolver import (
    ArtifactIdentity,
    ArtifactRequirements,
    find_existing_artifact,
)


def _write_manifest(
    root: Path,
    rel_dir: str,
    manifest_name: str,
    payload: dict,
) -> Path:
    d = root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / manifest_name
    p.write_text(json.dumps(payload) + "\n")
    return p


def _req(**overrides) -> ArtifactRequirements:
    values = {
        "artifact_type": "PARAMETER_SET",
        "manifest_name": "parameter_set_manifest.json",
        "identity": ArtifactIdentity(battery_id="CELL_001", experiment_id="EXP_001"),
        "output_rel_dir": "parameters/CELL_001/EXP_001",
        "id_key": "parameter_set_id",
    }
    values.update(overrides)
    return ArtifactRequirements(**values)


def test_t08_exact_id_resolution(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "parameters/CELL_001/EXP_001/PS::abc123",
        "parameter_set_manifest.json",
        {"parameter_set_id": "PS::abc123", "battery_id": "CELL_001", "experiment_id": "EXP_001"},
    )
    ref = find_existing_artifact(
        tmp_path,
        requirements=_req(),
        artifact_id="PS::abc123",
    )
    assert ref is not None
    assert ref.artifact_id == "PS::abc123"


def test_t09_manifest_required(tmp_path: Path) -> None:
    # artifact dir exists but no manifest → not resolvable
    (tmp_path / "parameters/CELL_001/EXP_001/PS::abc123").mkdir(parents=True)
    assert find_existing_artifact(tmp_path, requirements=_req(), artifact_id="PS::abc123") is None


def test_t10_directory_only_not_enough(tmp_path: Path) -> None:
    # manifest present but missing the artifact id key → not reusable
    _write_manifest(
        tmp_path,
        "parameters/CELL_001/EXP_001/PS::abc123",
        "parameter_set_manifest.json",
        {"battery_id": "CELL_001", "experiment_id": "EXP_001"},
    )
    assert find_existing_artifact(tmp_path, requirements=_req(), artifact_id="PS::abc123") is None


def test_t11_wrong_battery_experiment_rejected(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "parameters/CELL_002/EXP_001/PS::abc123",
        "parameter_set_manifest.json",
        {"parameter_set_id": "PS::abc123", "battery_id": "CELL_002", "experiment_id": "EXP_001"},
    )
    assert find_existing_artifact(tmp_path, requirements=_req(), artifact_id="PS::abc123") is None


def test_t12_provenance_mismatch_rejected(tmp_path: Path) -> None:
    """Input checksums must match the requirements' provenance fingerprint."""
    _write_manifest(
        tmp_path,
        "parameters/CELL_001/EXP_001/PS::abc123",
        "parameter_set_manifest.json",
        {
            "parameter_set_id": "PS::abc123",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "input_checksums": {"events": "different"},
        },
    )
    req = _req(provenance={"input_checksums": {"events": "expected"}})
    assert find_existing_artifact(tmp_path, requirements=req, artifact_id="PS::abc123") is None
    # matching provenance reuses
    _write_manifest(
        tmp_path,
        "parameters/CELL_001/EXP_001/PS::def456",
        "parameter_set_manifest.json",
        {
            "parameter_set_id": "PS::def456",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "input_checksums": {"events": "expected"},
        },
    )
    ref = find_existing_artifact(tmp_path, requirements=req, artifact_id="PS::def456")
    assert ref is not None and ref.artifact_id == "PS::def456"


def test_t13_valid_artifact_reused(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "datasets/CELL_001/EXP_001/SOC/DS::ok1",
        "dataset_manifest.json",
        {
            "dataset_id": "DS::ok1",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dataset_status": "READY_WITH_LIMITATIONS",
            "selected_features": ["amplitude_a_u"],
            "target_name": "soc_reference_percent",
        },
    )
    ref = find_existing_artifact(
        tmp_path,
        requirements=_req(
            artifact_type="DATASET",
            manifest_name="dataset_manifest.json",
            output_rel_dir="datasets/CELL_001/EXP_001/SOC",
            id_key="dataset_id",
            status_key="dataset_status",
            acceptable_statuses={"READY_WITH_LIMITATIONS", "READY"},
            extra_match={
                "selected_features": ["amplitude_a_u"],
                "target_name": "soc_reference_percent",
            },
        ),
        artifact_id="DS::ok1",
    )
    assert ref is not None and ref.status == "READY_WITH_LIMITATIONS"


def test_t14_incompatible_artifact_not_reused(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "datasets/CELL_001/EXP_001/SOC/DS::nope",
        "dataset_manifest.json",
        {
            "dataset_id": "DS::nope",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "dataset_status": "READY_WITH_LIMITATIONS",
            "selected_features": ["waveform_rms_a_u"],  # different selection
            "target_name": "soc_reference_percent",
        },
    )
    ref = find_existing_artifact(
        tmp_path,
        requirements=_req(
            artifact_type="DATASET",
            manifest_name="dataset_manifest.json",
            output_rel_dir="datasets/CELL_001/EXP_001/SOC",
            id_key="dataset_id",
            status_key="dataset_status",
            acceptable_statuses={"READY_WITH_LIMITATIONS", "READY"},
            extra_match={"selected_features": ["amplitude_a_u"]},
        ),
        artifact_id="DS::nope",
    )
    assert ref is None


def test_failing_status_not_reused(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "parameters/CELL_001/EXP_001/PS::bad",
        "parameter_set_manifest.json",
        {
            "parameter_set_id": "PS::bad",
            "battery_id": "CELL_001",
            "experiment_id": "EXP_001",
            "status": "FAILED",
        },
    )
    assert find_existing_artifact(tmp_path, requirements=_req(), artifact_id="PS::bad") is None

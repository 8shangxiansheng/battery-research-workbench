from __future__ import annotations

import json

import pandas as pd
import pytest

from battery_workbench.orchestrator.nodes import ParameterSetNode
from battery_workbench.orchestrator.schemas import AnalysisPlan
from battery_workbench.parameters.persistence import write_parameter_payload
from battery_workbench.parameters.schemas import ParameterConfig
from battery_workbench.provenance.processed_manifest import content_sha256


def _write_pinned_parameter_set(root, parameter_set_id: str) -> None:
    battery_id, experiment_id = "CELL_001", "EXP_001"
    events = root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    cycles = root / "electrical" / battery_id / experiment_id / "cycles.parquet"
    waveform_store = root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    label_manifest = root / "labels" / battery_id / experiment_id / "label_manifest.json"
    for path in (events, cycles, label_manifest):
        path.parent.mkdir(parents=True, exist_ok=True)
    waveform_store.mkdir(parents=True)
    events.write_bytes(b"events")
    cycles.write_bytes(b"cycles")
    label_manifest.write_text("{}\n", encoding="utf-8")
    (waveform_store / "chunk.bin").write_bytes(b"waveform")
    records = pd.DataFrame(
        [
            {
                "canonical_name": "ultrasound.sampling_rate_hz",
                "value": "50.0",
                "unit": "MHz",
                "source_type": "SourceType.USER_SUPPLIED",
                "source_reference": "user-confirmed:fixture",
                "evidence_note": "explicit prior verified record",
                "verification_status": "VERIFIED",
            }
        ]
    )
    write_parameter_payload(
        records=records,
        effective={"ultrasound.sampling_rate_hz": {"value": 50_000_000, "status": "RESOLVED"}},
        capability_matrix={},
        battery_id=battery_id,
        experiment_id=experiment_id,
        parameter_set_id=parameter_set_id,
        input_paths={
            "measurement_events": events,
            "cycles": cycles,
            "waveform_store": waveform_store,
            "label_manifest": label_manifest,
        },
        config=ParameterConfig(),
        output_root=root,
    )


def test_stale_parameter_set_preserves_pinned_user_supplied_records(tmp_path) -> None:
    parameter_set_id = "PS::KNOWN"
    _write_pinned_parameter_set(tmp_path, parameter_set_id)

    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={"parameter_set_id": parameter_set_id},
    )
    overrides = ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)

    assert overrides == {
        "ultrasound.sampling_rate_hz": {
            "value": 50.0,
            "unit": "MHz",
            "source_reference": "user-confirmed:fixture",
            "evidence_note": "explicit prior verified record",
            "verification_status": "VERIFIED",
        }
    }


def test_tampered_pinned_parameter_records_cannot_restore_user_values(tmp_path) -> None:
    parameter_set_id = "PS::KNOWN"
    _write_pinned_parameter_set(tmp_path, parameter_set_id)
    records_path = (
        tmp_path
        / "parameters"
        / "CELL_001"
        / "EXP_001"
        / parameter_set_id
        / "parameter_records.parquet"
    )
    records_path.write_bytes(b"tampered")
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={"parameter_set_id": parameter_set_id},
    )

    with pytest.raises(ValueError, match="cannot recover user parameters without verified"):
        ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)


def test_legacy_manifest_can_restore_only_checksum_verified_pinned_records(tmp_path) -> None:
    parameter_set_id = "PS::LEGACY"
    _write_pinned_parameter_set(tmp_path, parameter_set_id)
    parameter_dir = tmp_path / "parameters" / "CELL_001" / "EXP_001" / parameter_set_id
    records_path = parameter_dir / "parameter_records.parquet"
    manifest_path = parameter_dir / "parameter_set_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["input_paths"] = {}
    manifest["input_checksums"] = {}
    manifest["output_paths"] = {
        "records": "data/processed/parameters/CELL_001/EXP_001/"
        f"{parameter_set_id}/parameter_records.parquet"
    }
    manifest["output_checksums"] = {"records": content_sha256(records_path)}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={"parameter_set_id": parameter_set_id},
    )

    overrides = ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)

    assert overrides["ultrasound.sampling_rate_hz"]["value"] == 50.0
    assert overrides["ultrasound.sampling_rate_hz"]["verification_status"] == "VERIFIED"


def test_parameter_record_path_escape_is_not_eligible_for_recovery(tmp_path) -> None:
    parameter_set_id = "PS::ESCAPE"
    _write_pinned_parameter_set(tmp_path, parameter_set_id)
    parameter_dir = tmp_path / "parameters" / "CELL_001" / "EXP_001" / parameter_set_id
    manifest_path = parameter_dir / "parameter_set_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_paths"]["records"] = "../../outside/parameter_records.parquet"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={"parameter_set_id": parameter_set_id},
    )

    with pytest.raises(ValueError, match="RECORDS_PATH_INVALID"):
        ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)


def test_legacy_manifest_without_records_checksum_requires_reentry(tmp_path) -> None:
    parameter_set_id = "PS::LEGACY"
    _write_pinned_parameter_set(tmp_path, parameter_set_id)
    manifest_path = (
        tmp_path
        / "parameters"
        / "CELL_001"
        / "EXP_001"
        / parameter_set_id
        / "parameter_set_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_checksums"] = {}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={"parameter_set_id": parameter_set_id},
    )

    with pytest.raises(ValueError, match="RECORDS_CHECKSUM_MISSING_OR_INVALID"):
        ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)


def test_explicit_parameter_overrides_take_precedence_over_pinned_history(tmp_path) -> None:
    parameter_dir = tmp_path / "parameters" / "CELL_001" / "EXP_001" / "PS::KNOWN"
    parameter_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "canonical_name": "ultrasound.sampling_rate_hz",
                "value": "50.0",
                "unit": "MHz",
                "source_type": "SourceType.USER_SUPPLIED",
                "source_reference": "old",
                "evidence_note": "old",
                "verification_status": "VERIFIED",
            }
        ]
    ).to_parquet(parameter_dir / "parameter_records.parquet", index=False)
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project={"battery_id": "CELL_001", "experiment_id": "EXP_001"},
        parameters={
            "parameter_set_id": "PS::KNOWN",
            "user_overrides": {
                "ultrasound.sampling_rate_hz": {
                    "value": 48.0,
                    "unit": "MHz",
                    "verification_status": "UNVERIFIED",
                }
            },
        },
    )

    overrides = ParameterSetNode()._user_overrides(plan, processed_root=tmp_path)

    assert overrides["ultrasound.sampling_rate_hz"]["value"] == 48.0
    assert overrides["ultrasound.sampling_rate_hz"]["verification_status"] == "UNVERIFIED"

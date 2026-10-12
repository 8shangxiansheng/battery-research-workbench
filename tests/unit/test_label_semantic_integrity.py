from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.api.errors import APIError
from battery_workbench.api.integrity import assert_processed_artifact_integrity


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_semantically_invalid_label(root: Path) -> Path:
    battery_id, experiment_id = "CELL_A", "EXP_A"
    paths = {
        "measurement_events": root / "multimodal/CELL_A/EXP_A/measurement_events.parquet",
        "records": root / "electrical/CELL_A/EXP_A/records.parquet",
        "cycles": root / "electrical/CELL_A/EXP_A/cycles.parquet",
        "steps": root / "electrical/CELL_A/EXP_A/steps.parquet",
        "ultrasound_manifest": root / "ultrasound/CELL_A/EXP_A/parser_manifest.json",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": [battery_id],
            "experiment_id": [experiment_id],
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["1"],
            "voltage_v": [3.8],
        }
    ).to_parquet(paths["measurement_events"], index=False)
    pd.DataFrame(
        {
            "electrical_asset_id": ["EA1"],
            "source_row_index": [1],
            "voltage_v": [3.7],
        }
    ).to_parquet(paths["records"], index=False)
    for name in ("cycles", "steps"):
        pd.DataFrame({"battery_id": [battery_id], "experiment_id": [experiment_id]}).to_parquet(
            paths[name], index=False
        )
    paths["ultrasound_manifest"].write_text("{}", encoding="utf-8")

    labels_dir = root / "labels/CELL_A/EXP_A"
    labels_dir.mkdir(parents=True, exist_ok=True)
    event_labels = labels_dir / "event_labels.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"], "soc_reference_percent": [50.0]}
    ).to_parquet(event_labels, index=False)
    manifest = {
        "label_engine_name": "reference_label_engine",
        "label_engine_version": "0.3.0",
        "label_definition_version": "0.3.0",
        "label_set_id": "LB::semantic-integrity",
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "input_paths": {key: str(path) for key, path in paths.items()},
        "input_checksums": {key: _sha256(path) for key, path in paths.items()},
        "output_paths": {"event_labels": str(event_labels)},
        "output_checksums": {"event_labels": _sha256(event_labels)},
    }
    manifest_path = labels_dir / "label_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_api_integrity_rejects_fresh_checksummed_but_semantically_invalid_label(
    tmp_path: Path,
) -> None:
    manifest_path = _write_semantically_invalid_label(tmp_path)

    with pytest.raises(APIError) as error:
        assert_processed_artifact_integrity(
            tmp_path,
            manifest_path,
            battery_id="CELL_A",
            experiment_id="EXP_A",
            required_outputs={"event_labels"},
            required_inputs={"measurement_events", "records", "cycles", "steps"},
            required_manifest_fields={"label_set_id"},
        )

    assert "LABEL_INPUT_SEMANTICS_INVALID" in error.value.details["integrity_reasons"][0]


def test_api_integrity_converts_checksummed_corrupt_parquet_to_integrity_error(
    tmp_path: Path,
) -> None:
    manifest_path = _write_semantically_invalid_label(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events_path = Path(manifest["input_paths"]["measurement_events"])
    events_path.write_bytes(b"not a parquet file")
    manifest["input_checksums"]["measurement_events"] = _sha256(events_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(APIError) as error:
        assert_processed_artifact_integrity(
            tmp_path,
            manifest_path,
            battery_id="CELL_A",
            experiment_id="EXP_A",
            required_outputs={"event_labels"},
            required_inputs={"measurement_events", "records", "cycles", "steps"},
            required_manifest_fields={"label_set_id"},
        )

    assert "LABEL_INPUT_SEMANTICS_INVALID" in error.value.details["integrity_reasons"][0]


def test_api_integrity_rejects_legacy_reference_label_version(tmp_path: Path) -> None:
    manifest_path = _write_semantically_invalid_label(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["label_engine_version"] = "0.2.0"
    manifest["label_definition_version"] = "0.2.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(APIError) as error:
        assert_processed_artifact_integrity(
            tmp_path,
            manifest_path,
            battery_id="CELL_A",
            experiment_id="EXP_A",
            required_outputs={"event_labels"},
            required_inputs={"measurement_events", "records", "cycles", "steps"},
            required_manifest_fields={"label_set_id"},
        )

    assert "LABEL_ENGINE_VERSION_UNSUPPORTED" in error.value.details["integrity_reasons"]
    assert "LABEL_DEFINITION_VERSION_UNSUPPORTED" in error.value.details["integrity_reasons"]

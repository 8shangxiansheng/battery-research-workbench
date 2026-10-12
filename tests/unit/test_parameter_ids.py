from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from battery_workbench.orchestrator.nodes import ParameterSetNode
from battery_workbench.orchestrator.schemas import AnalysisPlan, PlanProject
from battery_workbench.parameters.schemas import ParameterConfig
from battery_workbench.parameters.service import build_parameter_set


def _config() -> ParameterConfig:
    return ParameterConfig()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


import hashlib


def _inputs(tmp_path: Path) -> dict[str, Path]:
    events = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "battery_id": ["CELL_X"], "experiment_id": ["EXP_X"]}
    ).to_parquet(events, index=False)
    cycles = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_X"],
            "experiment_id": ["EXP_X"],
            "cycle_index_raw": [1],
            "discharge_capacity_ah": [11.0441],
        }
    ).to_parquet(cycles, index=False)
    zarr_path = tmp_path / "waveforms.zarr"
    import zarr

    g = zarr.open_group(str(zarr_path), mode="w")
    arr = g.create_array("U001/waveform", data=__import__("numpy").zeros((4, 1250), dtype="int32"))
    arr.attrs["sampling_rate_hz"] = None
    label_manifest = tmp_path / "label_manifest.json"
    label_manifest.write_text(
        json.dumps(
            {
                "battery_id": "CELL_X",
                "experiment_id": "EXP_X",
                "soh_reference_source": "BASELINE_CYCLE",
                "soh_reference_cycle": 1,
                "soh_reference_capacity_ah": 11.0441,
                "reference_scope": "WITHIN_EXPERIMENT_BASELINE",
            }
        ),
        encoding="utf-8",
    )
    return {
        "measurement_events_path": events,
        "cycles_path": cycles,
        "waveform_store_path": zarr_path,
        "label_manifest_path": label_manifest,
    }


def test_deterministic_id_t49(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    r1 = build_parameter_set(output_root=tmp_path / "a", config=_config(), **inputs)
    r2 = build_parameter_set(output_root=tmp_path / "b", config=_config(), **inputs)
    assert r1.parameter_set_id == r2.parameter_set_id
    assert r1.parameter_set_id.startswith("PS::")


def test_value_change_changes_id_t50(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    r1 = build_parameter_set(output_root=tmp_path / "a", config=_config(), **inputs)
    user_overrides = {"ultrasound.sampling_rate_hz": {"value": 1e8, "unit": "Hz"}}
    r2 = build_parameter_set(
        output_root=tmp_path / "b", config=_config(), user_overrides=user_overrides, **inputs
    )
    assert r1.parameter_set_id != r2.parameter_set_id


def test_unit_equivalent_identity_t51(tmp_path: Path) -> None:
    """T51: 100 MHz and 1e8 Hz produce the identical parameter_set_id."""
    inputs = _inputs(tmp_path)
    r_hz = build_parameter_set(
        output_root=tmp_path / "a",
        config=_config(),
        user_overrides={"ultrasound.sampling_rate_hz": {"value": 1e8, "unit": "Hz"}},
        **inputs,
    )
    r_mhz = build_parameter_set(
        output_root=tmp_path / "b",
        config=_config(),
        user_overrides={"ultrasound.sampling_rate_hz": {"value": 100.0, "unit": "MHz"}},
        **inputs,
    )
    assert r_hz.parameter_set_id == r_mhz.parameter_set_id


def test_verification_change_changes_id_t52(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    r_un = build_parameter_set(
        output_root=tmp_path / "a",
        config=_config(),
        user_overrides={"ultrasound.sampling_rate_hz": {"value": 1e8, "unit": "Hz"}},
        **inputs,
    )
    r_ver = build_parameter_set(
        output_root=tmp_path / "b",
        config=_config(),
        user_overrides={
            "ultrasound.sampling_rate_hz": {
                "value": 1e8,
                "unit": "Hz",
                "verification_status": "VERIFIED",
            }
        },
        **inputs,
    )
    assert r_un.parameter_set_id != r_ver.parameter_set_id


def test_policy_version_changes_id_t54(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    r1 = build_parameter_set(output_root=tmp_path / "a", config=_config(), **inputs)
    r2 = build_parameter_set(
        output_root=tmp_path / "b",
        config=ParameterConfig(resolution_policy_version="0.2.0"),
        **inputs,
    )
    assert r1.parameter_set_id != r2.parameter_set_id


def test_evidence_tracked_t53(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    records = pd.read_parquet(report.artifacts["records"])
    # auto-read acquisition window carries provenance evidence.
    row = records[records["canonical_name"] == "ultrasound.acquisition_window_samples"]
    assert not row.empty
    assert row["source_reference"].iloc[0] != ""


def test_records_parquet_t55(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    assert Path(report.artifacts["records"]).exists()


def test_effective_json_t56(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    payload = json.loads(Path(report.artifacts["effective_parameters"]).read_text(encoding="utf-8"))
    assert "ultrasound.sampling_rate_hz" in payload
    entry = payload["ultrasound.sampling_rate_hz"]
    for key in (
        "value",
        "unit",
        "status",
        "source_type",
        "verification_status",
        "resolution_reason",
        "shadowed_records",
    ):
        assert key in entry


def test_manifest_checksum_t57(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    manifest = json.loads(Path(report.artifacts["manifest"]).read_text(encoding="utf-8"))
    assert "parameter_set_id" in manifest
    assert set(manifest["output_checksums"]) == {
        "records",
        "effective_parameters",
        "capability_matrix",
    }
    assert all(manifest["output_checksums"].values())
    assert len(manifest["input_checksums"]["waveform_store"]) == 64


def test_parameter_set_cache_rejects_output_and_waveform_changes(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    battery_id, experiment_id = "CELL_X", "EXP_X"
    events = root / "multimodal" / battery_id / experiment_id / "measurement_events.parquet"
    events.parent.mkdir(parents=True)
    pd.DataFrame(
        {"measurement_event_id": ["ME::1"], "battery_id": [battery_id], "experiment_id": [experiment_id]}
    ).to_parquet(events, index=False)
    cycles = root / "electrical" / battery_id / experiment_id / "cycles.parquet"
    cycles.parent.mkdir(parents=True)
    pd.DataFrame({"cycle_index_raw": [1], "discharge_capacity_ah": [11.0]}).to_parquet(
        cycles, index=False
    )
    waveform_store = root / "ultrasound" / battery_id / experiment_id / "waveforms.zarr"
    waveform_store.parent.mkdir(parents=True)
    import numpy as np
    import zarr

    group = zarr.open_group(str(waveform_store), mode="w")
    group.create_array("US001/waveform", data=np.zeros((2, 16), dtype="int16"))
    label_manifest = root / "labels" / battery_id / experiment_id / "label_manifest.json"
    label_manifest.parent.mkdir(parents=True)
    label_manifest.write_text("{}\n", encoding="utf-8")
    report = build_parameter_set(
        output_root=root,
        config=_config(),
        measurement_events_path=events,
        cycles_path=cycles,
        waveform_store_path=waveform_store,
        label_manifest_path=label_manifest,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )
    plan = AnalysisPlan(
        profile="SCIENTIFIC_ANALYSIS",
        project=PlanProject(battery_id=battery_id, experiment_id=experiment_id),
        parameters={"parameter_set_id": report.parameter_set_id},
    )
    node = ParameterSetNode()
    intact, reason = node.resolve_existing_output(plan, {}, root)
    assert intact is not None, reason

    effective = Path(report.artifacts["effective_parameters"])
    effective_bytes = effective.read_bytes()
    effective.write_text("{}\n", encoding="utf-8")
    tampered, reason = node.resolve_existing_output(plan, {}, root)
    assert tampered is None
    assert "OUTPUT_CHECKSUM_MISMATCH:effective_parameters" in reason

    # Restore the output bytes, then prove chunk-level waveform changes stale the set.
    effective.write_bytes(effective_bytes)
    group = zarr.open_group(str(waveform_store), mode="a")
    waveform = group["US001/waveform"]
    waveform[0, 0] = 1
    stale, reason = node.resolve_existing_output(plan, {}, root)
    assert stale is None
    assert "waveform_store' changed since the artifact was produced" in reason


def test_capability_matrix_t58(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    matrix = json.loads(Path(report.artifacts["capability_matrix"]).read_text(encoding="utf-8"))
    for cap in (
        "sample_time_conversion",
        "raw_tof",
        "corrected_tof",
        "wave_speed",
        "capacity_based_soc",
        "capacity_based_soh",
        "retrospective_soc",
    ):
        assert cap in matrix


def test_report_t59(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    report = build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    assert Path(report.artifacts["report_json"]).exists()
    assert Path(report.artifacts["report_html"]).exists()


def test_input_immutable_t60(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    before = {k: _sha256(v) for k, v in inputs.items() if v.suffix != ".zarr"}
    build_parameter_set(output_root=tmp_path, config=_config(), **inputs)
    after = {k: _sha256(v) for k, v in inputs.items() if v.suffix != ".zarr"}
    assert before == after

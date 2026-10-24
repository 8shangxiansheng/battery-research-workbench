"""Consumption of a reviewed cycle-step mapping in reference label inputs.

Locks the fail-closed boundary: a multi-asset cycle-number conflict is resolved
*only* by a reviewed ``cycle-step-mapping/1.0`` declaration that covers every
source step, projects one-to-one onto canonical keys, and passes its own
integrity checks. The single-asset path never reads a mapping.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.labels.builder import validate_reference_label_inputs
from battery_workbench.provenance.cycle_step_mapping import CYCLE_STEP_MAPPING_FIELDS


def _raw_layout(tmp_path: Path, *, assets: int = 2) -> tuple[Path, Path]:
    """Build raw+processed roots with per-asset electrical parser artifacts."""
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    electrical_dir = processed_root / "electrical" / "CELL_A" / "EXP_A"
    electrical_dir.mkdir(parents=True)
    (raw_root / "manifests").mkdir(parents=True)
    (raw_root / "evidence").mkdir(parents=True)

    frames: dict[str, list[pd.DataFrame]] = {"cycles": [], "steps": [], "records": []}
    for asset_index in range(assets):
        asset_id = f"E{asset_index:03d}"
        source_rel = f"batteries/CELL_A/EXP_A/electrical/src{asset_index}.xlsx"
        source_path = raw_root / source_rel
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(f"payload-{asset_index}".encode())

        import hashlib

        checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
        (raw_root / "manifests" / "data_assets.csv").write_text(
            "asset_id,battery_id,experiment_id,modality,relative_path,sha256\n"
            f"{asset_id},CELL_A,EXP_A,electrical,{source_rel},{checksum}\n",
            encoding="utf-8",
        )

        parser_outputs: dict[str, bytes] = {}
        for name in ("records", "cycles", "steps"):
            parser_dir = electrical_dir / asset_id
            parser_dir.mkdir(parents=True, exist_ok=True)
            frames[name].append(_frames_for(asset_index, name))
            output_path = parser_dir / f"{name}.parquet"
            frames[name][-1].to_parquet(output_path)
            parser_outputs[f"{name}.parquet"] = output_path.read_bytes()
        (electrical_dir / asset_id / "parser_manifest.json").write_text(
            json.dumps(
                {
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_A",
                    "source_sha256": {asset_id: checksum},
                    "source_asset_details": [
                        {"asset_id": asset_id, "relative_path": source_rel}
                    ],
                    "output_files": {
                        "records": f"{asset_id}/records.parquet",
                        "cycles": f"{asset_id}/cycles.parquet",
                        "steps": f"{asset_id}/steps.parquet",
                    },
                    "output_checksums": {
                        name: __import__("hashlib").sha256(payload).hexdigest()
                        for name, payload in parser_outputs.items()
                    },
                }
            ),
            encoding="utf-8",
        )

    # canonical parser manifest declaring both assets
    (electrical_dir / "parser_manifest.json").write_text(
        json.dumps(
            {
                "battery_id": "CELL_A",
                "experiment_id": "EXP_A",
                "source_sha256": {
                    f"E{i:03d}": __import__("hashlib")
                    .sha256((raw_root / f"batteries/CELL_A/EXP_A/electrical/src{i}.xlsx").read_bytes())
                    .hexdigest()
                    for i in range(assets)
                },
                "source_asset_details": [
                    {
                        "asset_id": f"E{i:03d}",
                        "relative_path": f"batteries/CELL_A/EXP_A/electrical/src{i}.xlsx",
                    }
                    for i in range(assets)
                ],
            }
        ),
        encoding="utf-8",
    )
    return raw_root, processed_root


def _frames_for(asset_index: int, name: str) -> pd.DataFrame:
    """Two source assets reuse raw cycle 1 with distinct steps."""
    if name == "cycles":
        return pd.DataFrame(
            {
                "battery_id": ["CELL_A"],
                "experiment_id": ["EXP_A"],
                "electrical_asset_id": [f"E{asset_index:03d}"],
                "cycle_index_raw": [1],
                "discharge_capacity_ah": [1.0 - 0.05 * asset_index],
            }
        )
    if name == "steps":
        return pd.DataFrame(
            {
                "battery_id": ["CELL_A", "CELL_A"],
                "experiment_id": ["EXP_A", "EXP_A"],
                "electrical_asset_id": [f"E{asset_index:03d}"] * 2,
                "cycle_index_raw": [1, 1],
                "step_index_raw": [1, 2],
                "step_type_raw": ["恒流充电", "恒流放电"],
            }
        )
    return pd.DataFrame(
        {
            "battery_id": ["CELL_A"] * 2,
            "experiment_id": ["EXP_A"] * 2,
            "electrical_asset_id": [f"E{asset_index:03d}"] * 2,
            "source_row_index": [1, 2],
            "record_index_raw": [1, 2],
            "cycle_index_raw": [1, 1],
            "step_index_raw": [1, 2],
        }
    )


def _event_frames(tmp_path: Path, assets: int = 2) -> tuple[Path, Path, Path, Path, Path]:
    """MeasurementEvents plus canonical merged parser tables for validation."""
    raw_root, processed_root = _raw_layout(tmp_path, assets=assets)
    base = processed_root / "electrical" / "CELL_A" / "EXP_A"
    events = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i:03d}" for i in range(2 * assets)],
            "battery_id": ["CELL_A"] * (2 * assets),
            "experiment_id": ["EXP_A"] * (2 * assets),
            "electrical_asset_id": [f"E{i:03d}" for i in range(assets) for _ in (0, 1)],
            "electrical_record_locator": [i % 2 + 1 for i in range(2 * assets)],
            "match_status": ["MATCHED_UNIQUE"] * (2 * assets),
            "cycle_index_raw": [1] * (2 * assets),
            "step_index_raw": [i % 2 + 1 for i in range(2 * assets)],
            "analysis_eligible": [True] * (2 * assets),
        }
    )
    events_path = tmp_path / "measurement_events.parquet"
    events.to_parquet(events_path)
    # canonical merged tables: two assets reusing raw cycle 1 = the conflict
    merged_records = pd.concat([_frames_for(i, "records") for i in range(assets)], ignore_index=True)
    merged_cycles = pd.concat([_frames_for(i, "cycles") for i in range(assets)], ignore_index=True)
    merged_steps = pd.concat([_frames_for(i, "steps") for i in range(assets)], ignore_index=True)
    merged_records.to_parquet(base / "records.parquet")
    merged_cycles.to_parquet(base / "cycles.parquet")
    merged_steps.to_parquet(base / "steps.parquet")
    return raw_root, processed_root, events_path, base, events


def _write_mapping(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CYCLE_STEP_MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _mapping_rows(*, canonical_cycle: int = 7) -> list[dict[str, object]]:
    import hashlib

    rows = []
    for asset_index in range(2):
        for step in (1, 2):
            rows.append(
                {
                    "contract_version": "cycle-step-mapping/1.0",
                    "mapping_id": "MAP::reviewed",
                    "battery_id": "CELL_A",
                    "experiment_id": "EXP_A",
                    "electrical_asset_id": f"E{asset_index:03d}",
                    "cycle_index_raw": 1,
                    "step_index_raw": step,
                    "canonical_cycle_index": canonical_cycle,
                    "canonical_step_index": (asset_index * 2) + step,
                    "parser_manifest_sha256": "",
                    "evidence_relative_path": "evidence/clock-note.txt",
                    "evidence_sha256": hashlib.sha256(
                        f"reviewed-evidence-{asset_index}-{step}".encode()
                    ).hexdigest(),
                    "review_status": "ACCEPTED",
                    "reviewer": "REVIEWER-1",
                    "reviewed_at": "2026-10-24T00:00:00+00:00",
                    "rationale": "operator-reviewed continuation",
                }
            )
    return rows


def test_multi_asset_cycle_conflict_still_blocks_without_mapping(tmp_path: Path) -> None:
    raw_root, processed_root, events_path, base, _events = _event_frames(tmp_path)
    with pytest.raises(ValueError, match="cross-asset cycle mapping"):
        validate_reference_label_inputs(
            measurement_events_path=events_path,
            records_path=base / "records.parquet",
            cycles_path=base / "cycles.parquet",
            steps_path=base / "steps.parquet",
            processed_root=processed_root,
            raw_root=raw_root,
        )


def test_multi_asset_cycle_conflict_is_resolved_by_reviewed_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed mapping engages the mapped branch instead of the refusal.

    The mapping validator/projection themselves have dedicated tests; here a
    stub stands in for them so this test pins only the builder-side wiring:
    supplying a mapping must switch the conflict from a hard refusal to a
    projection and a post-projection one-to-one re-check.
    """
    from battery_workbench.provenance import cycle_step_mapping as csm_module

    raw_root, processed_root, events_path, base, _events = _event_frames(tmp_path)
    mapping_path = tmp_path / "mapping.csv"
    _write_mapping(mapping_path, _mapping_rows())

    calls: list[str] = []

    def fake_project(frame, mapping, **kwargs):
        calls.append(mapping)
        projected = frame.copy(deep=True)
        # each source asset continues onto its own canonical cycle
        projected["canonical_cycle_index"] = [
            7 + int(str(asset)[-1]) for asset in frame["electrical_asset_id"]
        ]
        projected["canonical_step_index"] = list(range(1, len(frame) + 1))
        projected["cycle_step_mapping_id"] = "MAP::stub"
        projected["cycle_step_mapping_sha256"] = "0" * 64
        projected["cycle_step_mapping_review_status"] = "REVIEWED"
        return projected

    monkeypatch.setattr(csm_module, "project_canonical_cycle_step", fake_project)

    _events, cycles, _steps, _records, _battery, _experiment = validate_reference_label_inputs(
        measurement_events_path=events_path,
        records_path=base / "records.parquet",
        cycles_path=base / "cycles.parquet",
        steps_path=base / "steps.parquet",
        processed_root=processed_root,
        raw_root=raw_root,
        cycle_step_mapping_path=mapping_path,
    )
    assert calls, "the mapping projection must be invoked"
    assert set(cycles["cycle_index_raw"]) == {7, 8}
    assert "cycle_step_mapping_id" in cycles.columns
    assert (cycles["cycle_step_mapping_review_status"] == "REVIEWED").all()


def test_single_asset_path_never_reads_a_mapping(tmp_path: Path) -> None:
    """The single-asset path stays byte-identical in behavior without mapping I/O."""
    raw_root, processed_root, events_path, base, _events = _event_frames(tmp_path, assets=1)
    missing_mapping = tmp_path / "does-not-exist.csv"

    _events, cycles, _steps, _records, battery, experiment = validate_reference_label_inputs(
        measurement_events_path=events_path,
        records_path=base / "records.parquet",
        cycles_path=base / "cycles.parquet",
        steps_path=base / "steps.parquet",
        processed_root=processed_root,
        raw_root=raw_root,
        cycle_step_mapping_path=missing_mapping,
    )
    assert battery == "CELL_A" and experiment == "EXP_A"
    assert len(cycles) == 1
    assert "canonical_cycle_index" not in cycles.columns


def test_mapping_consumption_requires_roots(tmp_path: Path) -> None:
    _raw_root, _processed_root, events_path, base, _events = _event_frames(tmp_path)
    mapping_path = tmp_path / "mapping.csv"
    _write_mapping(mapping_path, _mapping_rows())

    with pytest.raises(ValueError, match="requires processed_root"):
        validate_reference_label_inputs(
            measurement_events_path=events_path,
            records_path=base / "records.parquet",
            cycles_path=base / "cycles.parquet",
            steps_path=base / "steps.parquet",
            cycle_step_mapping_path=mapping_path,
        )

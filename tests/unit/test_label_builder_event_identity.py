from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.labels.builder import (
    _validate_source_cycle_identity,
    build_reference_labels,
    validate_reference_label_inputs,
)


@pytest.mark.parametrize(
    "event_ids",
    [
        ["ME::CELL_A::EXP_A::U1::0", "ME::CELL_A::EXP_A::U1::0"],
        ["ME::CELL_A::EXP_A::U1::0", " ME::CELL_A::EXP_A::U1::1"],
        ["ME::CELL_A::EXP_A::U1::0", None],
        [1, 2],
    ],
)
def test_label_builder_rejects_invalid_event_identity_before_derivation(
    tmp_path: Path, event_ids: list[object]
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame({"measurement_event_id": event_ids}).to_parquet(events_path, index=False)

    with pytest.raises(ValueError, match="measurement_event_id"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=tmp_path / "records-must-not-be-read.parquet",
            cycles_path=tmp_path / "cycles-must-not-be-read.parquet",
            steps_path=tmp_path / "steps-must-not-be-read.parquet",
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


@pytest.mark.parametrize(
    ("event_batteries", "event_experiments", "expected_identity"),
    [
        (["CELL_A", "CELL_B"], ["EXP_A", "EXP_A"], ("CELL_A", "EXP_A")),
        (["CELL_A", "CELL_A"], ["EXP_A", "EXP_B"], ("CELL_A", "EXP_A")),
        (["CELL_B"], ["EXP_A"], ("CELL_A", "EXP_A")),
    ],
)
def test_label_builder_rejects_event_identity_mismatch_before_reading_electrical_inputs(
    tmp_path: Path,
    event_batteries: list[str],
    event_experiments: list[str],
    expected_identity: tuple[str, str],
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": [
                f"ME::{b}::{e}::U1::{i}"
                for i, (b, e) in enumerate(zip(event_batteries, event_experiments, strict=True))
            ],
            "battery_id": event_batteries,
            "experiment_id": event_experiments,
        }
    ).to_parquet(events_path, index=False)

    with pytest.raises(ValueError, match="identity"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=tmp_path / "records-must-not-be-read.parquet",
            cycles_path=tmp_path / "cycles-must-not-be-read.parquet",
            steps_path=tmp_path / "steps-must-not-be-read.parquet",
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
            expected_battery_id=expected_identity[0],
            expected_experiment_id=expected_identity[1],
        )


@pytest.mark.parametrize(
    ("cycle_batteries", "cycle_experiments", "step_batteries", "step_experiments"),
    [
        (["CELL_B"], ["EXP_A"], ["CELL_A"], ["EXP_A"]),
        (["CELL_A"], ["EXP_A"], ["CELL_A"], ["EXP_B"]),
        (["CELL_A", "CELL_B"], ["EXP_A", "EXP_A"], ["CELL_A"], ["EXP_A"]),
        (["CELL_A"], ["EXP_A"], ["CELL_A", "CELL_B"], ["EXP_A", "EXP_A"]),
    ],
)
def test_label_builder_rejects_mismatched_electrical_entity_rows(
    tmp_path: Path,
    cycle_batteries: list[str],
    cycle_experiments: list[str],
    step_batteries: list[str],
    step_experiments: list[str],
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "event_order_index": [0],
        }
    ).to_parquet(events_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": cycle_batteries,
            "experiment_id": cycle_experiments,
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": step_batteries,
            "experiment_id": step_experiments,
        }
    ).to_parquet(steps_path, index=False)

    with pytest.raises(ValueError, match="identity"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=tmp_path / "records.parquet",
            cycles_path=cycles_path,
            steps_path=steps_path,
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


def test_label_builder_rejects_event_electrical_values_not_matching_record_locator(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "event_order_index": [0],
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["7"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
            "step_type": ["恒流放电"],
            "discharge_capacity_ah": [1.0],
            "charge_capacity_ah": [0.0],
            "current_a": [-1.0],
            "voltage_v": [3.8],
        }
    ).to_parquet(events_path, index=False)
    records_path = tmp_path / "records.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "electrical_asset_id": ["EA1"],
            "source_row_index": [7],
            "voltage_v": [3.7],
        }
    ).to_parquet(records_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "charge_capacity_ah": [1.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
            "step_type_raw": ["恒流放电"],
            "charge_capacity_ah": [0.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(steps_path, index=False)

    with pytest.raises(ValueError, match="electrical.*mismatch"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=records_path,
            cycles_path=cycles_path,
            steps_path=steps_path,
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


def test_label_builder_rejects_non_unique_event_with_selected_locator(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "match_status": ["MATCHED_AMBIGUOUS"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["7"],
        }
    ).to_parquet(events_path, index=False)
    with pytest.raises(ValueError, match="non-unique event carries a locator"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=tmp_path / "records.parquet",
            cycles_path=tmp_path / "cycles.parquet",
            steps_path=tmp_path / "steps.parquet",
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


@pytest.mark.parametrize(
    "event_payload",
    [
        {
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
        },
        {
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": [None],
        },
    ],
)
def test_label_builder_rejects_incomplete_selected_record_contract(
    tmp_path: Path, event_payload: dict[str, list[object]]
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            **event_payload,
        }
    ).to_parquet(events_path, index=False)
    with pytest.raises(ValueError, match="electrical identity mismatch"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=tmp_path / "records.parquet",
            cycles_path=tmp_path / "cycles.parquet",
            steps_path=tmp_path / "steps.parquet",
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


def test_label_builder_rejects_records_missing_event_source_value_column(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["7"],
            "voltage_v": [3.7],
        }
    ).to_parquet(events_path, index=False)
    records_path = tmp_path / "records.parquet"
    pd.DataFrame(
        {
            "electrical_asset_id": ["EA1"],
            "source_row_index": [7],
        }
    ).to_parquet(records_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "charge_capacity_ah": [1.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
            "step_type_raw": ["恒流放电"],
            "charge_capacity_ah": [0.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(steps_path, index=False)
    with pytest.raises(ValueError, match="missing source value columns: voltage_v"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=records_path,
            cycles_path=cycles_path,
            steps_path=steps_path,
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


def test_label_builder_rejects_event_value_when_record_column_is_absent(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "match_status": ["MATCHED_UNIQUE"],
            "electrical_asset_id": ["EA1"],
            "electrical_record_locator": ["7"],
            "voltage_v": [3.7],
        }
    ).to_parquet(events_path, index=False)
    records_path = tmp_path / "records.parquet"
    pd.DataFrame(
        {
            "electrical_asset_id": ["EA1"],
            "source_row_index": [7],
        }
    ).to_parquet(records_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "charge_capacity_ah": [1.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
            "step_type_raw": ["恒流放电"],
            "charge_capacity_ah": [0.0],
            "discharge_capacity_ah": [1.0],
        }
    ).to_parquet(steps_path, index=False)
    with pytest.raises(ValueError, match="missing source value columns: voltage_v"):
        build_reference_labels(
            measurement_events_path=events_path,
            records_path=records_path,
            cycles_path=cycles_path,
            steps_path=steps_path,
            ultrasound_manifest_path=tmp_path / "ultrasound-manifest.json",
            output_root=tmp_path / "processed",
        )


def test_cycle_identity_guard_rejects_reused_raw_cycle_across_electrical_assets() -> None:
    cycles = pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 1],
        }
    )
    steps = pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 1],
            "step_index_raw": [1, 1],
        }
    )

    with pytest.raises(ValueError, match="cycle identity.*electrical assets"):
        _validate_source_cycle_identity(cycles, steps)


def test_cycle_identity_guard_allows_distinct_raw_cycles_across_electrical_assets() -> None:
    cycles = pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 2],
        }
    )
    steps = pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 2],
            "step_index_raw": [1, 1],
        }
    )

    _validate_source_cycle_identity(cycles, steps)


def test_reference_label_input_validation_rejects_cross_asset_cycle_collision(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
        }
    ).to_parquet(events_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 1],
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A", "CELL_A"],
            "experiment_id": ["EXP_A", "EXP_A"],
            "electrical_asset_id": ["EA1", "EA2"],
            "cycle_index_raw": [1, 1],
        }
    ).to_parquet(steps_path, index=False)
    records_path = tmp_path / "records.parquet"
    pd.DataFrame().to_parquet(records_path, index=False)

    with pytest.raises(ValueError, match="cycle identity.*electrical assets"):
        validate_reference_label_inputs(
            measurement_events_path=events_path,
            records_path=records_path,
            cycles_path=cycles_path,
            steps_path=steps_path,
        )


def test_reference_label_input_validation_rejects_missing_asset_cycle_identity(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "measurement_events.parquet"
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
        }
    ).to_parquet(events_path, index=False)
    cycles_path = tmp_path / "cycles.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
        }
    ).to_parquet(cycles_path, index=False)
    steps_path = tmp_path / "steps.parquet"
    pd.DataFrame(
        {
            "battery_id": ["CELL_A"],
            "experiment_id": ["EXP_A"],
            "cycle_index_raw": [1],
            "step_index_raw": [1],
        }
    ).to_parquet(steps_path, index=False)
    records_path = tmp_path / "records.parquet"
    pd.DataFrame(
        {
            "electrical_asset_id": ["EA1", "EA2"],
            "record_index_raw": [1, 1],
        }
    ).to_parquet(records_path, index=False)

    with pytest.raises(ValueError, match="electrical_asset_id.*cycle identity"):
        validate_reference_label_inputs(
            measurement_events_path=events_path,
            records_path=records_path,
            cycles_path=cycles_path,
            steps_path=steps_path,
        )

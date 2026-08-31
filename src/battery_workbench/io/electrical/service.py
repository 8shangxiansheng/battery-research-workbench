from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment
from battery_workbench.io.electrical.column_mapping import (
    CYCLE_COLUMN_MAPPING,
    RECORD_COLUMN_MAPPING,
    REQUIRED_COLUMNS,
    STEP_COLUMN_MAPPING,
)
from battery_workbench.io.electrical.custom_excel import (
    RawSheetData,
    read_electrical_workbook,
)
from battery_workbench.io.electrical.schemas import (
    ElectricalAssetParseResult,
    ElectricalExperimentParseResult,
    ElectricalOutputManifest,
)
from battery_workbench.io.electrical.validation import (
    ElectricalValidationError,
    is_fully_blank,
    validate_non_decreasing_timestamps,
    validate_required_columns,
    validate_required_sheets,
    validate_required_values,
    validation_context,
)
from battery_workbench.storage.parquet import write_parquet_verified

INTEGER_FIELDS = {
    "record_index_raw",
    "cycle_index_raw",
    "step_index_raw",
    "step_sequence_raw",
    "step_boundary_raw",
}
STRING_FIELDS = {"step_type_raw", "module_switch_raw"}
TIMESTAMP_FIELDS = {"timestamp", "start_timestamp", "end_timestamp"}
DURATION_FIELDS = {"elapsed_time_s", "step_time_s"}
PROVENANCE_COLUMNS = [
    "battery_id",
    "experiment_id",
    "electrical_asset_id",
    "source_file",
    "source_sheet",
    "source_row_index",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration_to_seconds(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, time):
        return float(value.hour * 3600 + value.minute * 60 + value.second) + (
            value.microsecond / 1_000_000
        )
    try:
        return float(pd.to_timedelta(str(value)).total_seconds())
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid duration {value!r}") from error


def _convert_value(value: Any, canonical: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if canonical in TIMESTAMP_FIELDS:
        try:
            return pd.Timestamp(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid timestamp {value!r}") from error
    if canonical in DURATION_FIELDS:
        return _duration_to_seconds(value)
    if canonical in INTEGER_FIELDS:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid integer {value!r}") from error
        if not numeric.is_integer():
            raise ValueError(f"invalid integer {value!r}")
        return int(numeric)
    if canonical in STRING_FIELDS:
        return str(value)
    if canonical.endswith("_raw"):
        return value
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid numeric value {value!r}") from error


def _provenance(
    *, battery_id: str, asset: DataAsset, source_file: Path, sheet: str, source_row_index: int
) -> dict[str, Any]:
    return {
        "battery_id": battery_id,
        "experiment_id": asset.experiment_id,
        "electrical_asset_id": asset.asset_id,
        "source_file": asset.relative_path.as_posix(),
        "source_sheet": sheet,
        "source_row_index": source_row_index,
    }


def _normalize_sheet(
    sheet: RawSheetData,
    mapping: dict[str, str],
    required: set[str],
    *,
    battery_id: str,
    asset: DataAsset,
    source_file: Path,
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    validate_required_columns(sheet, required, asset_id=asset.asset_id, source_file=source_file)
    active_mapping = {header: mapping[header] for header in sheet.headers if header in mapping}
    normalized: list[dict[str, Any]] = []
    ignored_blank_rows = 0
    non_tabular_warnings: list[str] = []
    for raw_row in sheet.rows:
        if is_fully_blank(raw_row.values.values()):
            ignored_blank_rows += 1
            continue
        required_values = [raw_row.values[column] for column in required]
        if is_fully_blank(required_values):
            populated = sorted(
                column for column, value in raw_row.values.items() if not is_fully_blank([value])
            )
            non_tabular_warnings.append(
                f"asset_id={asset.asset_id} sheet={sheet.name}: ignored non-tabular "
                f"row {raw_row.source_row_index} with values in columns {populated}"
            )
            continue
        validate_required_values(
            raw_row.values,
            required,
            asset_id=asset.asset_id,
            source_file=source_file,
            sheet=sheet.name,
            source_row_index=raw_row.source_row_index,
        )
        row = _provenance(
            battery_id=battery_id,
            asset=asset,
            source_file=source_file,
            sheet=sheet.name,
            source_row_index=raw_row.source_row_index,
        )
        for source_column, canonical in active_mapping.items():
            try:
                row[canonical] = _convert_value(raw_row.values[source_column], canonical)
            except ValueError as error:
                context = validation_context(
                    asset_id=asset.asset_id,
                    source_file=source_file,
                    sheet=sheet.name,
                    column=source_column,
                    source_row_index=raw_row.source_row_index,
                )
                raise ElectricalValidationError(f"{context}: {error}") from error
        normalized.append(row)

    frame = pd.DataFrame(normalized)
    if frame.empty:
        context = validation_context(
            asset_id=asset.asset_id, source_file=source_file, sheet=sheet.name
        )
        raise ElectricalValidationError(f"{context}: sheet has no data rows")
    for column in INTEGER_FIELDS & set(frame.columns):
        frame[column] = frame[column].astype("Int64")
    for column in TIMESTAMP_FIELDS & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column]).astype("datetime64[ns]")

    warnings: list[str] = []
    if ignored_blank_rows:
        noun = "row" if ignored_blank_rows == 1 else "rows"
        warnings.append(
            f"asset_id={asset.asset_id} sheet={sheet.name}: "
            f"ignored {ignored_blank_rows} fully blank {noun}"
        )
    warnings.extend(non_tabular_warnings)
    return frame, active_mapping, warnings


def _normalize_aux_sheet(
    sheet: RawSheetData,
    *,
    channel_prefix: str,
    channel_column: str,
    value_column: str,
    battery_id: str,
    asset: DataAsset,
    source_file: Path,
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    required = {"数据序号", "绝对时间"}
    validate_required_columns(sheet, required, asset_id=asset.asset_id, source_file=source_file)
    channels = [header for header in sheet.headers if header.startswith(channel_prefix)]
    if not channels:
        context = validation_context(
            asset_id=asset.asset_id, source_file=source_file, sheet=sheet.name
        )
        raise ElectricalValidationError(f"{context}: no {channel_prefix} auxiliary channels found")

    rows: list[dict[str, Any]] = []
    ignored_blank_rows = 0
    for raw_row in sheet.rows:
        if is_fully_blank(raw_row.values.values()):
            ignored_blank_rows += 1
            continue
        validate_required_values(
            raw_row.values,
            required | set(channels),
            asset_id=asset.asset_id,
            source_file=source_file,
            sheet=sheet.name,
            source_row_index=raw_row.source_row_index,
        )
        try:
            timestamp = _convert_value(raw_row.values["绝对时间"], "timestamp")
            record_index = _convert_value(raw_row.values["数据序号"], "record_index_raw")
            for channel in channels:
                row = _provenance(
                    battery_id=battery_id,
                    asset=asset,
                    source_file=source_file,
                    sheet=sheet.name,
                    source_row_index=raw_row.source_row_index,
                )
                row.update(
                    {
                        "record_index_raw": record_index,
                        "timestamp": timestamp,
                        channel_column: channel,
                        value_column: float(raw_row.values[channel]),
                    }
                )
                rows.append(row)
        except (TypeError, ValueError) as error:
            context = validation_context(
                asset_id=asset.asset_id,
                source_file=source_file,
                sheet=sheet.name,
                source_row_index=raw_row.source_row_index,
            )
            raise ElectricalValidationError(f"{context}: {error}") from error

    frame = pd.DataFrame(rows)
    frame["record_index_raw"] = frame["record_index_raw"].astype("Int64")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"]).astype("datetime64[ns]")
    mapping = {"数据序号": "record_index_raw", "绝对时间": "timestamp"}
    mapping.update({channel: value_column for channel in channels})
    warnings: list[str] = []
    if ignored_blank_rows:
        noun = "row" if ignored_blank_rows == 1 else "rows"
        warnings.append(
            f"asset_id={asset.asset_id} sheet={sheet.name}: "
            f"ignored {ignored_blank_rows} fully blank {noun}"
        )
    return frame, mapping, warnings


def _validate_asset_consistency(result: ElectricalAssetParseResult) -> None:
    record_cycles = set(result.records["cycle_index_raw"].dropna().astype(int))
    cycle_cycles = set(result.cycles["cycle_index_raw"].dropna().astype(int))
    if record_cycles != cycle_cycles:
        raise ElectricalValidationError(
            f"asset_id={result.asset.asset_id} file={result.source_path}: "
            f"record/cycle IDs differ record={sorted(record_cycles)} cycle={sorted(cycle_cycles)}"
        )
    record_pairs = set(
        zip(
            result.records["cycle_index_raw"].astype(int),
            result.records["step_index_raw"].astype(int),
            strict=True,
        )
    )
    step_pairs = set(
        zip(
            result.steps["cycle_index_raw"].astype(int),
            result.steps["step_index_raw"].astype(int),
            strict=True,
        )
    )
    if not record_pairs <= step_pairs:
        missing = sorted(record_pairs - step_pairs)
        raise ElectricalValidationError(
            f"asset_id={result.asset.asset_id} file={result.source_path}: "
            f"record Cycle/Step pairs missing from step sheet: {missing}"
        )


def parse_electrical_asset(
    asset: DataAsset, raw_root: str | Path, *, battery_id: str
) -> ElectricalAssetParseResult:
    """Parse one manifest-identified Electrical XLSX DataAsset."""
    if asset.modality != "electrical":
        raise ElectricalValidationError(
            f"asset_id={asset.asset_id}: expected modality=electrical, got {asset.modality}"
        )
    source_path = Path(raw_root) / asset.relative_path
    if not source_path.is_file():
        raise ElectricalValidationError(
            f"asset_id={asset.asset_id} file={source_path}: source XLSX does not exist"
        )
    if source_path.suffix.lower() != ".xlsx":
        raise ElectricalValidationError(
            f"asset_id={asset.asset_id} file={source_path}: expected .xlsx source"
        )

    source_hash_before = _sha256(source_path)
    workbook = read_electrical_workbook(source_path)
    validate_required_sheets(workbook, asset_id=asset.asset_id, source_file=source_path)

    warnings: list[str] = []
    mappings: dict[str, dict[str, str]] = {}
    records, mappings["record"], sheet_warnings = _normalize_sheet(
        workbook.sheets["record"],
        RECORD_COLUMN_MAPPING,
        REQUIRED_COLUMNS["record"],
        battery_id=battery_id,
        asset=asset,
        source_file=source_path,
    )
    warnings.extend(sheet_warnings)
    cycles, mappings["cycle"], sheet_warnings = _normalize_sheet(
        workbook.sheets["cycle"],
        CYCLE_COLUMN_MAPPING,
        REQUIRED_COLUMNS["cycle"],
        battery_id=battery_id,
        asset=asset,
        source_file=source_path,
    )
    warnings.extend(sheet_warnings)
    steps, mappings["step"], sheet_warnings = _normalize_sheet(
        workbook.sheets["step"],
        STEP_COLUMN_MAPPING,
        REQUIRED_COLUMNS["step"],
        battery_id=battery_id,
        asset=asset,
        source_file=source_path,
    )
    warnings.extend(sheet_warnings)

    validate_non_decreasing_timestamps(
        records["timestamp"],
        asset_id=asset.asset_id,
        source_file=source_path,
        sheet="record",
    )
    duplicate_count = int(records["timestamp"].duplicated().sum())
    if duplicate_count:
        warnings.append(
            f"asset_id={asset.asset_id} sheet=record: "
            f"found {duplicate_count} duplicate timestamps; rows were preserved"
        )

    aux_temperature: pd.DataFrame | None = None
    if "auxTemp" in workbook.sheets:
        aux_temperature, mappings["auxTemp"], sheet_warnings = _normalize_aux_sheet(
            workbook.sheets["auxTemp"],
            channel_prefix="T",
            channel_column="temperature_channel",
            value_column="temperature_c",
            battery_id=battery_id,
            asset=asset,
            source_file=source_path,
        )
        warnings.extend(sheet_warnings)
        validate_non_decreasing_timestamps(
            aux_temperature["timestamp"],
            asset_id=asset.asset_id,
            source_file=source_path,
            sheet="auxTemp",
        )

    aux_voltage: pd.DataFrame | None = None
    if "auxVol" in workbook.sheets:
        aux_voltage, mappings["auxVol"], sheet_warnings = _normalize_aux_sheet(
            workbook.sheets["auxVol"],
            channel_prefix="V",
            channel_column="voltage_channel",
            value_column="voltage_v",
            battery_id=battery_id,
            asset=asset,
            source_file=source_path,
        )
        warnings.extend(sheet_warnings)
        validate_non_decreasing_timestamps(
            aux_voltage["timestamp"],
            asset_id=asset.asset_id,
            source_file=source_path,
            sheet="auxVol",
        )

    source_hash_after = _sha256(source_path)
    if source_hash_after != source_hash_before:
        raise ElectricalValidationError(
            f"asset_id={asset.asset_id} file={source_path}: source SHA256 changed during parse"
        )

    result = ElectricalAssetParseResult(
        battery_id=battery_id,
        asset=asset,
        source_path=source_path,
        source_sha256=source_hash_before,
        sheets_found={name: sheet.info for name, sheet in workbook.sheets.items()},
        column_mappings=mappings,
        records=records,
        cycles=cycles,
        steps=steps,
        aux_temperature=aux_temperature,
        aux_voltage=aux_voltage,
        warnings=warnings,
    )
    _validate_asset_consistency(result)
    return result


def _concat(frames: Iterable[pd.DataFrame | None]) -> pd.DataFrame | None:
    present = [frame for frame in frames if frame is not None]
    if not present:
        return None
    return pd.concat(present, ignore_index=True, sort=False)


def _sorted(frame: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame | None:
    if frame is None:
        return None
    available = [column for column in columns if column in frame.columns]
    return frame.sort_values(available, kind="stable").reset_index(drop=True)


def _overlap_warnings(results: list[ElectricalAssetParseResult]) -> list[str]:
    ranges = sorted(
        (
            result.records["timestamp"].min(),
            result.records["timestamp"].max(),
            result.asset.asset_id,
        )
        for result in results
    )
    warnings: list[str] = []
    previous_end: pd.Timestamp | None = None
    previous_asset: str | None = None
    for start, end, asset_id in ranges:
        if previous_end is not None and start <= previous_end:
            warnings.append(
                f"Electrical asset timestamp overlap: {previous_asset} ends at "
                f"{previous_end.isoformat()} while {asset_id} starts at {start.isoformat()}; "
                "all rows were preserved"
            )
        if previous_end is None or end > previous_end:
            previous_end = end
            previous_asset = asset_id
    return warnings


def parse_electrical_experiment(
    experiment: Experiment,
    assets: list[DataAsset],
    raw_root: str | Path,
) -> ElectricalExperimentParseResult:
    """Parse and combine all Electrical DataAssets declared for one Experiment."""
    if not assets:
        raise ElectricalValidationError(
            f"experiment_id={experiment.experiment_id}: no Electrical DataAssets supplied"
        )
    for asset in assets:
        if asset.experiment_id != experiment.experiment_id:
            raise ElectricalValidationError(
                f"asset_id={asset.asset_id}: belongs to experiment_id={asset.experiment_id}, "
                f"expected {experiment.experiment_id}"
            )
    asset_results = [
        parse_electrical_asset(asset, raw_root, battery_id=experiment.battery_id)
        for asset in assets
    ]
    records = _sorted(
        _concat(result.records for result in asset_results),
        ["timestamp", "electrical_asset_id", "source_row_index"],
    )
    cycles = _sorted(
        _concat(result.cycles for result in asset_results),
        ["start_timestamp", "electrical_asset_id", "source_row_index"],
    )
    steps = _sorted(
        _concat(result.steps for result in asset_results),
        ["start_timestamp", "electrical_asset_id", "source_row_index"],
    )
    if records is None or cycles is None or steps is None:
        raise ElectricalValidationError(
            f"experiment_id={experiment.experiment_id}: required parsed table missing"
        )
    warnings = [warning for result in asset_results for warning in result.warnings]
    warnings.extend(_overlap_warnings(asset_results))
    return ElectricalExperimentParseResult(
        experiment=experiment,
        assets=list(assets),
        asset_results=asset_results,
        records=records,
        cycles=cycles,
        steps=steps,
        aux_temperature=_sorted(
            _concat(result.aux_temperature for result in asset_results),
            ["timestamp", "electrical_asset_id", "source_row_index", "temperature_channel"],
        ),
        aux_voltage=_sorted(
            _concat(result.aux_voltage for result in asset_results),
            ["timestamp", "electrical_asset_id", "source_row_index", "voltage_channel"],
        ),
        warnings=warnings,
    )


def _json_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def write_electrical_experiment(
    result: ElectricalExperimentParseResult, output_root: str | Path
) -> ElectricalOutputManifest:
    """Write canonical Parquet tables and a provenance-rich parser manifest."""
    output_dir = Path(output_root) / result.battery_id / result.experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[pd.DataFrame | None, str]] = {
        "records": (result.records, "records.parquet"),
        "cycles": (result.cycles, "cycles.parquet"),
        "steps": (result.steps, "steps.parquet"),
        "aux_temperature": (result.aux_temperature, "aux_temperature.parquet"),
        "aux_voltage": (result.aux_voltage, "aux_voltage.parquet"),
    }
    output_files: dict[str, Path] = {}
    for name, (frame, filename) in tables.items():
        if frame is not None:
            output_files[name] = write_parquet_verified(frame, output_dir / filename)

    records = result.records
    cycle_ids = sorted(
        int(value) for value in records["cycle_index_raw"].dropna().unique().tolist()
    )
    step_ids = sorted(int(value) for value in records["step_index_raw"].dropna().unique().tolist())
    parser_names = {asset.parser_name or "custom_excel" for asset in result.assets}
    parser_versions = {asset.parser_version for asset in result.assets if asset.parser_version}
    manifest_path = output_dir / "parser_manifest.json"
    manifest = {
        "battery_id": result.battery_id,
        "experiment_id": result.experiment_id,
        "parser": next(iter(parser_names)) if len(parser_names) == 1 else "mixed",
        "parser_version": next(iter(parser_versions)) if len(parser_versions) == 1 else None,
        "source_assets": [asset.asset_id for asset in result.assets],
        "source_asset_details": [
            {
                "asset_id": asset.asset_id,
                "relative_path": asset.relative_path.as_posix(),
                "parser_name": asset.parser_name,
                "parser_version": asset.parser_version,
            }
            for asset in result.assets
        ],
        "source_sha256": {
            parsed.asset.asset_id: parsed.source_sha256 for parsed in result.asset_results
        },
        "sheets_found": {
            parsed.asset.asset_id: {
                name: {"rows": info.rows, "columns": info.columns}
                for name, info in parsed.sheets_found.items()
            }
            for parsed in result.asset_results
        },
        "column_mappings": {
            parsed.asset.asset_id: parsed.column_mappings for parsed in result.asset_results
        },
        "row_counts": {
            "records": len(result.records),
            "cycles": len(result.cycles),
            "steps": len(result.steps),
            "aux_temperature": len(result.aux_temperature)
            if result.aux_temperature is not None
            else 0,
            "aux_voltage": len(result.aux_voltage) if result.aux_voltage is not None else 0,
            "per_asset_records": {
                parsed.asset.asset_id: len(parsed.records) for parsed in result.asset_results
            },
        },
        "cycle_ids_raw": cycle_ids,
        "step_ids_raw": step_ids,
        "timestamp_min": records["timestamp"].min().isoformat(),
        "timestamp_max": records["timestamp"].max().isoformat(),
        "null_counts": {column: int(count) for column, count in records.isna().sum().items()},
        "duplicate_timestamp_count": int(records["timestamp"].duplicated().sum()),
        "warnings": result.warnings,
        "output_files": {
            **{name: path.name for name, path in output_files.items()},
            "parser_manifest": manifest_path.name,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_scalar) + "\n",
        encoding="utf-8",
    )
    output_files["parser_manifest"] = manifest_path
    return ElectricalOutputManifest(
        output_dir=output_dir,
        manifest_path=manifest_path,
        output_files=output_files,
    )

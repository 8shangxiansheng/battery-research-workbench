"""BRW-015 high-level parameter-set service.

Implements the user principle end-to-end:

1. **auto-read** data-factual parameters (acquisition window from the Zarr
   shape; reference capacity / cycle / policy from the BRW-014 label manifest);
2. merge **user overrides** (accepted only for parameters whose catalog policy
   permits user configuration);
3. **resolve** every canonical parameter with the frozen precedence policy;
4. **derive** only with verified premises (acquisition_window_s = samples / fs);
5. persist the parameter set; raw parser manifests are never mutated.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import zarr

from battery_workbench.parameters.catalog import CANONICAL_PARAMETERS, get_spec
from battery_workbench.parameters.parameter_set_id import build_parameter_set_id
from battery_workbench.parameters.resolution import resolve_parameter
from battery_workbench.parameters.schemas import (
    ParameterConfig,
    ParameterRecord,
)
from battery_workbench.parameters.sources import SourceType

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_id(name: str, source: str, scope: str, seq: int) -> str:
    return f"{name}:{source}:{scope}:{seq}"


def _auto_records(
    *,
    battery_id: str,
    experiment_id: str,
    cycles_path: Path | None,
    waveform_store_path: Path | None,
    label_manifest_path: Path | None,
) -> list[ParameterRecord]:
    """Collect data-factual records (AUTO_ONLY sources)."""
    records: list[ParameterRecord] = []
    seq = 0

    # acquisition_window_samples from the Zarr waveform shape.
    if waveform_store_path is not None and Path(waveform_store_path).exists():
        try:
            root = zarr.open_group(str(waveform_store_path), mode="r")
            # Nested layout: {asset}/waveform — array_keys() is non-recursive in zarr 3.
            array_paths = [f"{key}/waveform" for key in root if f"{key}/waveform" in root]
            for key in array_paths:
                arr = root[key]
                if arr.ndim == 2:
                    records.append(
                        ParameterRecord(
                            parameter_record_id=_record_id(
                                "ultrasound.acquisition_window_samples",
                                "FILE_REPORTED",
                                "DATA_ASSET",
                                seq,
                            ),
                            canonical_name="ultrasound.acquisition_window_samples",
                            value=float(arr.shape[1]),
                            unit="sample",
                            source_type=SourceType.FILE_REPORTED,
                            source_reference=str(waveform_store_path),
                            evidence_note=f"waveform shape {arr.shape} read from Zarr store",
                            verification_status="VERIFIED",
                            scope_type="DATA_ASSET",
                            scope_key=f"{battery_id}/{experiment_id}/{key.split('/')[0]}",
                            battery_id=battery_id,
                            experiment_id=experiment_id,
                            asset_id=key.split("/")[0],
                        )
                    )
                    seq += 1
        except Exception as exc:  # noqa: BLE001 - a missing store leaves UNKNOWN
            logger.info("waveform store unreadable: %s", exc)

    # Reference capacity / cycle / policy from the BRW-014 label manifest.
    if label_manifest_path is not None and Path(label_manifest_path).exists():
        try:
            lm = json.loads(Path(label_manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lm = {}
        mapping = {
            "battery.reference_capacity_ah": lm.get("soh_reference_capacity_ah"),
            "labels.reference_cycle_index": lm.get("soh_reference_cycle"),
            "labels.reference_capacity_policy": lm.get("soh_reference_source"),
        }
        for name, value in mapping.items():
            if value is None:
                continue
            unit = get_spec(name).unit
            records.append(
                ParameterRecord(
                    parameter_record_id=_record_id(name, "MANIFEST_REPORTED", "EXPERIMENT", seq),
                    canonical_name=name,
                    value=value if isinstance(value, str) else float(value),
                    unit=unit,
                    source_type=SourceType.MANIFEST_REPORTED,
                    source_reference=str(label_manifest_path),
                    evidence_note="auto-read from the BRW-014 label manifest",
                    verification_status="UNVERIFIED",
                    scope_type="EXPERIMENT",
                    scope_key=f"{battery_id}/{experiment_id}",
                    battery_id=battery_id,
                    experiment_id=experiment_id,
                )
            )
            seq += 1

    return records


def _apply_user_overrides(
    records: list[ParameterRecord],
    user_overrides: dict[str, dict[str, Any]] | None,
    *,
    battery_id: str,
    experiment_id: str,
) -> list[ParameterRecord]:
    """Merge user-supplied records for parameters whose policy permits them."""
    if not user_overrides:
        return records
    out = list(records)
    seq = 10_000
    for name, payload in user_overrides.items():
        spec = get_spec(name)
        if spec.resolution_policy.value == "AUTO_ONLY":
            logger.warning("user override ignored for AUTO_ONLY parameter %s", name)
            continue
        out.append(
            ParameterRecord(
                parameter_record_id=_record_id(name, "USER_SUPPLIED", "EXPERIMENT", seq),
                canonical_name=name,
                value=payload.get("value"),
                unit=payload.get("unit", spec.unit),
                source_type=SourceType.USER_SUPPLIED,
                source_reference="configs/experiment_parameters.yaml",
                evidence_note=payload.get("evidence_note", ""),
                verification_status=payload.get("verification_status", "UNVERIFIED"),
                scope_type="EXPERIMENT",
                scope_key=f"{battery_id}/{experiment_id}",
                battery_id=battery_id,
                experiment_id=experiment_id,
            )
        )
        seq += 1
    return out


def build_parameter_set(
    *,
    output_root: Path,
    config: ParameterConfig | None = None,
    measurement_events_path: Path | None = None,
    cycles_path: Path | None = None,
    waveform_store_path: Path | None = None,
    label_manifest_path: Path | None = None,
    user_overrides: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Build one deterministic parameter set (registry contract entry point)."""
    from battery_workbench.parameters.persistence import write_parameter_payload

    output_root = Path(output_root)
    config = config or ParameterConfig()

    battery_id = "CELL_001"
    experiment_id = "EXP_001"

    if measurement_events_path is not None and Path(measurement_events_path).exists():
        events = pd.read_parquet(measurement_events_path)
        if not events.empty:
            battery_id = str(events["battery_id"].iloc[0])
            experiment_id = str(events["experiment_id"].iloc[0])

    # 1. auto-read.
    records = _auto_records(
        battery_id=battery_id,
        experiment_id=experiment_id,
        cycles_path=cycles_path,
        waveform_store_path=waveform_store_path,
        label_manifest_path=label_manifest_path,
    )
    # 2. user overrides (policy-filtered).
    records = _apply_user_overrides(
        records, user_overrides, battery_id=battery_id, experiment_id=experiment_id
    )

    # 3. resolve every canonical parameter.
    target_key = f"{battery_id}/{experiment_id}"
    effective: dict[str, dict] = {}
    for spec in CANONICAL_PARAMETERS:
        result = resolve_parameter(records, spec, target_scope_key=target_key)
        effective[spec.canonical_name] = result.model_dump(mode="json")

    # 4. verified-premise derivations only.
    fs_entry = effective.get("ultrasound.sampling_rate_hz", {})
    fs_value = fs_entry.get("value")
    fs_verified = fs_entry.get("verification_status") == "VERIFIED"
    samples_entry = effective.get("ultrasound.acquisition_window_samples", {})
    samples_value = samples_entry.get("value")
    if (
        isinstance(fs_value, (int, float))
        and fs_verified
        and isinstance(samples_value, (int, float))
        and fs_value > 0
    ):
        effective["ultrasound.acquisition_window_s"] = {
            "canonical_name": "ultrasound.acquisition_window_s",
            "value": samples_value / fs_value,
            "unit": "s",
            "status": "RESOLVED",
            "critical": False,
            "selected_parameter_record_id": samples_entry.get("selected_parameter_record_id"),
            "source_type": "DERIVED_FROM_VERIFIED_PARAMETERS",
            "verification_status": "DERIVED_FROM_VERIFIED_PARAMETERS",
            "resolution_reason": "acquisition_window_s = samples / fs (both VERIFIED)",
            "shadowed_records": [],
        }
    else:
        effective.setdefault(
            "ultrasound.acquisition_window_s",
            {
                "canonical_name": "ultrasound.acquisition_window_s",
                "value": None,
                "unit": "s",
                "status": "UNKNOWN",
                "critical": False,
                "selected_parameter_record_id": None,
                "source_type": None,
                "verification_status": "UNKNOWN",
                "resolution_reason": "requires a VERIFIED fs and sample count",
                "shadowed_records": [],
            },
        )

    # 5. capability matrix.
    from battery_workbench.parameters.capabilities import evaluate_capabilities

    capability_matrix = evaluate_capabilities(effective=effective, delay_policy=config.delay_policy)

    # 6. deterministic id over unit-normalized records.
    normalized_records = [
        {
            "canonical_name": spec.canonical_name,
            "value": effective[spec.canonical_name].get("value"),
            "unit": spec.unit,
            "source_type": effective[spec.canonical_name].get("source_type"),
            "verification_status": effective[spec.canonical_name].get("verification_status"),
            "scope_type": effective[spec.canonical_name].get("scope_type"),
            "scope_key": effective[spec.canonical_name].get("scope_key", target_key),
        }
        for spec in CANONICAL_PARAMETERS
        if spec.canonical_name in effective
    ]
    parameter_set_id = build_parameter_set_id(
        normalized_records=normalized_records,
        resolution_policy_version=config.resolution_policy_version,
        unit_policy_version=config.unit_policy_version,
        battery_id=battery_id,
        experiment_id=experiment_id,
    )

    # 7. persist. The records table is a provenance table: its value column
    # is stringified because canonical values mix numeric and text parameters;
    # typed values remain in effective_parameters.json.
    records_df = (
        pd.DataFrame([r.model_dump(mode="json") for r in records])
        if records
        else pd.DataFrame(
            columns=[
                "parameter_record_id",
                "canonical_name",
                "value",
                "unit",
                "source_type",
                "source_reference",
                "evidence_note",
                "verification_status",
                "scope_type",
                "scope_key",
            ]
        )
    )
    if not records_df.empty:
        records_df["value"] = records_df["value"].map(lambda v: None if v is None else str(v))
    input_paths = {
        k: v
        for k, v in {
            "measurement_events": measurement_events_path,
            "cycles": cycles_path,
            "waveform_store": waveform_store_path,
            "label_manifest": label_manifest_path,
        }.items()
        if v is not None
    }
    return write_parameter_payload(
        records=records_df,
        effective=effective,
        capability_matrix=capability_matrix,
        battery_id=battery_id,
        experiment_id=experiment_id,
        parameter_set_id=parameter_set_id,
        input_paths=input_paths,  # type: ignore[arg-type]
        config=config,
        output_root=output_root,
    )

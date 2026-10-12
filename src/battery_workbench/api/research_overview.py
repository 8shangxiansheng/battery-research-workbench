"""BRW-025R-OV — Research Overview aggregate read endpoint.

GET /experiments/{b}/{e}/research-overview

Single read-only aggregation for the Overview first screen: metadata strip,
electrical snapshot, ultrasound/TOF snapshot, signal quality, scientific
readiness matrix, scientific snapshot, model baseline comparison, limitations,
stale-artifact flags and recommended next actions. The frontend computes NO
science (no CE, no TOF, no correlation, no model metrics).

Read-only contract: every value comes from existing artifacts (BRW-017R2 /
BRW-018R2 outputs, electrical parquet manifests, parameter registry, model
comparison JSON). This module never writes scientific artifacts and never
re-runs pipelines. Unknown metadata is reported as Not configured /
Unavailable — never guessed (AGENTS.md #5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.event_label_join import merge_event_labels
from battery_workbench.api.integrity import (
    assert_canonical_tof_integrity,
    assert_processed_artifact_integrity,
)
from battery_workbench.api.service import validate_id
from battery_workbench.provenance.parser_manifest import (
    invalid_parser_manifest_modalities,
    invalid_parser_output_modalities,
    invalid_parser_source_modalities,
)

_STALE_DEFINITION_VERSION = "0.1.0"  # dataset/model built before BRW-013X V2


def _read_json_value(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    payload = _read_json_value(path)
    return payload if isinstance(payload, dict) else None


def _invalid_sources(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> list[str]:
    if raw_root is None:
        return sorted(
            set(invalid_parser_manifest_modalities(processed_root, b, e))
            | set(invalid_parser_output_modalities(processed_root, b, e))
        )
    return invalid_parser_source_modalities(processed_root, raw_root, b, e)


def _source_provenance_invalid(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> bool:
    return bool(_invalid_sources(processed_root, b, e, raw_root))


def _canonical_event_integrity(
    processed_root: Path, b: str, e: str
) -> tuple[str, list[str]]:
    """Check the canonical event chain before Overview aggregates consume it."""
    event_dir = processed_root / "multimodal" / b / e
    events_path = event_dir / "measurement_events.parquet"
    event_manifest = event_dir / "measurement_event_manifest.json"
    if not events_path.is_file() and not event_manifest.exists():
        return "NOT_AVAILABLE", ["MEASUREMENT_EVENTS_NOT_AVAILABLE"]
    try:
        assert_processed_artifact_integrity(
            processed_root,
            event_manifest,
            battery_id=b,
            experiment_id=e,
            required_outputs={"events", "candidates"},
            required_inputs={"aligned", "sync_candidates", "electrical_records"},
        )
    except APIError as exc:
        return "INTEGRITY_BLOCKED", [
            str(reason)
            for reason in (exc.details.get("integrity_reasons") or ["MEASUREMENT_EVENT_INVALID"])
        ]

    labels_dir = processed_root / "labels" / b / e
    label_path = labels_dir / "event_labels.parquet"
    label_manifest = labels_dir / "label_manifest.json"
    if not label_path.exists() and not label_manifest.exists():
        return "LABELS_NOT_AVAILABLE", ["EVENT_LABELS_NOT_AVAILABLE"]
    if not label_path.is_file() or not label_manifest.is_file():
        return "INTEGRITY_BLOCKED", ["LABEL_MANIFEST_OR_EVENT_LABELS_MISSING"]
    try:
        assert_processed_artifact_integrity(
            processed_root,
            label_manifest,
            battery_id=b,
            experiment_id=e,
            required_outputs={"event_labels"},
            required_inputs={"measurement_events", "records", "cycles", "steps"},
            required_manifest_fields={"label_set_id"},
            recovery_action="REBUILD_LABELS_FROM_CURRENT_VERIFIED_INPUTS",
        )
    except APIError as exc:
        return "INTEGRITY_BLOCKED", [
            str(reason)
            for reason in (exc.details.get("integrity_reasons") or ["EVENT_LABELS_INVALID"])
        ]
    try:
        events = pd.read_parquet(events_path, columns=["measurement_event_id"])
        labels = pd.read_parquet(label_path, columns=["measurement_event_id"])
        merge_event_labels(events, labels)
    except APIError as exc:
        return "INTEGRITY_BLOCKED", [
            str(reason)
            for reason in (
                exc.details.get("integrity_reasons")
                or ["MEASUREMENT_EVENT_LABEL_JOIN_INVALID"]
            )
        ]
    except (KeyError, OSError, ValueError):
        return "INTEGRITY_BLOCKED", ["MEASUREMENT_EVENT_LABEL_IDENTITY_UNREADABLE"]
    return "CURRENT", []


def _downsampled_series(
    df: pd.DataFrame, column: str, points: int = 240
) -> list[float | None]:
    if column not in df.columns or df.empty:
        return []
    step = max(1, len(df) // points)
    s = df[column].iloc[::step]
    return [None if pd.isna(v) else round(float(v), 4) for v in s]


def _fs_state(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """fs from the newest resolved parameter set (registry provenance only)."""
    ps_dir = processed_root / "parameters" / b / e
    newest_resolved: tuple[float | None, bool, str | None] = (None, False, None)
    if ps_dir.is_dir():
        from battery_workbench.features_physical.canonical_tof import effective_fs

        for manifest in sorted(ps_dir.glob("PS::*/effective_parameters.json")):
            eff = _read_json(manifest)
            if not eff:
                continue
            eff = eff.get("effective_parameters") or eff
            fs, verified = effective_fs(eff, require_verified=True)
            if verified:
                return {
                    "sampling_rate_hz": fs,
                    "sampling_rate_verified": True,
                    "parameter_set_id": manifest.parent.name,
                }
            if fs is not None and newest_resolved[0] is None:
                newest_resolved = (
                    fs, False, manifest.parent.name,
                )
    return {
        "sampling_rate_hz": newest_resolved[0],
        "sampling_rate_verified": False,
        "parameter_set_id": newest_resolved[2],
    }


def _metadata_strip(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    """Metadata strip — unknown fields are Not configured, never guessed."""
    invalid_modalities = set(_invalid_sources(processed_root, b, e, raw_root))
    if "electrical" in invalid_modalities:
        # Parser-derived temperature and time metadata must not survive a
        # broken source manifest. Sampling-rate registration is independent.
        fs_state = _fs_state(processed_root, b, e)
        return {
            "battery_id": b,
            "experiment_id": e,
            "chemistry": {"status": "NOT_CONFIGURED", "value": None},
            "nominal_capacity_ah": {"status": "NOT_CONFIGURED", "value": None},
            "probe": {"status": "NOT_CONFIGURED", "value": None},
            "channel": {"status": "NOT_CONFIGURED", "value": None},
            "temperature": {"status": "INTEGRITY_BLOCKED", "channel": None},
            "sampling_rate": {
                "status": "AVAILABLE" if fs_state["sampling_rate_verified"] else "NOT_CONFIGURED",
                "hz": fs_state["sampling_rate_hz"],
                "verified": fs_state["sampling_rate_verified"],
                "parameter_set_id": fs_state["parameter_set_id"],
            },
            "acquisition_window": {
                "status": "INTEGRITY_BLOCKED",
                "start": None,
                "end": None,
            },
            "timebase": {"status": "INTEGRITY_BLOCKED"},
        }
    parser = _read_json(processed_root / "electrical" / b / e / "parser_manifest.json") or {}
    fs_state = _fs_state(processed_root, b, e)

    aux_t = processed_root / "electrical" / b / e / "aux_temperature.parquet"
    temperature: dict[str, Any] = {"status": "NOT_CONFIGURED", "channel": None}
    if aux_t.is_file():
        try:
            tdf = pd.read_parquet(aux_t, columns=["temperature_channel", "temperature_c"])
            channels = sorted(str(c) for c in tdf["temperature_channel"].dropna().unique())
            tmin = float(tdf["temperature_c"].min())
            tmax = float(tdf["temperature_c"].max())
            temperature = {
                "status": "AVAILABLE",
                "channel": channels or None,
                "range_c": [round(tmin, 1), round(tmax, 1)],
            }
        except (OSError, ValueError):
            pass

    ts_min = parser.get("timestamp_min")
    ts_max = parser.get("timestamp_max")
    return {
        "battery_id": b,
        "experiment_id": e,
        "chemistry": {"status": "NOT_CONFIGURED", "value": None},
        "nominal_capacity_ah": {"status": "NOT_CONFIGURED", "value": None},
        "probe": {"status": "NOT_CONFIGURED", "value": None},
        "channel": {
            "status": "NOT_CONFIGURED" if not fs_state["sampling_rate_verified"] else "AVAILABLE",
            "value": None,
        },
        "temperature": temperature,
        "sampling_rate": {
            "status": "AVAILABLE" if fs_state["sampling_rate_verified"] else "NOT_CONFIGURED",
            "hz": fs_state["sampling_rate_hz"],
            "verified": fs_state["sampling_rate_verified"],
            "parameter_set_id": fs_state["parameter_set_id"],
        },
        "acquisition_window": {
            "status": "NOT_CONFIGURED",
            "start": ts_min,
            "end": ts_max,
        },
        "timebase": {"status": "PROVISIONAL"},
    }


def _electrical_snapshot(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    if "electrical" in _invalid_sources(processed_root, b, e, raw_root):
        return {
            "status": "INTEGRITY_BLOCKED",
            "record_count": None,
            "cycle_count": None,
            "step_count": None,
            "voltage_range_v": None,
            "current_range_a": None,
            "voltage_sparkline_v": [],
            "current_sparkline_a": [],
            "cycles": [],
        }
    rec_path = processed_root / "electrical" / b / e / "records.parquet"
    cyc_path = processed_root / "electrical" / b / e / "cycles.parquet"
    stp_path = processed_root / "electrical" / b / e / "steps.parquet"
    if not rec_path.is_file():
        return {"status": "UNAVAILABLE"}
    records = pd.read_parquet(rec_path, columns=["voltage_v", "current_a"])
    cycles = pd.read_parquet(cyc_path) if cyc_path.is_file() else pd.DataFrame()
    steps = pd.read_parquet(stp_path) if stp_path.is_file() else pd.DataFrame()

    cycle_rows = []
    for _, row in cycles.iterrows():
        ce = row.get("coulombic_efficiency_percent")
        cycle_rows.append(
            {
                "cycle_index_raw": int(row["cycle_index_raw"]),
                "charge_capacity_ah": (
                    None if pd.isna(row.get("charge_capacity_ah")) else round(float(row["charge_capacity_ah"]), 4)
                ),
                "discharge_capacity_ah": (
                    None if pd.isna(row.get("discharge_capacity_ah")) else round(float(row["discharge_capacity_ah"]), 4)
                ),
                "apparent_coulombic_efficiency_percent": (
                    None if pd.isna(ce) else round(float(ce), 2)
                ),
                "protocol": "PROTOCOL_FROM_PARSER",
            }
        )
    return {
        "status": "AVAILABLE",
        "record_count": len(records),
        "cycle_count": len(cycles),
        "step_count": int(steps["step_index_raw"].nunique()) if not steps.empty and "step_index_raw" in steps else None,
        "voltage_range_v": [
            round(float(records["voltage_v"].min()), 4),
            round(float(records["voltage_v"].max()), 4),
        ],
        "current_range_a": [
            round(float(records["current_a"].min()), 4),
            round(float(records["current_a"].max()), 4),
        ],
        "voltage_sparkline_v": _downsampled_series(records, "voltage_v"),
        "current_sparkline_a": _downsampled_series(records, "current_a"),
        "cycles": cycle_rows,
    }


def _tof_snapshot(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    if _invalid_sources(processed_root, b, e, raw_root):
        return {
            "status": "INTEGRITY_BLOCKED",
            "tof_method_id": "BLOCKED_BY_SOURCE_INTEGRITY",
            "tof_definition_version": None,
            "sampling_rate_hz": None,
            "sampling_rate_verified": False,
            "gate_calibration_id": "BLOCKED_BY_SOURCE_INTEGRITY",
            "gate_calibration_source": "UNAVAILABLE",
            "gate_calibration_version": 0,
            "surface_gate_id": "UNAVAILABLE",
            "surface_peak_sample_range": [0, 0],
            "bottom_gate_id": "UNAVAILABLE",
            "bottom_peak_sample_range": [0, 0],
            "artifact_status_counts": {},
            "artifact_tof_us_summary": None,
            "artifact_current": False,
            "waveform_tof": {
                "event_count": None,
                "ambiguous_events": None,
                "note": "source parser provenance is invalid",
            },
            "feature_target_eligible": {
                "eligible_count": None,
                "note": "source parser provenance is invalid",
            },
        }
    event_integrity_status, event_integrity_reasons = _canonical_event_integrity(
        processed_root, b, e
    )
    if event_integrity_status == "INTEGRITY_BLOCKED":
        return {
            "status": "INTEGRITY_BLOCKED",
            "tof_method_id": "BLOCKED_BY_EVENT_PROVENANCE",
            "tof_definition_version": None,
            "sampling_rate_hz": None,
            "sampling_rate_verified": False,
            "gate_calibration_id": "BLOCKED_BY_EVENT_PROVENANCE",
            "gate_calibration_source": "UNAVAILABLE",
            "gate_calibration_version": 0,
            "surface_gate_id": "UNAVAILABLE",
            "surface_peak_sample_range": [0, 0],
            "bottom_gate_id": "UNAVAILABLE",
            "bottom_peak_sample_range": [0, 0],
            "artifact_status_counts": {},
            "artifact_tof_us_summary": None,
            "artifact_current": False,
            "measurement_event_integrity_status": event_integrity_status,
            "measurement_event_integrity_reasons": event_integrity_reasons,
            "waveform_tof": {
                "event_count": None,
                "ambiguous_events": None,
                "note": "MeasurementEvent/label provenance is invalid; linked TOF summary is hidden",
            },
            "feature_target_eligible": {
                "eligible_count": None,
                "note": "MeasurementEvent/label provenance is invalid",
            },
        }
    from battery_workbench.features.gate_calibration import resolve_tof_gate_calibration

    parquet_path = processed_root / "features_physical" / b / e / "canonical_tof.parquet"
    tof_integrity_reasons: list[str] = []
    manifest_path = parquet_path.with_name("canonical_tof_manifest.json")
    audit_path = parquet_path.with_name("canonical_tof_audit.json")
    artifact_declared = any(path.exists() for path in (parquet_path, manifest_path, audit_path))
    if artifact_declared:
        try:
            assert_canonical_tof_integrity(
                processed_root, battery_id=b, experiment_id=e
            )
        except APIError as exc:
            tof_integrity_reasons = list(
                exc.details.get("integrity_reasons") or ["CANONICAL_TOF_INVALID"]
            )
    audit = (_read_json(audit_path) or {}) if not tof_integrity_reasons else {}
    cal = resolve_tof_gate_calibration(b, e, processed_root)
    fs_state = _fs_state(processed_root, b, e)
    fs_hz, fs_verified = fs_state["sampling_rate_hz"], fs_state["sampling_rate_verified"]

    status = "NOT_CONFIGURED"
    tof_us_summary = None
    if tof_integrity_reasons:
        status = "INTEGRITY_BLOCKED"
    elif fs_verified:
        status = "READY"
    elif fs_hz is not None:
        status = "BLOCKED"  # resolved but unverified → activation refused

    counts: dict[str, int] = {}
    if parquet_path.is_file() and not tof_integrity_reasons:
        try:
            tof_df = pd.read_parquet(
                parquet_path,
                columns=[
                    "tof_status", "tof_us",
                    "surface_peak_sample_index", "bottom_peak_sample_index",
                    "gate_calibration_id",
                ],
            )
            counts = {
                str(status): int(count)
                for status, count in tof_df["tof_status"].value_counts().items()
            }
            int((tof_df["tof_status"] == "VALID").sum())
            valid = tof_df[tof_df["tof_status"] == "VALID"]
            if len(valid):
                tof_us_summary = {
                    "min": round(float(valid["tof_us"].min()), 3),
                    "median": round(float(valid["tof_us"].median()), 3),
                    "max": round(float(valid["tof_us"].max()), 3),
                }
        except (OSError, ValueError):
            pass

    artifact_matches_registry = audit.get("parameter_set_id") == fs_state["parameter_set_id"]
    artifact_verified = bool(audit.get("sampling_rate_verified"))
    # coverage: waveform TOF valid vs Feature–Target eligible are different
    # counts and are reported separately (never merged).
    events = processed_root / "multimodal" / b / e / "measurement_events.parquet"
    eligible = None
    event_count = None
    ambiguous = None
    if events.is_file():
        try:
            me = pd.read_parquet(
                events, columns=["analysis_eligible", "sync_ambiguous"]
            )
            event_count = len(me)
            eligible = int(me["analysis_eligible"].sum())
            ambiguous = int(me["sync_ambiguous"].sum())
        except (OSError, ValueError):
            pass

    return {
        "status": status,
        "tof_method_id": audit.get(
            "tof_method_id", "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
        ),
        "tof_definition_version": audit.get("tof_definition_version"),
        "sampling_rate_hz": fs_hz,
        "sampling_rate_verified": fs_verified,
        "gate_calibration_id": cal["gate_calibration_id"],
        "gate_calibration_source": cal["source"],
        "gate_calibration_version": cal["version"],
        "surface_gate_id": cal["surface_gate_id"],
        "surface_peak_sample_range": [int(cal["surface_start"]), int(cal["surface_end_exclusive"])],
        "bottom_gate_id": cal["bottom_gate_id"],
        "bottom_peak_sample_range": [int(cal["bottom_start"]), int(cal["bottom_end_exclusive"])],
        "artifact_status_counts": counts,
        "artifact_tof_us_summary": tof_us_summary,
        "artifact_current": bool(artifact_matches_registry and artifact_verified) or status == "NOT_CONFIGURED",
        "artifact_integrity_reasons": tof_integrity_reasons,
        "recovery_action": (
            "REBUILD_CANONICAL_TOF_FROM_CURRENT_FEATURES_AND_PARAMETERS"
            if tof_integrity_reasons
            else None
        ),
        "measurement_event_integrity_status": event_integrity_status,
        "measurement_event_integrity_reasons": event_integrity_reasons,
        "waveform_tof": {
            "event_count": event_count,
            "ambiguous_events": ambiguous,
            "note": "波形级 TOF 行（每 MeasurementEvent 帧一行）",
        },
        "feature_target_eligible": {
            "eligible_count": eligible,
            "note": "特征–目标可用行（analysis_eligible）——与波形 TOF 有效数不同",
        },
    }


def _signal_quality(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    """Only formally defined quality metrics are reported; no invented SNR."""
    if "ultrasound" in _invalid_sources(processed_root, b, e, raw_root):
        return {
            "snr": {
                "status": "INTEGRITY_BLOCKED",
                "value": None,
                "reason": "ultrasound parser provenance is invalid",
            },
            "saturation_check": {
                "status": "INTEGRITY_BLOCKED",
                "definition": "unavailable while ultrasound source integrity is blocked",
            },
        }
    return {
        "snr": {"status": "NOT_CONFIGURED", "value": None,
                "reason": "no formally defined SNR algorithm in the workbench"},
        "saturation_check": {
            "status": "AVAILABLE",
            "definition": "gate-level saturation fraction (SATURATION_LIMIT 32000, gates engine)",
        },
    }


def _readiness_matrix(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    fs_state = _fs_state(processed_root, b, e)
    tof_ready = fs_state["sampling_rate_verified"]
    source_integrity_blocked = _source_provenance_invalid(processed_root, b, e, raw_root)
    event_integrity_status, _ = _canonical_event_integrity(processed_root, b, e)
    event_integrity_blocked = event_integrity_status == "INTEGRITY_BLOCKED"
    return {
        "acquisition": "READY" if (processed_root / "ultrasound" / b / e / "frames.parquet").is_file() else "BLOCKED",
        "synchronization": "PROVISIONAL",
        "tof": "READY" if tof_ready else "BLOCKED",
        "targets": (
            "BLOCKED_BY_SOURCE_INTEGRITY"
            if source_integrity_blocked
            else "BLOCKED_BY_EVENT_INTEGRITY"
            if event_integrity_blocked
            else "BLOCKED_LABELS_UNAVAILABLE"
            if event_integrity_status == "LABELS_NOT_AVAILABLE"
            else "BLOCKED_EVENTS_UNAVAILABLE"
            if event_integrity_status == "NOT_AVAILABLE"
            else "READY_FOR_LIMITED_EVALUATION"
        ),
        "modeling": (
            "BLOCKED_BY_SOURCE_INTEGRITY"
            if source_integrity_blocked
            else "BLOCKED_BY_EVENT_INTEGRITY"
            if event_integrity_blocked
            else "LIMITED"
        ),
    }


def _current_chain_dataset(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Manifest of the dataset the most recent model run actually consumed."""
    from battery_workbench.reporting.collector import latest_evaluated_chain

    ds_id, _ = latest_evaluated_chain(processed_root, b, e)
    if not ds_id:
        return {}
    hit = next(
        (processed_root / "datasets").rglob(f"{ds_id}/dataset_manifest.json"), None
    )
    return (_read_json(hit) or {}) if hit else {}


def _feature_definition_state(processed_root: Path, b: str, e: str) -> dict[str, Any]:
    """Freshness against BRW-017R2 provenance: does the evaluated dataset
    carry the canonical envelope-peak TOF (tof_method_id) — the RC1 criterion
    replacing the retired BRW-013X '2.0.0' pin."""
    dataset_manifest = _current_chain_dataset(processed_root, b, e)
    fs_id = dataset_manifest.get("feature_set_id", "")
    fs_version = None
    if fs_id:
        # FS id contains its directory; the manifest lives next to the parquet
        for fs_manifest in (processed_root / "features" / b / e).glob(
            f"AS::*/{fs_id}/feature_set_manifest.json"
        ):
            fs = _read_json(fs_manifest) or {}
            fs_version = fs.get("feature_definition_version")
            break
    has_canonical_tof = bool(dataset_manifest.get("tof_method_id"))
    stale = not has_canonical_tof
    return {
        "feature_set_id": fs_id,
        "dataset_definition_version": fs_version,
        "current_policy": "MATLAB_ALIGNED_FEATURE_FORMULAS_V1",
        "canonical_tof_provenance": dataset_manifest.get("tof_method_id"),
        "uses_previous_feature_definition": bool(stale),
        "refresh_required": bool(stale),
        "note": (
            "当前模型工件早于 BRW-013X V2 特征定义，且从未使用 "
            "BRW-017R2 canonical 包络峰值 TOF"
        )
        if stale
        else (
            "当前模型数据集使用 BRW-017R2 canonical 包络峰值 TOF"
            f"（{dataset_manifest.get('tof_method_id')} · "
            f"gate {dataset_manifest.get('tof_gate_calibration_id')}）"
        ),
    }


def _leading_exploratory(processed_root: Path, b: str, e: str) -> dict[str, Any] | None:
    """Newest current EXPLORATORY_FULL_DATA correlation row for the SOC target."""
    from battery_workbench.feature_analysis.output import (
        verify_analysis_input_checksums,
        verify_analysis_output_checksums,
    )
    from battery_workbench.reporting.collector import latest_evaluated_chain

    ds_id, _ = latest_evaluated_chain(processed_root, b, e)
    if not ds_id:
        return None
    root = Path(processed_root).resolve()
    an_root = processed_root / "feature_analysis" / b / e / ds_id
    if not an_root.is_dir():
        return None
    try:
        resolved_analysis_root = an_root.resolve(strict=True)
        resolved_analysis_root.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    newest: tuple[int, str, pd.DataFrame] | None = None
    for an in an_root.glob("AN::*"):
        try:
            resolved_analysis = an.resolve(strict=True)
            resolved_analysis.relative_to(resolved_analysis_root)
            manifest_path = (resolved_analysis / "analysis_manifest.json").resolve(strict=True)
            manifest_path.relative_to(resolved_analysis)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        if (
            manifest.get("analysis_id") != an.name
            or manifest.get("dataset_id") != ds_id
            or manifest.get("battery_id", b) != b
            or manifest.get("experiment_id", e) != e
        ):
            continue
        if manifest.get("analysis_mode") != "EXPLORATORY_FULL_DATA":
            continue
        output_checksums = manifest.get("output_checksums")
        if (
            not isinstance(output_checksums, dict)
            or "feature_target_correlation.parquet" not in output_checksums
        ):
            continue
        output_status, _ = verify_analysis_output_checksums(resolved_analysis, manifest)
        input_status, _ = verify_analysis_input_checksums(root, manifest)
        if output_status != "CURRENT" or input_status != "CURRENT":
            continue
        corr_path = resolved_analysis / "feature_target_correlation.parquet"
        if not corr_path.is_file():
            continue
        try:
            df = pd.read_parquet(corr_path)
        except (OSError, ValueError):
            continue
        if df.empty or not {"feature_name", "method", "coefficient", "n"}.issubset(df.columns):
            continue
        candidate = (manifest_path.stat().st_mtime_ns, an.name, df)
        if newest is None or candidate[:2] > newest[:2]:
            newest = candidate
    if newest is None:
        return None
    _, analysis_id, df = newest
    row = df.iloc[0]
    return {
        "analysis_id": analysis_id,
        "feature_name": str(row.get("feature_name")),
        "method": str(row.get("method")),
        "coefficient": round(float(row["coefficient"]), 4) if pd.notna(row["coefficient"]) else None,
        "n": int(row["n"]) if pd.notna(row["n"]) else None,
        "note": "取自持久化的 EXPLORATORY_FULL_DATA 分析（未重新计算）",
    }


def _scientific_snapshot(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    """Target + leading exploratory candidate + model evidence (read-only).

    The leading candidate reuses the feature-target-ranking computation
    (deterministic, read-only); no new science is defined here.
    """
    source_integrity_blocked = _source_provenance_invalid(processed_root, b, e, raw_root)
    event_integrity_status, event_integrity_reasons = _canonical_event_integrity(
        processed_root, b, e
    )
    integrity_blocked = source_integrity_blocked or event_integrity_status == "INTEGRITY_BLOCKED"
    dataset_manifest = {} if integrity_blocked else _current_chain_dataset(processed_root, b, e)
    feature_state = (
        {
            "feature_set_id": None,
            "dataset_definition_version": None,
            "canonical_tof_provenance": None,
            "current_policy": "MATLAB_ALIGNED_FEATURE_FORMULAS_V1",
            "uses_previous_feature_definition": False,
            "refresh_required": True,
            "note": "feature provenance is hidden because source or event integrity is blocked",
            "status": "INTEGRITY_BLOCKED",
            "freshness_reasons": (
                _invalid_sources(processed_root, b, e, raw_root)
                if source_integrity_blocked
                else event_integrity_reasons
            ),
        }
        if integrity_blocked
        else _feature_definition_state(processed_root, b, e)
    )

    comparison = _model_comparison(processed_root, b, e, raw_root)
    selected_features = (
        (dataset_manifest or {}).get("selected_features") or []
        if comparison.get("status") not in {"STALE", "INTEGRITY_BLOCKED"}
        else []
    )
    if comparison.get("status") in {"STALE", "INTEGRITY_BLOCKED"}:
        feature_state = {
            **feature_state,
            "status": comparison["status"],
            "freshness_reasons": comparison.get("freshness_reasons", []),
        }
    # leading exploratory candidate from the newest persisted EXPLORATORY
    # correlation artifact (read-only; no fresh computation, no artifact writes)
    leading = None if integrity_blocked else _leading_exploratory(processed_root, b, e)
    return {
        "target": {"target_id": "reference_soc_percent",
                   "readiness": (
                       "BLOCKED_BY_SOURCE_INTEGRITY"
                       if source_integrity_blocked
                       else "BLOCKED_BY_EVENT_INTEGRITY"
                       if event_integrity_status == "INTEGRITY_BLOCKED"
                       else "BLOCKED_LABELS_UNAVAILABLE"
                       if event_integrity_status == "LABELS_NOT_AVAILABLE"
                       else "READY_FOR_LIMITED_EVALUATION"
                   ),
                   "note": (
                       "source parser provenance is invalid; repair the source manifest before interpreting results"
                       if source_integrity_blocked
                       else "MeasurementEvent/label provenance is invalid; rebuild derived artifacts before interpreting results"
                       if event_integrity_status == "INTEGRITY_BLOCKED"
                       else "Reference SOC labels are unavailable; generate labels from current verified inputs"
                       if event_integrity_status == "LABELS_NOT_AVAILABLE"
                       else "retrospective segment-normalized reference label"
                   )},
        "measurement_event_integrity_status": event_integrity_status,
        "measurement_event_integrity_reasons": event_integrity_reasons,
        "leading_exploratory_candidate": leading,
        "selected_features": selected_features,
        "model_evidence": {
            "dummy_first_conclusion": (
                None if integrity_blocked else comparison.get("dummy_first_conclusion")
            ),
            "dummy_macro_mae": (
                None if integrity_blocked else (comparison.get("dummy") or {}).get("macro_mae")
            ),
            "note": (
                "model evidence is hidden because source provenance integrity is blocked"
                if integrity_blocked
                else
                "model evaluation is stale because its dataset sources changed"
                if comparison.get("status") == "STALE"
                else "no model beat the Dummy baseline in the current same-scope evaluation"
            ),
        },
        "feature_definition": feature_state,
    }


def _model_comparison(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    """Current model artifact rows + freshness flags (never re-trained)."""
    from battery_workbench.datasets.freshness import dataset_freshness
    from battery_workbench.reporting.collector import latest_evaluated_chain

    invalid_modalities = _invalid_sources(processed_root, b, e, raw_root)
    event_integrity_status, event_integrity_reasons = _canonical_event_integrity(
        processed_root, b, e
    )
    if invalid_modalities or event_integrity_status == "INTEGRITY_BLOCKED":
        source_invalid = bool(invalid_modalities)
        reason = "SOURCE_PROVENANCE_INVALID" if source_invalid else "MEASUREMENT_EVENT_INTEGRITY_INVALID"
        feature_state = {
            "feature_set_id": None,
            "dataset_definition_version": None,
            "canonical_tof_provenance": None,
            "current_policy": "MATLAB_ALIGNED_FEATURE_FORMULAS_V1",
            "uses_previous_feature_definition": False,
            "refresh_required": True,
            "note": "feature provenance is hidden because source or event integrity is blocked",
            "status": "INTEGRITY_BLOCKED",
            "freshness_reasons": [reason, *event_integrity_reasons],
            "invalid_modalities": invalid_modalities,
        }
        return {
            "status": "INTEGRITY_BLOCKED",
            "artifact_path": None,
            "strategies": [],
            "dummy": None,
            "dummy_first_conclusion": None,
            "freshness_reasons": [reason, *event_integrity_reasons],
            "invalid_modalities": invalid_modalities,
            "dataset_id": None,
            "split_id": None,
            "feature_definition": feature_state,
        }

    root = processed_root / "models" / b / e
    dataset_id, split_id = latest_evaluated_chain(processed_root, b, e)
    if not dataset_id or not split_id:
        return {
            "status": "UNAVAILABLE",
            "artifact_path": None,
            "strategies": [],
            "dummy": None,
            "dummy_first_conclusion": None,
            "freshness_reasons": [],
            "dataset_id": None,
            "split_id": None,
            "feature_definition": _feature_definition_state(processed_root, b, e),
        }
    comp_path = (
        root / dataset_id / split_id / "model_comparison.json"
        if dataset_id and split_id
        else None
    )
    manifest_path = next(
        (processed_root / "datasets" / b / e).rglob(
            f"{dataset_id}/dataset_manifest.json"
        ),
        None,
    ) if dataset_id else None
    manifest = _read_json(manifest_path) if manifest_path else None
    freshness = (
        dataset_freshness(processed_root, manifest_path, manifest, raw_root=raw_root)
        if manifest_path and manifest
        else {"freshness_status": "STALE_SOURCE", "freshness_reasons": ["DATASET_MANIFEST_MISSING"]}
    )
    if freshness["freshness_status"] != "FRESH":
        feature_state = {
            **_feature_definition_state(processed_root, b, e),
            "status": "STALE",
            "freshness_reasons": list(freshness["freshness_reasons"]),
        }
        return {
            "status": "STALE",
            "artifact_path": str(comp_path.relative_to(processed_root)) if comp_path and comp_path.is_file() else None,
            "strategies": [],
            "dummy": None,
            "dummy_first_conclusion": None,
            "freshness_reasons": freshness["freshness_reasons"],
            "dataset_id": dataset_id or None,
            "split_id": split_id or None,
            "feature_definition": feature_state,
        }
    if comp_path is None or not comp_path.is_file():
        return {
            "status": "UNAVAILABLE",
            "artifact_path": None,
            "strategies": [],
            "dummy": None,
            "dummy_first_conclusion": None,
            "freshness_reasons": [],
            "dataset_id": dataset_id,
            "split_id": split_id,
            "feature_definition": _feature_definition_state(processed_root, b, e),
        }
    raw_rows = _read_json_value(comp_path)
    rows = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    feature_state = _feature_definition_state(processed_root, b, e)
    strategies = [
        {
            "strategy": r.get("strategy"),
            "macro_mae": r.get("macro_MAE"),
            "macro_rmse": r.get("macro_RMSE"),
            "macro_r2": r.get("macro_R2"),
            "vs_dummy": r.get("macro_MAE_vs_DUMMY"),
        }
        for r in rows
    ]
    dummy = next((s for s in strategies if s["strategy"] == "DUMMY_MEAN"), None)
    return {
        "status": "AVAILABLE",
        "artifact_path": str(comp_path.relative_to(processed_root)),
        "strategies": strategies,
        "dummy": dummy,
        "dummy_first_conclusion": (
            "当前同口径评估中没有任何模型跑赢 Dummy 基准"
            if dummy is not None
            and all(
                (s["macro_mae"] or 0) >= (dummy["macro_mae"] or 0)
                for s in strategies
                if s["strategy"] != "DUMMY_MEAN"
            )
            else None
        ),
        "feature_definition": feature_state,
    }


_LIMITATION_ZH: dict[str, str] = {
    "ONE_BATTERY_ONLY": "数据集仅含 1 块电池——无法进行跨电池评估",
    "SOH_INDEPENDENT_STATES_TOO_FEW": "SOH 独立状态数未达到数据集就绪门槛（事件行不独立）",
    "LIMITED_CROSS_CYCLE_GENERALIZATION": "仅限同电池跨循环评估，不外推泛化",
    "PROVISIONAL_TIMEBASE": "同步时间基准为临时基准（尚未验证）",
    "SOURCE_PROVENANCE_INVALID": "原始来源解析清单无效；来源追溯与相关科学主张已阻断",
    "MEASUREMENT_EVENT_INTEGRITY_INVALID": "声电关联/标签工件完整性失败；依赖事件的结果已阻断",
}


def _limitations_first_screen(
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    raw_root: Path | None = None,
) -> list[dict[str, str]]:
    from battery_workbench.reporting.collector import collect_limitation_registry

    codes = {"PROVISIONAL_TIMEBASE", "SOH_INDEPENDENT_STATES_TOO_FEW",
             "LIMITED_CROSS_CYCLE_GENERALIZATION", "ONE_BATTERY_ONLY",
             "SOURCE_PROVENANCE_INVALID", "MEASUREMENT_EVENT_INTEGRITY_INVALID"}
    out = []
    for l in collect_limitation_registry(processed_root, battery_id, experiment_id):
        if l["code"] not in codes:
            continue
        out.append({**l, "description_zh": _LIMITATION_ZH.get(l["code"], l["description"])})
    if raw_root is not None and _invalid_sources(
        processed_root, battery_id, experiment_id, raw_root
    ) and not any(item["code"] == "SOURCE_PROVENANCE_INVALID" for item in out):
        out.append(
            {
                "code": "SOURCE_PROVENANCE_INVALID",
                "severity": "BLOCKING_FOR_CLAIM",
                "description": "registered raw source bytes no longer match parser provenance",
                "description_zh": _LIMITATION_ZH["SOURCE_PROVENANCE_INVALID"],
            }
        )
    event_integrity_status, event_integrity_reasons = _canonical_event_integrity(
        processed_root, battery_id, experiment_id
    )
    if event_integrity_status == "INTEGRITY_BLOCKED":
        out.append(
            {
                "code": "MEASUREMENT_EVENT_INTEGRITY_INVALID",
                "severity": "BLOCKING_FOR_CLAIM",
                "description": "MeasurementEvent or Reference SOC label manifest/input/output checksum is invalid",
                "description_zh": _LIMITATION_ZH["MEASUREMENT_EVENT_INTEGRITY_INVALID"],
                "reasons": ";".join(event_integrity_reasons),
            }
        )
    return out


def _next_actions(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> list[dict[str, str]]:
    """Recommended next action from the current scientific state (≤3)."""
    if _source_provenance_invalid(processed_root, b, e, raw_root):
        return [{
            "action_id": "REPAIR_SOURCE_PROVENANCE",
            "label": "重新解析原始文件并复核来源追溯",
            "route": f"/experiments/{b}/{e}/runs",
        }]
    event_integrity_status, event_integrity_reasons = _canonical_event_integrity(
        processed_root, b, e
    )
    if event_integrity_status == "INTEGRITY_BLOCKED":
        return [{
            "action_id": "REBUILD_VERIFIED_EVENT_CHAIN",
            "label": "从已验证输入重建同步、MeasurementEvent 与标签工件",
            "route": f"/experiments/{b}/{e}/runs",
            "reason": ";".join(event_integrity_reasons),
        }]
    fs_state = _fs_state(processed_root, b, e)
    actions: list[dict[str, str]] = []
    if not fs_state["sampling_rate_verified"]:
        actions.append({
            "action_id": "PROVIDE_SAMPLING_RATE",
            "label": "填写并验证采样频率（参数注册表；绝不猜测）",
            "route": f"/experiments/{b}/{e}/overview",
        })
    else:
        actions.append({
            "action_id": "CALIBRATE_TOF_GATES",
            "label": "标定并冻结 TOF 双闸门（波形工作台）",
            "route": f"/experiments/{b}/{e}/waveform",
        })
    actions.append({
        "action_id": "REVIEW_ALIGNMENT",
        "label": "复核同步对齐与 Feature–Target 预览（特征分析）",
        "route": f"/experiments/{b}/{e}/analysis",
    })
    actions.append({
        "action_id": "REVIEW_MODEL_BASELINES",
        "label": "复核 Dummy-first 基线结论与限制（建模评估）",
        "route": f"/experiments/{b}/{e}/models",
    })
    return actions[:3]


def research_overview_payload(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    """Assemble the aggregate payload (pure read; no artifact writes)."""
    return {
        "schema_version": "research-overview/1.0",
        "metadata": _metadata_strip(processed_root, b, e, raw_root),
        "electrical": _electrical_snapshot(processed_root, b, e, raw_root),
        "ultrasound_tof": _tof_snapshot(processed_root, b, e, raw_root),
        "signal_quality": _signal_quality(processed_root, b, e, raw_root),
        "readiness_matrix": _readiness_matrix(processed_root, b, e, raw_root),
        "scientific_snapshot": _scientific_snapshot(processed_root, b, e, raw_root),
        "model_comparison": _model_comparison(processed_root, b, e, raw_root),
        "limitations_first_screen": _limitations_first_screen(processed_root, b, e, raw_root),
        "next_actions": _next_actions(processed_root, b, e, raw_root),
        "research_status_banner": _research_banner(processed_root, b, e, raw_root),
    }


def _research_banner(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, str]:
    if _source_provenance_invalid(processed_root, b, e, raw_root):
        return {
            "level": "BLOCKED",
            "message": "来源解析清单无效：当前结果的原始来源追溯不完整。请先重新解析并复核来源链。",
        }
    event_integrity_status, _ = _canonical_event_integrity(processed_root, b, e)
    if event_integrity_status == "INTEGRITY_BLOCKED":
        return {
            "level": "BLOCKED",
            "message": "MeasurementEvent/标签来源或工件校验失败：已隐藏依赖声电事件的科研结果，请从已验证输入重建后复核。",
        }
    fs_state = _fs_state(processed_root, b, e)
    if not fs_state["sampling_rate_verified"]:
        return {
            "level": "BLOCKED",
            "message": (
                "阻断：采样频率未在参数注册表验证（canonical TOF 未激活）。"
                "原始波形查看不受影响。"
            ),
        }
    return {
        "level": "LIMITED",
        "message": (
            "受限评估就绪：fs 已验证，TOF 规范管线可用；时间基准仍为 PROVISIONAL，"
            "SOH 依据不足，无跨电池评估。"
        ),
    }


def get_research_overview_data(
    processed_root: Path, b: str, e: str, raw_root: Path | None = None
) -> dict[str, Any]:
    validate_id(b, "battery_id")
    validate_id(e, "experiment_id")
    if not (processed_root / "electrical" / b / e).is_dir() and not (
        processed_root / "ultrasound" / b / e
    ).is_dir():
        raise APIError(ErrorCode.NOT_FOUND, "experiment artifacts not available")
    return research_overview_payload(processed_root, b, e, raw_root)

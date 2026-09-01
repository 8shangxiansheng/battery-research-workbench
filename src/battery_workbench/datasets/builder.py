"""BRW-016 leakage-safe dataset builder.

Builds separate SOC and SOH_CAPACITY dataset families from BRW-013 features +
BRW-014 labels via exact event/cycle joins. No preprocessing, no splitting,
no target leakage. Column roles are deterministic.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

from battery_workbench.datasets.joins import exact_cycle_join, exact_event_join
from battery_workbench.datasets.roles import ColumnRole, get_column_role
from battery_workbench.datasets.schemas import DatasetConfig, DatasetReport

logger = logging.getLogger(__name__)

_IDENTITY_COLS = [
    "measurement_event_id",
    "battery_id",
    "experiment_id",
    "ultrasound_asset_id",
    "frame_index_raw",
    "event_order_index",
]
# Non-numeric ultrasound columns that are provenance, not predictors.
_EXCLUDED_FROM_PREDICTORS = {"xcorr_reference_measurement_event_id", "xcorr_warning"}


def _sha256(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_columns(
    columns: list[str],
    target_name: str,
) -> tuple[list[str], list[str], list[str]]:
    """Split columns into (predictors, forbidden, context/other)."""
    predictors: list[str] = []
    forbidden: list[str] = []
    other: list[str] = []
    for col in columns:
        role = get_column_role(col)
        if col == target_name:
            other.append(col)  # target role
            continue
        if role == ColumnRole.PREDICTOR and col not in _EXCLUDED_FROM_PREDICTORS:
            predictors.append(col)
        elif role == ColumnRole.FORBIDDEN_PREDICTOR:
            forbidden.append(col)
        elif role == ColumnRole.CONTEXT and col in ("capacity_ah", "soc_dod_percent"):
            # Context columns that carry target-derivation info.
            forbidden.append(col)
        else:
            other.append(col)
    return predictors, forbidden, other


def build_soc_dataset(
    *,
    features: pd.DataFrame,
    event_labels: pd.DataFrame,
    cycle_labels: pd.DataFrame,
    config: DatasetConfig | None = None,
    analysis_slice_id: str = "",
    feature_set_id: str = "",
    label_set_id: str = "",
    parameter_set_id: str = "",
    feature_set_path: Path | None = None,
    label_set_path: Path | None = None,
    selected_features: list[str] | None = None,
) -> tuple[DatasetReport, pd.DataFrame]:
    """Build the SOC dataset family.

    ``selected_features`` (V2): explicit predictor list. When ``None``, the
    legacy BRW-016 behavior is preserved (all numeric ultrasound features).
    """
    from battery_workbench.datasets.ids import build_dataset_id

    config = config or DatasetConfig()
    target = "soc_reference_percent"

    joined = exact_event_join(features, event_labels, report_surplus=False)
    if isinstance(joined, tuple):  # pragma: no cover - report_surplus=False never returns tuple
        raise TypeError("exact_event_join returned unexpected tuple")
    joined = exact_cycle_join(joined, cycle_labels)

    predictors, forbidden, _ = _classify_columns(list(joined.columns), target)
    # Remove non-numeric / target-derivation columns from predictors.
    predictors = [c for c in predictors if c not in ("xcorr_reference_measurement_event_id")]
    if selected_features is not None:
        # Target-leakage guard first: an explicitly requested forbidden column
        # is rejected even if it is absent from the data (not bypassable).
        for col in selected_features:
            assert get_column_role(col) != ColumnRole.FORBIDDEN_PREDICTOR, (
                f"target-leakage predictor selected: {col}"
            )
        # Explicit selection: predictors = selected ∩ available in joined.
        available = set(joined.columns)
        predictors = [c for c in selected_features if c in available and c != target]

    # Eligibility: eligible label + non-null target + usable feature + non-null predictors.
    breakdown: dict[str, int] = {}
    eligible_mask = joined["soc_label_eligible"] == True
    breakdown["label_ineligible"] = int((~eligible_mask).sum())
    mask = eligible_mask
    mask &= joined[target].notna()
    breakdown["target_null"] = int((~joined[target].notna()).sum())
    mask &= joined["analysis_eligible"] == True
    breakdown["analysis_ineligible"] = int((~(joined["analysis_eligible"] == True)).sum())
    mask &= joined["feature_status"] == "READY"
    breakdown["feature_ineligible"] = int((~(joined["feature_status"] == "READY")).sum())
    for col in predictors:
        null_count = int(joined[col].isna().sum())
        if null_count:
            breakdown.setdefault("predictor_null", 0)
            breakdown["predictor_null"] += null_count
            mask &= joined[col].notna()

    eligible_df = joined[mask].copy()
    excluded = len(joined) - len(eligible_df)

    # Cross-target isolation: SOC dataset never carries the SOH target.
    soh_cols = [c for c in eligible_df.columns if c.startswith("soh_")]
    eligible_df = eligible_df.drop(columns=soh_cols, errors="ignore")

    # Target-leakage guard: no forbidden predictor may appear as a predictor.
    for col in forbidden:
        assert col not in predictors, f"target-leakage predictor in SOC: {col}"

    feature_checksum = _sha256(feature_set_path) if feature_set_path else ""
    label_checksum = _sha256(label_set_path) if label_set_path else ""
    dataset_id = build_dataset_id(
        feature_set_id=feature_set_id,
        label_set_id=label_set_id,
        parameter_set_id=parameter_set_id,
        target_name=target,
        config=config,
        feature_checksum=feature_checksum,
        label_checksum=label_checksum,
        selected_features=selected_features,
    )

    eligible_soc = eligible_df[target].dropna()
    battery_count = (
        eligible_df["battery_group_id"].nunique()
        if "battery_group_id" in eligible_df.columns
        else 0
    )

    report = DatasetReport(
        dataset_id=dataset_id,
        dataset_family="SOC",
        target_name=target,
        dataset_status="READY_WITH_LIMITATIONS"
        if len(eligible_df) > 0 and battery_count == 1
        else ("EMPTY" if len(eligible_df) == 0 else "READY_FOR_SPLIT"),
        battery_id=eligible_df["battery_id"].iloc[0] if len(eligible_df) else "",
        experiment_id=eligible_df["experiment_id"].iloc[0] if len(eligible_df) else "",
        analysis_slice_id=analysis_slice_id,
        feature_set_id=feature_set_id,
        label_set_id=label_set_id,
        parameter_set_id=parameter_set_id,
        parameter_dependency=config.parameter_dependency,
        input_feature_rows=len(features),
        input_label_rows=len(event_labels),
        joined_rows=len(joined),
        eligible_rows=len(eligible_df),
        excluded_rows=excluded,
        exclusion_breakdown=breakdown,
        predictor_columns=sorted(predictors),
        forbidden_predictor_columns=sorted(forbidden),
        selected_features=list(selected_features) if selected_features is not None else None,
        target_column=target,
        battery_group_count=int(eligible_df["battery_group_id"].nunique())
        if "battery_group_id" in eligible_df.columns
        else 0,
        experiment_group_count=int(eligible_df["experiment_group_id"].nunique())
        if "experiment_group_id" in eligible_df.columns
        else 0,
        cycle_group_count=int(eligible_df["cycle_group_id"].nunique())
        if "cycle_group_id" in eligible_df.columns
        else 0,
        target_range=[float(eligible_soc.min()), float(eligible_soc.max())]
        if len(eligible_soc)
        else [],
        soc_label_temporality=eligible_df["soc_label_temporality"].iloc[0]
        if len(eligible_df)
        else None,
        soc_formula_version=eligible_df["soc_formula_version"].iloc[0]
        if len(eligible_df)
        else None,
        frame_random_split_prohibited=True,
        limitations=[
            "SOC is RETROSPECTIVE_SEGMENT_NORMALIZED — not online-causal",
            "single battery — cross-battery generalization not evaluable",
            "2 cycle groups — grouped CV still possible but limited",
        ],
        warnings=[],
    )
    return report, eligible_df


def build_soh_dataset(
    *,
    features: pd.DataFrame,
    event_labels: pd.DataFrame,
    cycle_labels: pd.DataFrame,
    config: DatasetConfig | None = None,
    analysis_slice_id: str = "",
    feature_set_id: str = "",
    label_set_id: str = "",
    parameter_set_id: str = "",
    feature_set_path: Path | None = None,
    label_set_path: Path | None = None,
    selected_features: list[str] | None = None,
) -> tuple[DatasetReport, pd.DataFrame]:
    """Build the SOH_CAPACITY dataset family."""
    from battery_workbench.datasets.ids import build_dataset_id

    config = config or DatasetConfig()
    target = "soh_capacity_reference_percent"

    joined = exact_event_join(features, event_labels, report_surplus=False)
    if isinstance(joined, tuple):  # pragma: no cover - report_surplus=False never returns tuple
        raise TypeError("exact_event_join returned unexpected tuple")
    joined = exact_cycle_join(joined, cycle_labels)

    # independent_soh_group_id defaults to cycle_group_id.
    if "independent_soh_group_id" not in joined.columns:
        joined["independent_soh_group_id"] = joined["cycle_group_id"]

    predictors, forbidden, _ = _classify_columns(list(joined.columns), target)
    predictors = [c for c in predictors if c not in _EXCLUDED_FROM_PREDICTORS]
    if selected_features is not None:
        # Target-leakage guard first (not bypassable, see build_soc_dataset).
        for col in selected_features:
            assert get_column_role(col) != ColumnRole.FORBIDDEN_PREDICTOR, (
                f"target-leakage predictor selected: {col}"
            )
        available = set(joined.columns)
        predictors = [c for c in selected_features if c in available and c != target]
    # SOH-specific forbidden: cycle index + capacity retention/formula fields.
    for col in ("cycle_index_raw", "capacity_retention_percent", "soh_reference_cycle_index"):
        if col in predictors:
            predictors.remove(col)
        if col not in forbidden:
            forbidden.append(col)

    breakdown: dict[str, int] = {}
    mask = joined["soh_label_eligible"] == True
    breakdown["label_ineligible"] = int((~mask).sum())
    mask &= joined[target].notna()
    mask &= joined["analysis_eligible"] == True
    mask &= joined["feature_status"] == "READY"
    for col in predictors:
        mask &= joined[col].notna()

    eligible_df = joined[mask].copy()
    excluded = len(joined) - len(eligible_df)

    # Cross-target isolation: SOH dataset never carries the SOC target.
    soc_cols = [
        c
        for c in eligible_df.columns
        if c.startswith(
            (
                "soc_reference",
                "soc_label",
                "soc_formula",
                "soc_anchor",
                "soc_integral",
                "soc_direction",
            )
        )
    ]
    eligible_df = eligible_df.drop(columns=soc_cols, errors="ignore")

    feature_checksum = _sha256(feature_set_path) if feature_set_path else ""
    label_checksum = _sha256(label_set_path) if label_set_path else ""
    dataset_id = build_dataset_id(
        feature_set_id=feature_set_id,
        label_set_id=label_set_id,
        parameter_set_id=parameter_set_id,
        target_name=target,
        config=config,
        feature_checksum=feature_checksum,
        label_checksum=label_checksum,
        selected_features=selected_features,
    )

    cycle_count = int(eligible_df["cycle_group_id"].nunique()) if len(eligible_df) else 0
    distinct_soh = eligible_df[target].nunique() if len(eligible_df) else 0
    ready = distinct_soh >= config.min_soh_independent_states

    report = DatasetReport(
        dataset_id=dataset_id,
        dataset_family="SOH_CAPACITY",
        target_name=target,
        dataset_status="READY_FOR_SPLIT"
        if ready
        else ("EMPTY" if len(eligible_df) == 0 else "NOT_READY_FOR_MODEL_EVALUATION"),
        battery_id=eligible_df["battery_id"].iloc[0] if len(eligible_df) else "",
        experiment_id=eligible_df["experiment_id"].iloc[0] if len(eligible_df) else "",
        analysis_slice_id=analysis_slice_id,
        feature_set_id=feature_set_id,
        label_set_id=label_set_id,
        parameter_set_id=parameter_set_id,
        parameter_dependency=config.parameter_dependency,
        input_feature_rows=len(features),
        input_label_rows=len(event_labels),
        joined_rows=len(joined),
        eligible_rows=len(eligible_df),
        excluded_rows=excluded,
        exclusion_breakdown=breakdown,
        predictor_columns=sorted(predictors),
        forbidden_predictor_columns=sorted(forbidden),
        selected_features=list(selected_features) if selected_features is not None else None,
        target_column=target,
        battery_group_count=int(eligible_df["battery_group_id"].nunique())
        if len(eligible_df)
        else 0,
        experiment_group_count=int(eligible_df["experiment_group_id"].nunique())
        if len(eligible_df)
        else 0,
        cycle_group_count=cycle_count,
        distinct_soh_values=distinct_soh,
        frame_random_split_prohibited=True,
        limitations=[
            "EVENT ROW COUNT IS NOT INDEPENDENT SOH SAMPLE COUNT",
            f"only {distinct_soh} distinct SOH values from {cycle_count} cycle groups — NOT ready for supervised modeling",
            "requires more ageing cycles / multiple batteries / RPT before model evaluation",
        ],
        warnings=[],
    )
    return report, eligible_df

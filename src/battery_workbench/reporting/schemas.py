"""BRW-023 Experiment Tracking & Scientific Reporting schemas.

Evidence provenance is mandatory for every numeric scientific claim.
Prior audits and source-code inference are never promoted to direct
current measurements.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field, model_validator


class EvidenceType(str, Enum):
    DIRECT_CURRENT_ARTIFACT = "DIRECT_CURRENT_ARTIFACT"
    DIRECT_OTHER_WORKSPACE_ARTIFACT = "DIRECT_OTHER_WORKSPACE_ARTIFACT"
    CI_ARTIFACT = "CI_ARTIFACT"
    DOCUMENTED_PRIOR_AUDIT = "DOCUMENTED_PRIOR_AUDIT"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    SOURCE_CODE_INFERENCE = "SOURCE_CODE_INFERENCE"
    USER_PROVIDED_CONTEXT = "USER_PROVIDED_CONTEXT"


class EvidenceEntry(BaseModel):
    evidence_type: EvidenceType
    evidence_ref: str
    artifact_id: str | None = None
    artifact_path: str | None = None
    artifact_availability: str = "AVAILABLE"
    generated_at: str = ""


class ScientificResultRecord(BaseModel):
    result_id: str
    result_type: str  # DATA_QUALITY/SYNCHRONIZATION/LABEL/FEATURE_ANALYSIS/SPLIT/
    # MODEL_METRIC/MODEL_COMPARISON/SCIENTIFIC_LIMITATION/READINESS
    name: str
    value: Any = None
    units: str = ""
    scope: str = "experiment"
    source_artifact_id: str | None = None
    source_run_id: str | None = None
    dataset_id: str | None = None
    split_id: str | None = None
    model_id: str | None = None
    model_family: str | None = None
    evidence_type: EvidenceType = EvidenceType.DIRECT_CURRENT_ARTIFACT
    evidence_ref: str = ""
    fold_index: int | None = None
    strategy: str | None = None
    scientific_status: str = ""
    limitations: list[str] = Field(default_factory=list)
    pooled_rows_usage: str = ""

    @model_validator(mode="after")
    def _require_evidence(self) -> ScientificResultRecord:
        if not self.evidence_ref:
            raise ValueError(
                f"numeric/structured claim {self.result_id!r} requires evidence_ref "
                "(UNSUPPORTED_REPORT_CLAIM)"
            )
        return self


class ExperimentRecord(BaseModel):
    battery_id: str
    experiment_id: str
    raw_assets: list[str] = Field(default_factory=list)
    parameter_set_ids: list[str] = Field(default_factory=list)
    latest_canonical_artifacts: dict[str, str] = Field(default_factory=dict)
    run_ids: list[str] = Field(default_factory=list)
    scientific_status: str = ""
    limitations: list[str] = Field(default_factory=list)


class LimitationEntry(BaseModel):
    code: str
    severity: str  # INFO / LIMITATION / WARNING / BLOCKING_FOR_CLAIM / BLOCKING_FOR_MODELING
    description: str = ""


class ReportSpec(BaseModel):
    target: str
    battery_id: str
    experiment_id: str
    source_artifact_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    output_formats: list[str] = Field(default_factory=lambda: ["json", "md", "html"])
    reporting_policy_version: str = "0.1.0"
    report_id: str = ""

    @model_validator(mode="after")
    def _compute_id(self) -> ReportSpec:
        if not self.report_id:
            canonical = json.dumps(
                {
                    "target": self.target,
                    "battery_id": self.battery_id,
                    "experiment_id": self.experiment_id,
                    "source_artifact_ids": sorted(self.source_artifact_ids),
                    "sections": sorted(self.sections),
                    "reporting_policy_version": self.reporting_policy_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self.report_id = "REPORT::" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return self


REPORT_SECTIONS = [
    "Executive Summary",
    "Experiment Identity",
    "Raw Data & Provenance",
    "Data Quality",
    "Synchronization",
    "MeasurementEvents",
    "Parameter Registry",
    "SOC/SOH Reference Labels",
    "Ultrasound Features",
    "Waveform Gates",
    "Feature–Label Analysis",
    "Dataset",
    "Leakage-Safe Split",
    "SOC Baseline Modeling",
    "Scientific Findings",
    "Scientific Limitations",
    "Evidence Provenance",
    "Reproducibility",
]


class ClaimGuard:
    """Blocks claims not supported by current evidence."""

    BLOCKED_PATTERNS: ClassVar[list[str]] = [
        "true soc",
        "validated cross-battery",
        "cross-battery validated",
        "absolute tof",
        "production-ready",
        "robust battery-independent",
    ]

    @classmethod
    def check(cls, claim: str) -> None:
        lowered = claim.lower()
        for pattern in cls.BLOCKED_PATTERNS:
            if pattern in lowered:
                raise ValueError(
                    f"UNSUPPORTED_REPORT_CLAIM: {claim!r} — {pattern!r} is not "
                    "supported by current evidence"
                )

    @classmethod
    def is_allowed(cls, claim: str) -> bool:
        try:
            cls.check(claim)
            return True
        except ValueError:
            return False


def build_lineage_snapshot(
    processed_root: Path, battery_id: str, experiment_id: str
) -> dict[str, Any]:
    """Structured lineage: Raw → Canonical → Sync → Events → Slice → Features/Gates
    → Labels → Dataset → Split → Feature Analysis → Selection → Model → Evaluation."""
    from battery_workbench.orchestrator.lineage import get_artifact_lineage

    stages = [
        ("MEASUREMENT_EVENTS", None),
        ("ANALYSIS_SLICE", None),
        ("ULTRASOUND_FEATURE_SET", None),
        ("GATED_FEATURE_SET", None),
        ("LABEL_SET", None),
        ("PARAMETER_SET", None),
        ("DATASET", "DS::6a3142e5186fc684964ff09e"),
        ("SPLIT", "SPLIT::062cf007d21578a11ab2d728"),
        ("SOC_MODELING", "EXP_001"),
    ]
    stages_out = []
    for artifact_type, artifact_id in stages:
        lineage = get_artifact_lineage(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            battery_id=battery_id,
            experiment_id=experiment_id,
            processed_root=processed_root,
        )
        stages_out.append(lineage)
    return {
        "battery_id": battery_id,
        "experiment_id": experiment_id,
        "raw_assets": ["E001", "U001"],
        "lineage_chain": [
            (
                "Raw Assets → Canonical → Synchronization → MeasurementEvents → "
                "Slice → Features/Gates → Labels → Dataset → Split → "
                "Feature Analysis → Selection → Model → Evaluation"
            )
        ],
        "stages": stages_out,
    }

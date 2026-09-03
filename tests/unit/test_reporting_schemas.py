"""BRW-023 T01-T22: evidence provenance, tracking registries, claim guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.reporting.schemas import (
    ClaimGuard,
    EvidenceEntry,
    EvidenceType,
    ExperimentRecord,
    ReportSpec,
    ScientificResultRecord,
)

# --- T01-T04: evidence types ---


def test_t01_evidence_enum_validation() -> None:
    assert len(EvidenceType) == 7
    assert EvidenceType.DIRECT_CURRENT_ARTIFACT.value == "DIRECT_CURRENT_ARTIFACT"


def test_t02_direct_current_classification() -> None:
    e = EvidenceEntry(
        evidence_type="DIRECT_CURRENT_ARTIFACT",
        evidence_ref="data/processed/models/.../model_comparison.parquet",
        artifact_id="DS::6a3142e5186fc684964ff09e",
    )
    assert e.evidence_type == EvidenceType.DIRECT_CURRENT_ARTIFACT


def test_t03_prior_audit_classification() -> None:
    e = EvidenceEntry(
        evidence_type="DOCUMENTED_PRIOR_AUDIT",
        evidence_ref="docs/reviews/BRW-003-021-acceptance-audit.md",
    )
    assert e.evidence_type == EvidenceType.DOCUMENTED_PRIOR_AUDIT
    assert e.evidence_type != EvidenceType.DIRECT_CURRENT_ARTIFACT


def test_t04_source_inference_not_promoted() -> None:
    e = EvidenceEntry(
        evidence_type="SOURCE_CODE_INFERENCE",
        evidence_ref="src/battery_workbench/modeling/engine.py",
    )
    assert e.evidence_type != EvidenceType.DIRECT_CURRENT_ARTIFACT
    assert e.evidence_type != EvidenceType.DOCUMENTED_PRIOR_AUDIT


def test_t05_missing_artifact_marked_unavailable() -> None:
    e = EvidenceEntry(
        evidence_type="DIRECT_CURRENT_ARTIFACT",
        evidence_ref="data/processed/nonexistent/artifact.parquet",
        artifact_availability="NOT_AVAILABLE_CURRENT_ENVIRONMENT",
    )
    assert e.artifact_availability == "NOT_AVAILABLE_CURRENT_ENVIRONMENT"


# --- T06: numeric claim requires evidence ---


def test_t06_numeric_claim_requires_evidence() -> None:
    r = ScientificResultRecord(
        result_id="R::1",
        result_type="MODEL_METRIC",
        name="Dummy MAE",
        value=29.61,
        units="percent",
        scope="experiment",
        evidence_type="DIRECT_CURRENT_ARTIFACT",
        evidence_ref="model_comparison.parquet",
    )
    assert r.evidence_ref
    with pytest.raises(ValueError, match="evidence"):
        ScientificResultRecord(
            result_id="R::2",
            result_type="MODEL_METRIC",
            name="Dummy MAE",
            value=29.61,
            units="percent",
            scope="experiment",
            evidence_type="DIRECT_CURRENT_ARTIFACT",
            evidence_ref="",
        )


# --- T07: evidence roundtrip ---


def test_t07_evidence_roundtrip(tmp_path: Path) -> None:
    e = EvidenceEntry(
        evidence_type="SYNTHETIC_TEST",
        evidence_ref="tests/unit/test_x.py",
    )
    p = tmp_path / "e.json"
    p.write_text(e.model_dump_json())
    e2 = EvidenceEntry.model_validate_json(p.read_text())
    assert e2 == e


# --- T08: ExperimentRecord ---


def test_t08_experiment_record(tmp_path: Path) -> None:
    rec = ExperimentRecord(
        battery_id="CELL_001",
        experiment_id="EXP_001",
        raw_assets=["E001", "U001"],
        parameter_set_ids=["PS::99a655be1ffdffc6aa217fa8"],
        latest_canonical_artifacts={"dataset_id": "DS::6a3142e5186fc684964ff09e"},
        run_ids=["RUN::1"],
        scientific_status="READY_FOR_LIMITED_EVALUATION",
        limitations=["ONE_BATTERY_ONLY", "TWO_CYCLES_ONLY"],
    )
    assert rec.battery_id == "CELL_001"
    assert len(rec.limitations) == 2


# --- T10: ResultRecord ---


def test_t10_result_record() -> None:
    r = ScientificResultRecord(
        result_id="R::m1",
        result_type="MODEL_METRIC",
        name="Ridge macro MAE",
        value=30.87,
        units="percent",
        scope="experiment",
        evidence_type="DIRECT_CURRENT_ARTIFACT",
        evidence_ref="model_comparison.json",
        source_artifact_id="DS::6a3142e5186fc684964ff09e",
        limitations=["LIMITED_TWO_CYCLE_EVALUATION"],
    )
    assert r.result_type == "MODEL_METRIC"
    assert r.limitations == ["LIMITED_TWO_CYCLE_EVALUATION"]


# --- T11: limitation registry ---


def test_t11_limitation_registry() -> None:
    from battery_workbench.reporting.collector import DEFAULT_LIMITATIONS

    codes = [l["code"] for l in DEFAULT_LIMITATIONS]
    for required in (
        "ONE_BATTERY_ONLY",
        "TWO_CYCLES_ONLY",
        "NO_CROSS_BATTERY_EVALUATION",
        "NO_INDEPENDENT_VALIDATION_GROUP",
        "NO_HYPERPARAMETER_TUNING",
        "SOH_INDEPENDENT_STATES_TOO_FEW",
        "TOF_UNAVAILABLE_OR_BLOCKED",
        "FEATURE_SELECTION_STABILITY_LIMITED",
        "LIMITED_CROSS_CYCLE_GENERALIZATION",
        "PROVISIONAL_TIMEBASE",
        "RETROSPECTIVE_SOC_REFERENCE",
    ):
        assert required in codes, f"missing limitation: {required}"
    severities = {l["code"]: l["severity"] for l in DEFAULT_LIMITATIONS}
    assert severities["ONE_BATTERY_ONLY"] == "BLOCKING_FOR_CLAIM"
    assert severities["PROVISIONAL_TIMEBASE"] in {"INFO", "LIMITATION"}


# --- T12: lineage snapshot ---


def test_t12_lineage_snapshot_structure(tmp_path: Path) -> None:
    from battery_workbench.reporting.schemas import build_lineage_snapshot as build_full_lineage

    lineage = build_full_lineage(Path("data/processed"), "CELL_001", "EXP_001")
    assert "raw_assets" in lineage
    assert len(lineage.get("stages", [])) >= 8


# --- T13: IDs preserved ---


def test_t13_ids_preserved_in_lineage(tmp_path: Path) -> None:
    from battery_workbench.reporting.schemas import build_lineage_snapshot as build_full_lineage

    lineage = build_full_lineage(Path("data/processed"), "CELL_001", "EXP_001")
    text = json.dumps(lineage)
    for known_id in (
        "DS::6a3142e5186fc684964ff09e",
        "LB::752466f98a93a4d1b44da358",
        "SPLIT::062cf007d21578a11ab2d728",
        "GATESET::8633ce421ad5e26fe686",
    ):
        assert known_id in text, f"lineage missing {known_id}"


# --- T14-T16: report_id ---


def test_t14_deterministic_report_id() -> None:
    s1 = ReportSpec(target="soc_reference_percent", battery_id="CELL_001", experiment_id="EXP_001")
    s2 = ReportSpec(target="soc_reference_percent", battery_id="CELL_001", experiment_id="EXP_001")
    assert s1.report_id == s2.report_id
    assert s1.report_id.startswith("REPORT::")


def test_t15_source_change_changes_id() -> None:
    s1 = ReportSpec(
        target="soc_reference_percent",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        source_artifact_ids=["DS::a"],
    )
    s2 = ReportSpec(
        target="soc_reference_percent",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        source_artifact_ids=["DS::b"],
    )
    assert s1.report_id != s2.report_id


def test_t16_styling_only_no_id_change() -> None:
    s1 = ReportSpec(
        target="soc_reference_percent",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        output_formats=["json", "md", "html"],
    )
    s2 = ReportSpec(
        target="soc_reference_percent",
        battery_id="CELL_001",
        experiment_id="EXP_001",
        output_formats=["json"],
    )
    assert s1.report_id == s2.report_id  # styling/format doesn't change scientific id


# --- T17-T20: report sections & formats ---


def test_t17_required_sections() -> None:
    from battery_workbench.reporting.schemas import REPORT_SECTIONS

    for s in (
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
    ):
        assert s in REPORT_SECTIONS, f"missing section: {s}"


def test_t18_json_report(tmp_path: Path) -> None:
    from battery_workbench.reporting.report import generate_report_files

    paths = generate_report_files(
        report={"sections": {}, "report_id": "REPORT::test"},
        battery_id="CELL_001",
        experiment_id="EXP_001",
        report_id="REPORT::test",
        output_root=tmp_path,
    )
    assert Path(paths["report_json"]).exists()
    data = json.loads(Path(paths["report_json"]).read_text())
    assert "report_id" in data


def test_t19_markdown_report(tmp_path: Path) -> None:
    from battery_workbench.reporting.report import generate_report_files

    paths = generate_report_files(
        report={"sections": {}},
        battery_id="CELL_001",
        experiment_id="EXP_001",
        report_id="REPORT::test",
        output_root=tmp_path,
    )
    assert Path(paths["report_md"]).exists()
    assert "# " in Path(paths["report_md"]).read_text()


def test_t20_html_report(tmp_path: Path) -> None:
    from battery_workbench.reporting.report import generate_report_files

    paths = generate_report_files(
        report={"sections": {}},
        battery_id="CELL_001",
        experiment_id="EXP_001",
        report_id="REPORT::test",
        output_root=tmp_path,
    )
    assert Path(paths["report_html"]).exists()
    assert "<html>" in Path(paths["report_html"]).read_text()


# --- Claim Guard T21-T26 ---


def test_t21_derived_soc_wording_allowed() -> None:
    assert ClaimGuard.is_allowed("derived/reference SOC (protocol-anchored label)")


def test_t22_true_soc_claim_blocked() -> None:
    with pytest.raises(ValueError, match="true SOC"):
        ClaimGuard.check("model predicts true SOC")


def test_t23_limited_cross_cycle_wording_allowed() -> None:
    assert ClaimGuard.is_allowed("limited within-battery cross-cycle evaluation")


def test_t24_cross_battery_validated_claim_blocked() -> None:
    with pytest.raises(ValueError, match="cross-battery"):
        ClaimGuard.check("validated cross-battery SOC model")


def test_t25_tof_blocked_wording_allowed() -> None:
    assert ClaimGuard.is_allowed("TOF currently blocked / unavailable")


def test_t26_absolute_tof_claim_blocked() -> None:
    with pytest.raises(ValueError, match="absolute TOF"):
        ClaimGuard.check("measured absolute TOF")

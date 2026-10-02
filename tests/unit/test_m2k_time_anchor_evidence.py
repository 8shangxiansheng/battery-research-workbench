from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.synchronization.anchors import build_assessment
from battery_workbench.synchronization.evidence import collect_candidates
from battery_workbench.synchronization.m2k_evidence import (
    M2KAcquisitionStartEvidence,
    M2KTimeEvidenceError,
    read_m2k_acquisition_start,
)
from battery_workbench.synchronization.schemas import TimeAnchorConfig
from battery_workbench.synchronization.service import assess_experiment_time_anchors


def test_reads_explicit_date_acquis_without_timezone_inference(tmp_path: Path) -> None:
    config = tmp_path / "M2kConfig.xml"
    config.write_text(
        '<M2kData dateAcquis="06-01-2024 09:49:56"><ControlReporting '
        'dateAcquis="06-01-2024 09:49:56" /></M2kData>',
        encoding="utf-8",
    )

    evidence = read_m2k_acquisition_start(config)

    assert evidence.anchor_datetime.isoformat() == "2024-01-06T09:49:56"
    assert evidence.source_type == "M2K_CONFIG_DATE_ACQUIS"
    assert evidence.source_ref == "M2kConfig.xml#M2kData/@dateAcquis"
    assert evidence.source_sha256 == hashlib.sha256(config.read_bytes()).hexdigest()
    assert evidence.timezone_known is False


def test_explicit_m2k_candidate_wins_over_manifest_and_stays_provisional() -> None:
    m2k_start = datetime(2024, 1, 6, 9, 49, 56)
    candidates, evidence = collect_candidates(
        asset_id="U_CW1_1_2",
        modality="ultrasound",
        file_start_time=datetime(2024, 1, 6, 9, 52, 31),
        m2k_evidence=M2KAcquisitionStartEvidence(
            anchor_datetime=m2k_start,
            source_ref="batteries/CELL/EXP/M2kConfig.xml#M2kData/@dateAcquis",
        ),
    )

    assessment = build_assessment(
        asset_id="U_CW1_1_2",
        modality="ultrasound",
        elapsed_min_s=0.031217,
        elapsed_max_s=39980.03,
        candidates=candidates,
        evidence=evidence,
    )

    assert assessment.selected_anchor_id == "U_CW1_1_2-m2k-config"
    assert assessment.anchor_status == "CONFLICTING"
    assert not assessment.validated_sync
    assert len(assessment.conflicts) == 1
    assert assessment.conflicts[0].source_type == "MANIFEST_FILE_START"
    assert assessment.candidates[0].timezone_known is False


@pytest.mark.parametrize(
    "xml",
    [
        "<M2kData />",
        '<M2kData dateAcquis="not-a-date" />',
        (
            '<M2kData dateAcquis="06-01-2024 09:49:56"><ControlReporting '
            'dateAcquis="06-01-2024 09:50:00" /></M2kData>'
        ),
    ],
)
def test_rejects_missing_invalid_or_conflicting_acquisition_times(tmp_path: Path, xml: str) -> None:
    config = tmp_path / "M2kConfig.xml"
    config.write_text(xml, encoding="utf-8")

    with pytest.raises(M2KTimeEvidenceError):
        read_m2k_acquisition_start(config)


def test_manifest_explicit_sidecar_is_loaded_as_per_asset_candidate(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifests = raw_root / "manifests"
    sidecar = raw_root / "batteries/CELL/EXP/ultrasound/M2kConfig.xml"
    processed = tmp_path / "processed"
    manifests.mkdir(parents=True)
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text('<M2kData dateAcquis="06-01-2024 09:49:56" />', encoding="utf-8")
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\nEXP,CELL,,,,\n",
        encoding="utf-8",
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,"
        "time_anchor_metadata_path\n"
        "U1,CELL,EXP,ultrasound,batteries/CELL/EXP/ultrasound/frame.txt,,"
        "batteries/CELL/EXP/ultrasound/M2kConfig.xml\n",
        encoding="utf-8",
    )
    frames_dir = processed / "ultrasound/CELL/EXP"
    frames_dir.mkdir(parents=True)
    pd.DataFrame({"ultrasound_asset_id": ["U1"], "elapsed_time_s": [0.031]}).to_parquet(
        frames_dir / "frames.parquet", index=False
    )

    report = assess_experiment_time_anchors(
        "EXP",
        battery_id="CELL",
        processed_root=processed,
        manifest_root=manifests,
        config=TimeAnchorConfig(),
    )

    asset = report.assets[0]
    assert asset["selected_anchor_id"] == "U1-m2k-config"
    assert asset["anchor_status"] == "PROVISIONAL"
    assert asset["candidates"][0]["timezone_known"] is False
    assert asset["candidates"][0]["source_ref"] == (
        "batteries/CELL/EXP/ultrasound/M2kConfig.xml#M2kData/@dateAcquis"
    )
    m2k_item = next(
        item for item in asset["evidence"] if item["source_type"] == "M2K_CONFIG_DATE_ACQUIS"
    )
    assert len(m2k_item["source_sha256"]) == 64

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.api import research_overview


def _write_event_label_artifacts(
    root: Path, event_ids: list[str], label_ids: list[str]
) -> None:
    event_dir = root / "multimodal/CELL_A/EXP_A"
    label_dir = root / "labels/CELL_A/EXP_A"
    event_dir.mkdir(parents=True)
    label_dir.mkdir(parents=True)
    pd.DataFrame(
        {"measurement_event_id": event_ids, "analysis_eligible": [True] * len(event_ids)}
    ).to_parquet(event_dir / "measurement_events.parquet", index=False)
    pd.DataFrame(
        {
            "measurement_event_id": label_ids,
            "soc_reference_percent": [50.0] * len(label_ids),
        }
    ).to_parquet(label_dir / "event_labels.parquet", index=False)
    (event_dir / "measurement_event_manifest.json").write_text("{}", encoding="utf-8")
    (label_dir / "label_manifest.json").write_text("{}", encoding="utf-8")


@pytest.mark.parametrize(
    ("event_ids", "label_ids", "expected_reason"),
    [
        (
            ["ME::CELL_A::EXP_A::U1::0"],
            ["ME::CELL_A::EXP_A::U1::0", "ME::CELL_A::EXP_A::U1::0"],
            "MEASUREMENT_EVENT_ID_DUPLICATE",
        ),
        (
            ["ME::CELL_A::EXP_A::U1::0", "ME::CELL_A::EXP_A::U1::0"],
            ["ME::CELL_A::EXP_A::U1::0"],
            "MEASUREMENT_EVENT_ID_DUPLICATE",
        ),
        (
            ["ME::CELL_A::EXP_A::U1::0"],
            [" ME::CELL_A::EXP_A::U1::0 "],
            "MEASUREMENT_EVENT_ID_INVALID",
        ),
    ],
)
def test_overview_integrity_blocks_invalid_event_label_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_ids: list[str],
    label_ids: list[str],
    expected_reason: str,
) -> None:
    _write_event_label_artifacts(tmp_path, event_ids, label_ids)
    monkeypatch.setattr(
        research_overview,
        "assert_processed_artifact_integrity",
        lambda *_args, **_kwargs: {},
    )

    status, reasons = research_overview._canonical_event_integrity(
        tmp_path, "CELL_A", "EXP_A"
    )

    assert status == "INTEGRITY_BLOCKED"
    assert expected_reason in reasons


def test_overview_integrity_allows_valid_partial_label_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_event_label_artifacts(
        tmp_path,
        ["ME::CELL_A::EXP_A::U1::0", "ME::CELL_A::EXP_A::U1::1"],
        ["ME::CELL_A::EXP_A::U1::0"],
    )
    monkeypatch.setattr(
        research_overview,
        "assert_processed_artifact_integrity",
        lambda *_args, **_kwargs: {},
    )

    status, reasons = research_overview._canonical_event_integrity(
        tmp_path, "CELL_A", "EXP_A"
    )

    assert (status, reasons) == ("CURRENT", [])

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from battery_workbench.api import workflow_context


@pytest.mark.parametrize(
    ("event_ids", "label_ids"),
    [
        (["ME::CELL_A::EXP_A::U1::0"], ["ME::CELL_A::EXP_A::U1::0"] * 2),
        (["ME::CELL_A::EXP_A::U1::0"] * 2, ["ME::CELL_A::EXP_A::U1::0"]),
        ([None], ["ME::CELL_A::EXP_A::U1::0"]),
        (["ME::CELL_A::EXP_A::U1::0"], [" ME::CELL_A::EXP_A::U1::0 "]),
    ],
)
def test_target_step_blocks_non_unique_or_invalid_event_label_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_ids: list[str | None],
    label_ids: list[str],
) -> None:
    events_dir = tmp_path / "multimodal/CELL_A/EXP_A"
    labels_dir = tmp_path / "labels/CELL_A/EXP_A"
    events_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "measurement_event_id": event_ids,
            "analysis_eligible": [True] * len(event_ids),
        }
    ).to_parquet(events_dir / "measurement_events.parquet", index=False)
    pd.DataFrame(
        {
            "measurement_event_id": label_ids,
            "soc_reference_percent": [50.0] * len(label_ids),
        }
    ).to_parquet(labels_dir / "event_labels.parquet", index=False)

    monkeypatch.setattr(
        workflow_context,
        "assert_processed_artifact_integrity",
        lambda *_args, **_kwargs: {},
    )

    result = workflow_context._target_step(tmp_path, "CELL_A", "EXP_A")

    assert result["status"] == "BLOCKED"
    assert result["committed"] is None
    assert result["blocking"]["blocking_code"] == "TARGET_EVENT_LABEL_JOIN_INVALID"
    assert result["blocking"]["required_action"] == (
        "REBUILD_MEASUREMENT_EVENTS_AND_LABELS_FROM_VERIFIED_INPUTS"
    )


def test_target_step_keeps_valid_unlabeled_events_in_coverage_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events_dir = tmp_path / "multimodal/CELL_A/EXP_A"
    labels_dir = tmp_path / "labels/CELL_A/EXP_A"
    events_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "measurement_event_id": [
                "ME::CELL_A::EXP_A::U1::0",
                "ME::CELL_A::EXP_A::U1::1",
            ],
            "analysis_eligible": [True, True],
        }
    ).to_parquet(events_dir / "measurement_events.parquet", index=False)
    pd.DataFrame(
        {
            "measurement_event_id": ["ME::CELL_A::EXP_A::U1::0"],
            "soc_reference_percent": [50.0],
        }
    ).to_parquet(labels_dir / "event_labels.parquet", index=False)
    monkeypatch.setattr(
        workflow_context,
        "assert_processed_artifact_integrity",
        lambda *_args, **_kwargs: {},
    )

    result = workflow_context._target_step(tmp_path, "CELL_A", "EXP_A")

    assert result["status"] == "COMPLETE"
    assert result["committed"]["coverage_eligible"] == 1

"""Workflow model freshness is bound to the exact committed split."""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.api.workflow_context import (
    _models_for_split,
    _report_split_id,
    _split_latest,
)


def test_models_from_an_older_split_do_not_satisfy_current_chain(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    dataset_id, current_split_id = "DS::TEST", "SPLIT::CURRENT"
    older_split_id = "SPLIT::OLDER"

    def add_model(split_id: str, model_id: str) -> None:
        directory = root / "models" / battery_id / experiment_id / dataset_id / split_id / model_id
        directory.mkdir(parents=True)
        (directory / "model.joblib").write_bytes(b"model")
        (directory / "held_out_predictions.parquet").write_bytes(b"predictions")
        import hashlib

        (directory / "model_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_id": dataset_id,
                    "split_id": split_id,
                    "model_id": model_id,
                    "output_checksums": {
                        "model": hashlib.sha256(b"model").hexdigest(),
                        "held_out_predictions": hashlib.sha256(b"predictions").hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )

    add_model(older_split_id, "MODEL::OLD")
    add_model(current_split_id, "MODEL::CURRENT")

    current_models = _models_for_split(
        root, battery_id, experiment_id, dataset_id, current_split_id
    )
    models, integrity_reasons = current_models
    assert [model["model_id"] for model in models] == ["MODEL::CURRENT"]
    assert integrity_reasons == []
    assert _models_for_split(root, battery_id, experiment_id, dataset_id, None) == ([], [])


def test_split_manifest_identity_must_match_its_directory(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    battery_id, experiment_id = "CELL_TEST", "EXP_TEST"
    split_dir = root / "splits" / battery_id / experiment_id / "DS::TEST" / "SPLIT::PATH"
    split_dir.mkdir(parents=True)
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "DS::TEST",
                "split_id": "SPLIT::DECLARED_OTHER",
                "readiness_status": "READY_FOR_LIMITED_EVALUATION",
            }
        ),
        encoding="utf-8",
    )

    assert _split_latest(root, battery_id, experiment_id, "DS::TEST") == (None, None, None)


def test_report_split_lineage_is_read_from_canonical_artifacts() -> None:
    assert _report_split_id(
        {"experiment_record": {"latest_canonical_artifacts": {"split_id": "SPLIT::1"}}}
    ) == "SPLIT::1"
    assert _report_split_id({"experiment_record": {"latest_canonical_artifacts": {}}}) is None

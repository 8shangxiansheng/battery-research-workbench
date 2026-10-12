from battery_workbench.reporting.collector import _model_fold_coverage_status


def test_reporting_marks_partial_model_set_as_diagnostic_only() -> None:
    status, limitations = _model_fold_coverage_status(
        {"fold_coverage": {"complete": False, "missing_fold_indices": [2]}}
    )

    assert status == "PARTIAL_FOLD_COVERAGE"
    assert "DO_NOT_INTERPRET_AS_COMPLETE_SPLIT_EVALUATION" in limitations


def test_reporting_keeps_complete_split_limited_evaluation_status() -> None:
    status, limitations = _model_fold_coverage_status(
        {"fold_coverage": {"complete": True, "missing_fold_indices": []}}
    )

    assert status == "READY_FOR_LIMITED_EVALUATION"
    assert limitations == []


def test_reporting_does_not_assume_legacy_model_set_is_complete() -> None:
    status, limitations = _model_fold_coverage_status({})

    assert status == "PARTIAL_FOLD_COVERAGE"
    assert limitations

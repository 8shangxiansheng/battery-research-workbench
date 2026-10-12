from battery_workbench.modeling.persistence import fold_coverage


def test_fold_coverage_marks_complete_split() -> None:
    result = fold_coverage([1, 2], [2, 1, 1])

    assert result == {
        "expected_fold_indices": [1, 2],
        "evaluated_fold_indices": [1, 2],
        "missing_fold_indices": [],
        "unexpected_fold_indices": [],
        "complete": True,
        "readiness": "READY_FOR_LIMITED_EVALUATION",
    }


def test_fold_coverage_marks_missing_and_unexpected_folds() -> None:
    result = fold_coverage([1, 2], [1, 3])

    assert result["expected_fold_indices"] == [1, 2]
    assert result["evaluated_fold_indices"] == [1, 3]
    assert result["missing_fold_indices"] == [2]
    assert result["unexpected_fold_indices"] == [3]
    assert result["complete"] is False
    assert result["readiness"] == "PARTIAL_FOLD_COVERAGE"


def test_empty_expected_folds_are_not_reported_complete() -> None:
    result = fold_coverage([], [])

    assert result["complete"] is False
    assert result["readiness"] == "PARTIAL_FOLD_COVERAGE"

"""P4 robustness statistics: uncertainty intervals, multiplicity control and
pseudo-replication diagnostics on synthetic data with known ground truth.

Acceptance is deliberately synthetic: each case encodes a property that must be
detectable regardless of the real CELL_001 sample, so these tests cannot be
satisfied by a nicer-looking number on one battery.

Wording: association / monotonic association / observed relationship only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_workbench.feature_analysis.engine import (
    benjamini_hochberg,
    bootstrap_correlation_interval,
    effective_independent_units,
    fisher_z_interval,
    pseudo_replication_diagnostic,
    subgroup_effect_split,
)

# ---------------------------------------------------------------- intervals


def test_fisher_z_interval_brackets_point_estimate() -> None:
    lo, hi = fisher_z_interval(0.6, n=50)
    assert lo < 0.6 < hi
    assert -1.0 <= lo and hi <= 1.0


def test_fisher_z_interval_widens_as_n_shrinks() -> None:
    narrow_lo, narrow_hi = fisher_z_interval(0.5, n=200)
    wide_lo, wide_hi = fisher_z_interval(0.5, n=10)
    assert (wide_hi - wide_lo) > (narrow_hi - narrow_lo)


def test_fisher_z_interval_requires_enough_rows() -> None:
    assert fisher_z_interval(0.5, n=2) == (None, None)
    assert fisher_z_interval(None, n=100) == (None, None)
    # A perfect correlation has an infinite Fisher z; the interval must not
    # fabricate finite bounds.
    assert fisher_z_interval(1.0, n=100) == (None, None)


def test_bootstrap_interval_is_seeded_and_deterministic() -> None:
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=60))
    y = pd.Series(0.7 * x + rng.normal(size=60))

    first = bootstrap_correlation_interval(x, y, method="pearson", seed=7)
    second = bootstrap_correlation_interval(x, y, method="pearson", seed=7)
    other = bootstrap_correlation_interval(x, y, method="pearson", seed=8)

    assert first == second, "same seed must reproduce identical bounds"
    assert first != other, "different seeds must not silently reuse bounds"
    lo, hi = first
    assert lo is not None and hi is not None and lo < hi


def test_bootstrap_interval_requires_seed_and_rows() -> None:
    x = pd.Series([1.0, 2.0, 3.0])
    y = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        bootstrap_correlation_interval(x, y, method="pearson")
    assert bootstrap_correlation_interval(x, y, method="pearson", seed=1, min_rows=10) == (
        None,
        None,
    )


# ---------------------------------------------------- pseudo replication


def test_pseudo_replication_reports_nominal_vs_independent_units() -> None:
    """Many rows per cycle must not masquerade as independent observations."""
    frame = pd.DataFrame(
        {
            "cycle_group_id": ["C1"] * 20 + ["C2"] * 20 + ["C3"] * 20,
            "y": [1.0] * 20 + [2.0] * 20 + [3.0] * 20,
        }
    )

    diag = pseudo_replication_diagnostic(frame, target="y", group_column="cycle_group_id")

    assert diag["nominal_rows"] == 60
    assert diag["independent_units"] == 3
    assert diag["replication_factor"] == pytest.approx(20.0)
    assert diag["status"] == "PSEUDO_REPLICATED"
    assert "not independent" in diag["message"].lower()


def test_pseudo_replication_clean_when_one_row_per_unit() -> None:
    frame = pd.DataFrame({"cycle_group_id": ["C1", "C2", "C3"], "y": [1.0, 2.0, 3.0]})
    diag = pseudo_replication_diagnostic(frame, target="y", group_column="cycle_group_id")
    assert diag["independent_units"] == 3
    assert diag["status"] == "OK"


def test_pseudo_replication_skips_without_group_column() -> None:
    frame = pd.DataFrame({"y": [1.0, 2.0]})
    diag = pseudo_replication_diagnostic(frame, target="y", group_column="missing")
    assert diag["status"] == "GROUP_COLUMN_ABSENT"
    assert diag["independent_units"] is None


def test_effective_independent_units_counts_distinct_keys() -> None:
    frame = pd.DataFrame(
        {"cycle_group_id": ["C1", "C1", "C2", "C3", "C3"], "y": [1.0, 1.0, 2.0, 3.0, 3.0]}
    )
    assert effective_independent_units(frame, group_column="cycle_group_id") == 3


# ------------------------------------------------ subgroup effect split


def test_simpson_reversal_is_exposed_by_group_vs_within_split() -> None:
    """Pooled trend masks a reversal between group-level and within-group trends.

    Inside every group y rises with x, but the groups sit at increasing x with
    *decreasing* y, so the group-level (between-group) trend is negative while
    every within-group trend is positive. A single pooled coefficient blends the
    two; the split must expose the disagreement.
    """
    rows = []
    for group, base_x, offset in (("A", 0.0, 30.0), ("B", 20.0, 20.0), ("C", 40.0, 10.0)):
        for i in range(10):
            rows.append({"g": group, "x": base_x + float(i), "y": offset + float(i)})
    frame = pd.DataFrame(rows)

    split = subgroup_effect_split(frame, "x", "y", group_column="g")

    assert split["within_rho"] is not None and split["within_rho"] > 0.9
    # between-group trend runs opposite to the shared within-group slope
    assert split["between_rho"] is not None and split["between_rho"] < -0.9
    assert split["verdict"] == "GROUP_AND_WITHIN_DISAGREE"
    assert split["group_count"] == 3


def test_subgroup_split_agrees_when_no_confounding() -> None:
    rng = np.random.default_rng(3)
    rows = []
    for group in ("A", "B", "C"):
        for _ in range(15):
            x = rng.normal()
            rows.append({"g": group, "x": x, "y": 2.0 * x + rng.normal(scale=0.1)})
    frame = pd.DataFrame(rows)

    split = subgroup_effect_split(frame, "x", "y", group_column="g")

    assert split["within_rho"] > 0.9
    assert split["verdict"] in {"CONSISTENT", "GROUP_AND_WITHIN_AGREE"}


def test_subgroup_split_requires_group_column() -> None:
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [1.0, 2.0]})
    split = subgroup_effect_split(frame, "x", "y", group_column="absent")
    assert split["status"] == "GROUP_COLUMN_ABSENT"


# ------------------------------------------------ multiplicity (BH-FDR)


def test_benjamini_hochberg_monotone_and_bounded() -> None:
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
    assert all(0.0 <= value <= 1.0 for value in adjusted)
    # adjusted p-values never decrease as raw p-values grow
    ordered = [value for _, value in sorted(zip([0.01, 0.04, 0.03, 0.5], adjusted))]
    assert ordered == sorted(ordered)
    assert adjusted[0] == pytest.approx(0.04)


def test_benjamini_hochberg_controls_false_positives_against_null() -> None:
    """Under a global null, most raw p-values must not survive BH at q=0.05."""
    rng = np.random.default_rng(11)
    raw = list(rng.uniform(size=200))
    adjusted = benjamini_hochberg(raw, alpha=0.05)
    assert sum(1 for value in adjusted if value <= 0.05) <= 10


def test_benjamini_hochberg_keeps_strong_signal() -> None:
    adjusted = benjamini_hochberg([1e-8, 0.9, 0.95, 0.99], alpha=0.05)
    assert adjusted[0] <= 0.05


def test_benjamini_hochberg_handles_missing_values() -> None:
    adjusted = benjamini_hochberg([0.01, None, 0.5])
    assert adjusted[0] is not None
    assert adjusted[1] is None
    assert adjusted[2] is not None

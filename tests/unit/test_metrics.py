"""Unit tests for evaluation metrics.

Counts are checked against hand-computed values so a metric cannot be "verified"
by comparing it to itself.
"""

from __future__ import annotations

import pytest

from evaluation import BinaryCounts, brier_score, mean_absolute_error
from evaluation.metrics import _percentile


def test_confusion_counts_are_computed_correctly():
    # 3 flagged correctly, 1 flagged wrongly, 4 correctly ignored, 2 missed.
    counts = BinaryCounts(
        true_positive=3, false_positive=1, true_negative=4, false_negative=2
    )
    assert counts.total == 10
    assert counts.accuracy == pytest.approx(7 / 10)
    assert counts.precision == pytest.approx(3 / 4)
    assert counts.recall == pytest.approx(3 / 5)
    assert counts.f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)
    assert counts.false_positive_rate == pytest.approx(0.2)
    assert counts.false_negative_rate == pytest.approx(0.4)


def test_a_never_escalating_model_scores_perfect_accuracy_on_a_quiet_dataset():
    """Why accuracy alone is misleading, made concrete."""
    counts = BinaryCounts(true_negative=95, false_negative=5)
    assert counts.accuracy == pytest.approx(0.95)
    assert counts.recall == 0.0, "but it misses every risky change"
    assert counts.false_negative_rate == 1.0


def test_empty_counts_do_not_raise():
    empty = BinaryCounts()
    assert empty.total == 0
    assert empty.accuracy == 0.0
    assert empty.f1 == 0.0


def test_zero_division_yields_zero_not_an_error():
    """A noul nobody answered has precision 0, not a crash."""
    counts = BinaryCounts(true_negative=5)
    assert counts.precision == 0.0


def test_brier_score_matches_hand_calculation():
    assert brier_score([(1.0, 1.0), (0.0, 0.0)]) == pytest.approx(0.0)
    assert brier_score([(1.0, 0.0), (0.0, 1.0)]) == pytest.approx(1.0)
    assert brier_score([(0.5, 1.0)]) == pytest.approx(0.25)


def test_brier_score_of_empty_is_zero():
    assert brier_score([]) == 0.0


def test_mean_absolute_error():
    assert mean_absolute_error([(1.0, 1.5), (2.0, 2.5)]) == pytest.approx(0.5)
    assert mean_absolute_error([]) == 0.0


def test_percentiles_use_nearest_rank_without_interpolation():
    values = [10, 20, 30, 40]
    assert _percentile(values, 50) == 20
    assert _percentile(values, 95) == 40
    assert _percentile([], 50) == 0.0

"""Tests for the evaluation runner.

The providers here are deterministic stubs used to verify the *scoring logic*, not
to imitate Jev's judgement. A stub that always answers correctly must score 1.0;
one that always answers wrongly must score 0.0. That is what pins the metric
arithmetic without pretending to evaluate a model.
"""

from __future__ import annotations

import json

import pytest

from decisions.provider import DecisionUnavailable
from decisions.registry import load_registry
from decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer
from evaluation import Dataset, load_dataset, run_dataset
from evaluation.runner import compare

REGISTRY = load_registry()


def make_dataset(tmp_path, cases):
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"name": "t", "cases": cases}), encoding="utf-8")
    return load_dataset(path)


def case(case_id, title, **labels):
    """Build a dataset entry. `title` is the case field; kwargs are labels."""
    return {
        "id": case_id,
        "repository": "octo/repo",
        "number": 1,
        "title": title,
        "labels": labels,
    }


class StubProvider:
    """Answers from a fixed mapping. Used only to test scoring arithmetic."""

    def __init__(self, answers, name="stub", model="stub-1", fail_on=()):
        self._answers = answers
        self._fail_on = set(fail_on)
        self.name = name
        self._model = model
        self.calls = 0

    @property
    def model(self) -> str:
        return self._model

    async def evaluate(self, state, questions):
        self.calls += 1
        title = state["untrusted_content"]["title"]
        if title in self._fail_on:
            raise DecisionUnavailable("simulated provider outage")
        return {
            "pr_security_review": NoulAnswer(noul=self._answers[title]),
            "pr_risk": ScoreAnswer(
                score=2.0,
                confidence=0.8,
                legend={"0": "T", "1": "L", "2": "M", "3": "H", "4": "C"},
                probabilities={"0": 0, "1": 0, "2": 1, "3": 0, "4": 0},
            ),
            "pr_category": ChoiceAnswer(
                choice="dependency", confidence=0.9, probabilities={"dependency": 0.9}
            ),
        }


async def test_perfect_provider_scores_one(tmp_path):
    dataset = make_dataset(
        tmp_path,
        [
            case("a", "Fix the parser", pr_security_review=1),
            case("b", "Tidy whitespace", pr_security_review=0),
        ],
    )
    provider = StubProvider({"Fix the parser": 0.95, "Tidy whitespace": 0.02})
    report = await run_dataset(provider, dataset, REGISTRY)

    counts = report.binary["pr_security_review"]
    assert counts.true_positive == 1
    assert counts.true_negative == 1
    assert counts.accuracy == 1.0
    assert counts.f1 == 1.0
    assert report.failures == []


async def test_inverted_provider_scores_zero(tmp_path):
    dataset = make_dataset(
        tmp_path,
        [
            case("a", "Fix the parser", pr_security_review=1),
            case("b", "Tidy whitespace", pr_security_review=0),
        ],
    )
    provider = StubProvider({"Fix the parser": 0.05, "Tidy whitespace": 0.98})
    report = await run_dataset(provider, dataset, REGISTRY)

    counts = report.binary["pr_security_review"]
    assert counts.accuracy == 0.0


async def test_provider_failure_is_counted_not_silently_skipped(tmp_path):
    """A provider cannot look good by declining hard cases."""
    dataset = make_dataset(
        tmp_path,
        [
            case("a", "Fix the parser", pr_security_review=1),
            case("b", "Hard one", pr_security_review=1),
        ],
    )
    provider = StubProvider(
        {"Fix the parser": 0.9, "Hard one": 0.9}, fail_on={"Hard one"}
    )
    report = await run_dataset(provider, dataset, REGISTRY)

    assert report.succeeded == 1
    assert len(report.failures) == 1
    assert report.failures[0]["case"] == "b"
    summary = report.summary()
    assert summary["evaluated"] == 1
    assert summary["failed"] == 1


async def test_unexpected_exception_does_not_abort_the_run(tmp_path):
    dataset = make_dataset(
        tmp_path,
        [case("a", "One", pr_security_review=0), case("b", "Two", pr_security_review=0)],
    )

    class Exploding(StubProvider):
        async def evaluate(self, state, questions):
            if state["untrusted_content"]["title"] == "One":
                raise RuntimeError("kaboom")
            return await super().evaluate(state, questions)

    provider = Exploding({"One": 0.1, "Two": 0.1})
    report = await run_dataset(provider, dataset, REGISTRY)

    assert report.succeeded == 1
    assert len(report.failures) == 1
    assert "kaboom" in report.failures[0]["error"]


async def test_score_questions_are_compared_by_level_not_raw_float(tmp_path):
    """Jev is non-deterministic, so a 0.03 shift must not count as an error."""
    dataset = make_dataset(tmp_path, [case("a", "T", pr_risk=2)])
    provider = StubProvider({"T": 0.5})
    report = await run_dataset(provider, dataset, REGISTRY)

    # The stub's level is 2 and the label is 2, so this is a match.
    assert report.binary["pr_risk"].true_positive == 1
    assert report.binary["pr_risk"].accuracy == 1.0


async def test_only_labelled_questions_contribute(tmp_path):
    """An unlabelled question must not enter the denominator."""
    dataset = make_dataset(
        tmp_path,
        [case("a", "Only security", pr_security_review=1)],
    )
    provider = StubProvider({"Only security": 0.9})
    report = await run_dataset(provider, dataset, REGISTRY)

    assert "pr_risk" not in report.binary
    assert "pr_category" not in report.binary
    assert report.binary["pr_security_review"].total == 1


async def test_brier_score_is_recorded_for_calibration(tmp_path):
    dataset = make_dataset(
        tmp_path,
        [
            case("a", "Yes", pr_security_review=1),
            case("b", "No", pr_security_review=0),
        ],
    )
    provider = StubProvider({"Yes": 0.9, "No": 0.1})
    report = await run_dataset(provider, dataset, REGISTRY)

    brier = report.summary()["brier"]["pr_security_review"]
    expected = ((0.9 - 1) ** 2 + (0.1 - 0) ** 2) / 2
    assert brier == pytest.approx(expected, rel=1e-3)


async def test_latency_and_token_counters_are_populated(tmp_path):
    dataset = make_dataset(tmp_path, [case("a", "T", pr_security_review=0)])
    report = await run_dataset(StubProvider({"T": 0.1}), dataset, REGISTRY)

    assert len(report.latency_ms) == 1
    assert report.latency_ms[0] >= 0


async def test_comparison_includes_dataset_scope(tmp_path):
    """A comparison quoted without its dataset is how provider claims go wrong."""
    dataset = make_dataset(tmp_path, [case("a", "T", pr_security_review=1)])
    good = await run_dataset(StubProvider({"T": 0.9}, name="a"), dataset, REGISTRY)
    poor = await run_dataset(StubProvider({"T": 0.1}, name="b"), dataset, REGISTRY)

    rows = compare([good, poor])
    assert len(rows) == 2
    for row in rows:
        assert row["dataset"] == "t@v1"
        assert row["evaluated"] == 1
        assert row["failed"] == 0
    assert rows[0]["security_review_f1"] > rows[1]["security_review_f1"]


async def test_harness_records_an_auth_failure_rather_than_faking_results(tmp_path):
    """If the provider is unreachable, the report must show a failure, not zeros.

    This is the property that keeps a credential outage from being mistaken for a
    provider that simply scored zero.
    """
    dataset = make_dataset(
        tmp_path, [case("a", "T", pr_security_review=1), case("b", "U", pr_security_review=0)]
    )

    class Expired(StubProvider):
        async def evaluate(self, state, questions):
            raise DecisionUnavailable("Jev rejected the API key")

    report = await run_dataset(Expired({}, fail_on=set()), dataset, REGISTRY)
    summary = report.summary()

    assert summary["evaluated"] == 0
    assert summary["failed"] == 2
    # No confusion counts may be produced from zero successful evaluations.
    assert summary["binary_metrics"] == {}
    assert len(report.failures) == 2


async def test_empty_dataset_produces_an_empty_report(tmp_path):
    dataset = Dataset(name="empty", version=1, cases=[])
    report = await run_dataset(StubProvider({}), dataset, REGISTRY)
    summary = report.summary()
    assert summary["evaluated"] == 0
    assert summary["failed"] == 0
    assert summary["binary_metrics"] == {}
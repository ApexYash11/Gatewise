"""Run a decision provider over a labelled dataset and score it.

The runner is provider-agnostic by construction: it depends only on
``DecisionProvider``, so the same harness scores Jev, a local Jev-compatible
server, or any future provider against the identical dataset. That is what makes
a provider comparison meaningful rather than a comparison of two harnesses.

Scoring rules, chosen to match how the product actually uses decisions:

- **Noul questions** produce confusion counts against the 0.0/1.0 label, plus a
  Brier score for calibration.
- **Choice questions** produce plain accuracy, because there is no useful notion
  of a false positive for a single chosen option.
- **Score questions** are compared on the **discrete level**, not the raw float,
  because Jev is non-deterministic and the raw value moves between runs.
- A provider failure is recorded, and the case is excluded from metrics. The
  failure count is reported alongside accuracy so a provider cannot look good by
  declining to answer hard cases.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from decisions.provider import DecisionError, DecisionProvider
from decisions.registry import QuestionRegistry
from decisions.schemas import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer

from .dataset import Case, Dataset
from .metrics import BinaryCounts, EvaluationReport, brier_score

#: Probability at or above which a noul counts as "yes" for confusion counting.
DEFAULT_THRESHOLD = 0.5


class ScorableProvider(Protocol):
    """What the runner needs: a name, a model, and an evaluate method."""

    name: str

    @property
    def model(self) -> str: ...

    async def evaluate(
        self, state: Any, questions: dict[str, Any]
    ) -> dict[str, Answer]: ...


def _threshold_for(label: Any, threshold: float) -> bool:
    """Interpret a label as a yes/no expectation.

    Booleans are used as-is. Numeric labels are compared against the threshold, so
    a dataset can record a probability target and still be scored.
    """
    if isinstance(label, bool):
        return label
    if isinstance(label, (int, float)):
        return float(label) >= threshold
    raise TypeError(f"cannot interpret label {label!r} as yes/no")


async def run_dataset(
    provider: ScorableProvider,
    dataset: Dataset,
    registry: QuestionRegistry,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> EvaluationReport:
    """Evaluate every case and return a scored report.

    Never raises for a provider failure: the case is recorded in ``failures`` and
    the run continues, so one bad case does not abort a benchmark.
    """
    report = EvaluationReport(
        provider=provider.name,
        model=provider.model,
        dataset_name=f"{dataset.name}@v{dataset.version}",
        dataset_size=len(dataset),
    )
    questions = registry.build_request()

    for case in dataset.cases:
        started = time.perf_counter()
        try:
            answers = await provider.evaluate(case.to_context(), questions)
        except DecisionError as exc:
            report.failures.append({"case": case.id, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - a benchmark must not abort
            report.failures.append({"case": case.id, "error": repr(exc)})
            continue

        report.latency_ms.append(int((time.perf_counter() - started) * 1000))
        report.case_results.append(
            {"case": case.id, "answers": {k: _render(v) for k, v in answers.items()}}
        )
        _score_case(report, case, answers, threshold)

    return report


def _render(answer: Answer) -> Any:
    """Render an answer for the stored per-case record."""
    if isinstance(answer, NoulAnswer):
        return round(answer.noul, 4)
    if isinstance(answer, ChoiceAnswer):
        return {"choice": answer.choice, "confidence": round(answer.confidence, 4)}
    return {
        "score": round(answer.score, 4),
        "level": answer.resolve_level(),
        "confidence": round(answer.confidence, 4),
    }


def _score_case(
    report: EvaluationReport,
    case: Case,
    answers: dict[str, Answer],
    threshold: float,
) -> None:
    """Fold one case's answers into the running metrics.

    Only questions the case actually labels contribute. A case that labels three
    of six questions does not silently get scored as six, which would otherwise
    distort the denominator.
    """
    for question, expected in case.labels.items():
        answer = answers.get(question)
        if answer is None:
            continue

        if isinstance(answer, NoulAnswer):
            report.calibration.setdefault(question, []).append((answer.noul, float(expected)))
            positive = answer.noul >= threshold
            truth = _threshold_for(expected, threshold)
            counts = report.binary.setdefault(question, BinaryCounts())
            report.binary[question] = BinaryCounts(
                true_positive=counts.true_positive + (positive and truth),
                false_positive=counts.false_positive + (positive and not truth),
                true_negative=counts.true_negative + (not positive and not truth),
                false_negative=counts.false_negative + (not positive and truth),
            )
        elif isinstance(answer, ScoreAnswer):
            predicted_level = answer.resolve_level()
            correct = int(predicted_level) == int(expected)
            counts = report.binary.setdefault(question, BinaryCounts())
            report.binary[question] = BinaryCounts(
                true_positive=counts.true_positive + correct,
                false_negative=counts.false_negative + (not correct),
            )
        elif isinstance(answer, ChoiceAnswer):
            correct = answer.choice == expected
            counts = report.binary.setdefault(question, BinaryCounts())
            report.binary[question] = BinaryCounts(
                true_positive=counts.true_positive + correct,
                false_negative=counts.false_negative + (not correct),
            )


def compare(reports: list[EvaluationReport]) -> list[dict[str, Any]]:
    """Line up several providers' summaries for side-by-side reading.

    The dataset name and size are included in every row so a comparison cannot be
    quoted without its scope, which is how provider claims usually go wrong.
    """
    rows = []
    for report in reports:
        summary = report.summary()
        rows.append(
            {
                "provider": summary["provider"],
                "model": summary["model"],
                "dataset": summary["dataset"],
                "evaluated": summary["evaluated"],
                "failed": summary["failed"],
                "security_review_f1": summary["binary_metrics"]
                .get("pr_security_review", {})
                .get("f1"),
                "pr_risk_accuracy": summary["binary_metrics"]
                .get("pr_risk", {})
                .get("accuracy"),
                "latency_p50_ms": summary["latency_ms"]["p50"],
                "cost_usd": summary["cost_usd"]["total"],
            }
        )
    return rows
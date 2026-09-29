"""Metrics for evaluating decision providers.

Chosen deliberately, and each one has a reason to exist here:

- **Accuracy** alone is misleading for a triage system. A dataset that is 95%
  "no" would score 95% for a model that never escalates, while being useless. The
  false positive and false negative rates are reported for exactly this reason: a
  missed security review and a false alarm are different failures with different
  costs.
- **Brier score** is included because the downstream policy thresholds
  probabilities. A provider that is accurate but badly calibrated will set the
  wrong escalation threshold even though its accuracy looks fine.
- **No metric asserts bitwise equality of scores.** Jev is non-deterministic, so
  two runs of the same case differ slightly. Comparison therefore uses level
  agreement and a tolerance, never exact floats.

Every metric is computed from explicit counts, so a result can be checked by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

#: Probability differences below this count as agreement. Jev was measured moving
#: by ~0.03 between identical runs, so anything tighter would report noise.
DEFAULT_TOLERANCE = 0.05


def _ratio(numerator: float, denominator: float) -> float:
    """Divide safely; an empty denominator yields 0.0 rather than raising."""
    return numerator / denominator if denominator else 0.0


def brier_score(pairs: Sequence[tuple[float, float]]) -> float:
    """Mean squared error between predicted probabilities and outcomes.

    Lower is better. Included because policy thresholds raw probabilities, so the
    calibration of a provider matters as much as its accuracy.
    """
    if not pairs:
        return 0.0
    return sum((p - a) ** 2 for p, a in pairs) / len(pairs)


def mean_absolute_error(pairs: Sequence[tuple[float, float]]) -> float:
    if not pairs:
        return 0.0
    return sum(abs(p - a) for p, a in pairs) / len(pairs)


@dataclass(frozen=True)
class BinaryCounts:
    """Confusion counts for a yes/no decision."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def total(self) -> int:
        return (
            self.true_positive
            + self.false_positive
            + self.true_negative
            + self.false_negative
        )

    @property
    def accuracy(self) -> float:
        return _ratio(self.true_positive + self.true_negative, self.total)

    @property
    def precision(self) -> float:
        """Of the cases flagged, how many were right.

        Low precision means alert fatigue: a reviewer learns to ignore the label.
        """
        return _ratio(self.true_positive, self.true_positive + self.false_positive)

    @property
    def recall(self) -> float:
        """Of the cases that should have been flagged, how many were.

        Low recall means missed risk, the most damaging failure here.
        """
        return _ratio(self.true_positive, self.true_positive + self.false_negative)

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    @property
    def false_positive_rate(self) -> float:
        return _ratio(self.false_positive, self.false_positive + self.true_negative)

    @property
    def false_negative_rate(self) -> float:
        return _ratio(self.false_negative, self.false_negative + self.true_positive)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "total": self.total,
        }


@dataclass
class EvaluationReport:
    """Aggregated results for one provider over a dataset."""

    provider: str
    model: str
    dataset_name: str
    dataset_size: int
    case_results: list[dict[str, Any]] = field(default_factory=list)
    binary: dict[str, BinaryCounts] = field(default_factory=dict)
    calibration: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    latency_ms: list[int] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)
    cost_usd: list[float] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return len(self.case_results)

    def summary(self) -> dict[str, Any]:
        """Machine-readable summary, safe to print or diff between providers."""
        return {
            "provider": self.provider,
            "model": self.model,
            "dataset": self.dataset_name,
            "dataset_size": self.dataset_size,
            "evaluated": self.succeeded,
            "failed": len(self.failures),
            "binary_metrics": {
                name: counts.to_dict() for name, counts in sorted(self.binary.items())
            },
            "brier": {
                name: round(brier_score(pairs), 4)
                for name, pairs in sorted(self.calibration.items())
            },
            "latency_ms": {
                "mean": round(_mean(self.latency_ms), 1),
                "p50": round(_percentile(self.latency_ms, 50), 1),
                "p95": round(_percentile(self.latency_ms, 95), 1),
            },
            "input_tokens": {"mean": round(_mean(self.input_tokens), 1)},
            "cost_usd": {"total": round(sum(self.cost_usd), 8)},
        }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile, avoiding interpolation the data cannot support."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(percentile / 100 * len(ordered)))))
    return float(ordered[rank - 1])
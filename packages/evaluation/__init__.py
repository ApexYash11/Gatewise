"""Evaluation harness: score decision providers against labelled data.

The purpose is measurement, not marketing. A claim that one provider is better
than another requires running both over the same dataset with the same questions
and reporting the numbers, including the failures.

Three properties make the numbers trustworthy:

- **Provider-agnostic.** The runner depends only on ``DecisionProvider``, so
  comparing providers compares providers rather than two different harnesses.
- **Provenance travels with the results.** Every dataset reports who produced its
  labels, and a dataset of assistant-assessed labels is never presented as
  human-validated accuracy.
- **Failures are counted.** A provider that declines hard cases cannot improve its
  reported accuracy by declining them, because the failure count sits beside the
  accuracy in the same summary.
"""

from .dataset import Case, Dataset, DatasetError, LabelSource, load_dataset
from .metrics import (
    DEFAULT_TOLERANCE,
    BinaryCounts,
    EvaluationReport,
    brier_score,
    mean_absolute_error,
)
from .runner import DEFAULT_THRESHOLD, compare, run_dataset

__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOLERANCE",
    "BinaryCounts",
    "Case",
    "Dataset",
    "DatasetError",
    "EvaluationReport",
    "LabelSource",
    "brier_score",
    "compare",
    "load_dataset",
    "mean_absolute_error",
    "run_dataset",
]

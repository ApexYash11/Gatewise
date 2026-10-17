"""Gatewise decision layer.

Everything above this package -- the context builder, action router, audit store
and dashboard -- depends on the abstract :class:`DecisionProvider` only. The real
Jev implementation lives in :mod:`decisions.jev` and is imported lazily so that
constructing schemas or loading the registry never requires the SDK.
"""

from __future__ import annotations

from .provider import (
    DecisionError,
    DecisionProvider,
    DecisionUnavailable,
    DecisionValidationError,
)
from .registry import (
    DEFAULT_QUESTIONS_DIR,
    QuestionRegistry,
    RegisteredQuestion,
    load_registry,
)
from .schemas import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionSet,
    NoulAnswer,
    NoulQuestion,
    Question,
    QuestionType,
    ScoreAnswer,
    ScoreQuestion,
    Usage,
    normalize_score_levels,
)

__all__ = [
    "DEFAULT_QUESTIONS_DIR",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DecisionError",
    "DecisionProvider",
    "DecisionSet",
    "DecisionUnavailable",
    "DecisionValidationError",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "QuestionRegistry",
    "QuestionType",
    "RegisteredQuestion",
    "ScoreAnswer",
    "ScoreQuestion",
    "Usage",
    "load_registry",
    "normalize_score_levels",
]

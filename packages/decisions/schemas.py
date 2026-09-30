"""Typed decision schemas for Gatewise.

These mirror the *verified* TypeSafe AI Jev contract:

    POST https://api.typesafe.ai/v1/systemone
    -> { "state": <json>, "questions": { <name>: <question> } }
    <- { "model": str, "answers": { <name>: <answer> }, "usage": {...} }

Question types are exactly three: ``noul``, ``choice`` and ``score``.

Two contract details drive this module:

1. ``ScoreAnswer`` returns a *probability-weighted expected score* which may fall
   between integer levels (e.g. ``1.84`` on a 3-level rubric). We keep BOTH the
   raw expected value and the discrete arg-max level, so policy can route on a
   stable level without discarding real model signal.
2. ``ScoreAnswer.legend`` / ``probabilities`` are typed ``dict[int, ...]``
   upstream, but JSON object keys are always strings, so we normalize at the
   boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator




class BaseQuestion(BaseModel):
    """Fields shared by every question type."""

    model_config = ConfigDict(extra="forbid")

    instructions: str | None = None
    criteria: Any = None


class NoulQuestion(BaseQuestion):
    """A boolean/probabilistic judgement.

    ``criteria`` is optional; when supplied it is ``{"true": ..., "false": ...}``
    and documents what each outcome means.
    """

    type: Literal["noul"] = "noul"
    criteria: dict[str, str | None] | None = None

    @field_validator("criteria", mode="before")
    @classmethod
    def _stringify_keys(cls, value: Any) -> Any:
        """Coerce boolean YAML keys to strings.

        In YAML, ``true:``/``false:`` parse as booleans, while the Jev API expects
        the literal keys "true"/"false". Normalizing here means authors need not
        quote those keys in the question files.

        This must run ``before`` type validation, since the declared type is
        ``dict[str, ...]`` and Pydantic would otherwise reject a bool key first.
        """
        if not isinstance(value, dict):
            return value
        return {
            ("true" if key is True else "false" if key is False else str(key)): item
            for key, item in value.items()
        }


class ChoiceQuestion(BaseQuestion):
    """A closed-set classification. ``criteria`` is REQUIRED by the Jev API."""

    type: Literal["choice"] = "choice"
    criteria: dict[str, str | None]


class ScoreQuestion(BaseQuestion):
    """A bounded rubric judgement. ``criteria`` is a REQUIRED ordered list.

    List position defines the level index: index 0 is the lowest level.
    """

    type: Literal["score"] = "score"
    criteria: list[str]

    @field_validator("criteria")
    @classmethod
    def _require_levels(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("a score question needs at least two rubric levels")
        return value


Question = Annotated[
    Union[NoulQuestion, ChoiceQuestion, ScoreQuestion],
    Field(discriminator="type"),
]

class QuestionType(str, Enum):
    """The three decision primitives Jev supports."""

    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"



class BaseAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NoulAnswer(BaseAnswer):
    """Probability of a *yes* answer, from 0 to 1.

    The Jev contract has NO separate ``confidence`` field for nouls -- ``noul``
    is the only signal. We deliberately do not invent one.
    """

    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0.0, le=1.0)

    @property
    def probability(self) -> float:
        return self.noul


class ChoiceAnswer(BaseAnswer):
    """The highest-probability option, its confidence, and the distribution."""

    type: Literal["choice"] = "choice"
    choice: str
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float]


class ScoreAnswer(BaseAnswer):
    """A probability-weighted expected score plus the per-level distribution.

    ``score`` may fall between integer levels. ``level`` is the arg-max level,
    which is what policy code should route on.
    """

    type: Literal["score"] = "score"
    score: float
    confidence: float = Field(ge=0.0, le=1.0)
    legend: dict[str, str] = Field(default_factory=dict)
    probabilities: dict[str, float] = Field(default_factory=dict)
    level: int | None = None

    def resolve_level(self) -> int:
        """Compute and cache the discrete arg-max level index. Never raises."""
        if self.level is not None:
            return self.level
        if self.probabilities:
            best = max(self.probabilities, key=lambda k: self.probabilities[k])
            try:
                self.level = int(best)
            except (TypeError, ValueError):
                self.level = int(round(self.score))
        else:
            # With N rubric levels the valid index range is 0..N-1.
            top = max(len(self.legend) - 1, 0)
            self.level = max(0, min(int(round(self.score)), top))
        return self.level

    def level_label(self) -> str | None:
        return self.legend.get(str(self.resolve_level()))



Answer = Annotated[
    Union[NoulAnswer, ChoiceAnswer, ScoreAnswer],
    Field(discriminator="type"),
]


def normalize_score_levels(legend: Any, probabilities: Any) -> tuple[dict[str, str], dict[str, float]]:
    """Coerce upstream level keys to strings.

    Jev types these maps as ``dict[int, ...]``. Over the wire -- and in anything we
    persist and later re-hydrate -- the keys arrive as strings, so we normalize
    once, here, at the boundary.
    """
    norm_legend: dict[str, str] = {}
    norm_probs: dict[str, float] = {}
    if isinstance(legend, dict):
        for key, value in legend.items():
            norm_legend[str(key)] = value if isinstance(value, str) else str(value)
    if isinstance(probabilities, dict):
        for key, value in probabilities.items():
            try:
                norm_probs[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return norm_legend, norm_probs


class Usage(BaseModel):
    """Token accounting returned by the provider.

    ``cost`` is populated when the request is served through OpenRouter, which
    reports a per-request USD cost. TypeSafe's own endpoint does not return it, so
    it stays ``None`` there rather than being estimated.
    """

    model_config = ConfigDict(extra="ignore")

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


class DecisionSet(BaseModel):
    """A normalized, validated response from a decision provider."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    answers: dict[str, Answer]
    usage: Usage = Field(default_factory=Usage)

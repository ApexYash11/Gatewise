"""Versioned decision registry.

Every decision is a versioned, named artifact. Versioning matters because
changing a rubric silently changes the *meaning* of historical results: a stored
``pr_risk@1`` answer of level 4 must stay comparable forever, which is impossible
if the rubric underneath it can drift without a version bump.

Questions are defined in YAML (see ``questions/pull_request.yaml``) and loaded
into the typed schemas, so a malformed rubric fails at load time rather than at
decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from .provider import DecisionValidationError
from .schemas import (
    ChoiceQuestion,
    NoulQuestion,
    QuestionType,
    ScoreQuestion,
)

#: Where the shipped question definitions live.
DEFAULT_QUESTIONS_DIR = Path(__file__).resolve().parent / "questions"


@dataclass(frozen=True)
class RegisteredQuestion:
    """A versioned question definition."""

    name: str
    version: int
    type: QuestionType
    description: str
    question: NoulQuestion | ChoiceQuestion | ScoreQuestion

    @property
    def identifier(self) -> str:
        """Stable identity of this exact definition, e.g. ``pr_risk@1``."""
        return f"{self.name}@{self.version}"

    def to_request(self) -> NoulQuestion | ChoiceQuestion | ScoreQuestion:
        return self.question


def _build_question(
    name: str, spec: Mapping[str, Any]
) -> NoulQuestion | ChoiceQuestion | ScoreQuestion:
    qtype = spec.get("type")
    criteria = spec.get("criteria")
    instructions = spec.get("instructions")
    try:
        if qtype == "noul":
            return NoulQuestion(instructions=instructions, criteria=criteria)
        if qtype == "choice":
            if not criteria:
                raise ValueError("a choice question requires criteria")
            return ChoiceQuestion(instructions=instructions, criteria=criteria)
        if qtype == "score":
            if not criteria:
                raise ValueError("a score question requires criteria")
            return ScoreQuestion(instructions=instructions, criteria=criteria)
    except (TypeError, ValueError) as exc:
        raise DecisionValidationError(f"question {name!r} is invalid: {exc}") from exc
    raise DecisionValidationError(
        f"question {name!r} has unsupported type {qtype!r}; expected one of "
        f"{sorted(q.value for q in QuestionType)}"
    )


class QuestionRegistry:
    """An immutable, versioned collection of questions."""

    def __init__(self, questions: list[RegisteredQuestion]) -> None:
        seen: set[tuple[str, int]] = set()
        for question in questions:
            key = (question.name, question.version)
            if key in seen:
                raise DecisionValidationError(
                    f"duplicate question {question.identifier} in registry"
                )
            seen.add(key)
        # Sort by name, then version, so iteration is deterministic.
        self._questions = sorted(questions, key=lambda q: (q.name, q.version))

    def __iter__(self) -> Iterator[RegisteredQuestion]:
        return iter(self._questions)

    def __len__(self) -> int:
        return len(self._questions)

    def latest(self, name: str) -> RegisteredQuestion:
        """Return the highest version registered under ``name``."""
        versions = [q for q in self._questions if q.name == name]
        if not versions:
            raise DecisionValidationError(f"no question named {name!r}")
        return max(versions, key=lambda q: q.version)

    def get(self, name: str, version: int | None = None) -> RegisteredQuestion:
        if version is None:
            return self.latest(name)
        for question in self._questions:
            if question.name == name and question.version == version:
                return question
        raise DecisionValidationError(f"no question {name!r} at version {version}")

    def build_request(
        self, names: list[str] | None = None, *, version: int | None = None
    ) -> dict[str, NoulQuestion | ChoiceQuestion | ScoreQuestion]:
        """Build the request payload for the named questions (all, if omitted).

        Compatible questions are batched into a single provider call, since the
        Jev API accepts one request containing many questions.
        """
        selected = self._questions if names is None else [self.get(n, version) for n in names]
        if not selected:
            raise DecisionValidationError("cannot build a request with no questions")
        return {q.name: q.to_request() for q in selected}

    def identifiers(self) -> list[str]:
        """Every registered question as ``name@version`` -- persisted with results."""
        return [q.identifier for q in self._questions]


def load_registry(path: str | Path | None = None) -> QuestionRegistry:
    """Load question definitions from a YAML file or a directory of them."""
    target = Path(path) if path else DEFAULT_QUESTIONS_DIR
    files = sorted(target.glob("*.yaml")) if target.is_dir() else [target]
    if not files:
        raise DecisionValidationError(f"no question definitions found at {target}")

    questions: list[RegisteredQuestion] = []
    for file in files:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        entries = data.get("questions")
        if not isinstance(entries, list):
            raise DecisionValidationError(f"{file.name}: expected a 'questions' list")
        for entry in entries:
            name = entry.get("name")
            if not name:
                raise DecisionValidationError(f"{file.name}: a question is missing 'name'")
            version = entry.get("version")
            if not isinstance(version, int) or version < 1:
                raise DecisionValidationError(
                    f"question {name!r} needs an integer 'version' >= 1"
                )
            qtype = entry.get("type")
            try:
                parsed_type = QuestionType(qtype)
            except ValueError as exc:
                raise DecisionValidationError(
                    f"question {name!r} has unsupported type {qtype!r}"
                ) from exc
            questions.append(
                RegisteredQuestion(
                    name=name,
                    version=version,
                    type=parsed_type,
                    description=entry.get("description", ""),
                    question=_build_question(name, entry),
                )
            )
    return QuestionRegistry(questions)

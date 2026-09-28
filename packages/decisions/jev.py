"""The real TypeSafe AI Jev decision provider.

Every field used here was read from the installed ``typesafe_sdk`` package rather
than assumed. See docs/architecture/jev-contract.md for the verified contract and
the provenance of each claim.

Network access is confined to :meth:`JevDecisionProvider.evaluate`, so tests can
mock the socket (via the SDK's ``transport`` hook) and assert on request
construction and failure handling -- without simulating any model intelligence.
"""

from __future__ import annotations

from typing import Any

import typesafe_sdk
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from .provider import (
    DecisionProvider,
    DecisionUnavailable,
    DecisionValidationError,
)
from .schemas import (
    Answer,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    normalize_score_levels,
)

# Maps a schema question to the SDK question type the API actually accepts.
_QUESTION_BUILDERS = {"noul": Noul, "choice": Choice, "score": Score}


class JevDecisionProvider(DecisionProvider):
    """Evaluates engineering context using the real Jev System-1 model."""

    name = "jev"

    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        *,
        timeout: float = 10.0,
        base_url: str | None = None,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "a Jev API key is required; Gatewise never falls back to a "
                "simulated decision model"
            )
        self._model = model
        self._client = client or AsyncTypeSafeClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
            base_url=base_url,
        )
        self._owns_client = client is None

    @property
    def model(self) -> str:
        return self._model

    def _build_questions(self, questions: dict[str, Any]) -> dict[str, Any]:
        """Translate our schemas into the SDK's question objects."""
        built: dict[str, Any] = {}
        for name, question in questions.items():
            if isinstance(question, dict):
                question = _coerce_question(question)
            qtype = getattr(question, "type", None)
            builder = _QUESTION_BUILDERS.get(qtype)
            if builder is None:
                raise DecisionValidationError(
                    f"question {name!r} has unsupported type {qtype!r}"
                )
            criteria = question.criteria
            if qtype in {"choice", "score"} and not criteria:
                raise DecisionValidationError(
                    f"question {name!r} of type {qtype!r} requires criteria; the "
                    "Jev API rejects an empty rubric"
                )
            built[name] = builder(
                instructions=question.instructions, criteria=criteria
            )
        return built

    async def evaluate(self, state: Any, questions: dict[str, Any]) -> dict[str, Answer]:
        """Call Jev and return validated answers.

        Raises:
            DecisionUnavailable: On timeout, rate limit, network failure,
                authentication failure, or provider error.
            DecisionValidationError: On a malformed or unexpected response.
        """
        if not questions:
            raise DecisionValidationError("at least one question is required")

        payload = self._build_questions(questions)
        try:
            response = await self._client.system_one(state=state, questions=payload)
        except typesafe_sdk.TypeSafeAuthenticationError as exc:
            raise DecisionUnavailable(
                "Jev rejected the API key; check TYPESAFE_API_KEY"
            ) from exc
        except typesafe_sdk.TypeSafeRateLimitError as exc:
            raise DecisionUnavailable("Jev rate limit reached") from exc
        except typesafe_sdk.TypeSafeAPITimeoutError as exc:
            raise DecisionUnavailable("Jev request timed out") from exc
        except typesafe_sdk.TypeSafeAPIConnectionError as exc:
            raise DecisionUnavailable("could not reach the Jev API") from exc
        except typesafe_sdk.TypeSafeAPIResponseValidationError as exc:
            raise DecisionValidationError(
                "Jev returned a response that failed schema validation"
            ) from exc
        except typesafe_sdk.TypeSafeAPIError as exc:
            raise DecisionUnavailable(f"Jev API error: {exc}") from exc

        return self._normalize(response, expected=set(questions))

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


    def _normalize(self, response: Any, *, expected: set[str]) -> dict[str, Answer]:
        """Convert SDK answers into our validated schemas."""
        raw = getattr(response, "answers", None)
        if not isinstance(raw, dict):
            raise DecisionValidationError("Jev response contained no answers object")

        # A missing answer must never be silently defaulted to a safe value.
        missing = expected - set(raw)
        if missing:
            raise DecisionValidationError(
                f"Jev omitted answers for: {', '.join(sorted(missing))}"
            )

        answers: dict[str, Answer] = {}
        for name, value in raw.items():
            kind = getattr(value, "type", None)
            try:
                answers[name] = _to_answer(value, name)
            except DecisionValidationError:
                raise
            except (AttributeError, TypeError, ValueError) as exc:
                raise DecisionValidationError(
                    f"answer {name!r} was malformed: {exc}"
                ) from exc
        return answers


def _to_answer(value: Any, name: str) -> Answer:
    """Map one SDK answer object onto our validated schema."""
    kind = getattr(value, "type", None)
    if kind == "noul":
        return NoulAnswer(noul=float(value.noul))
    if kind == "choice":
        return ChoiceAnswer(
            choice=str(value.choice),
            confidence=float(value.confidence),
            probabilities={
                str(k): float(v) for k, v in dict(value.probabilities).items()
            },
        )
    if kind == "score":
        legend, probs = normalize_score_levels(
            dict(value.legend), dict(value.probabilities)
        )
        answer = ScoreAnswer(
            score=float(value.score),
            confidence=float(value.confidence),
            legend=legend,
            probabilities=probs,
        )
        answer.resolve_level()
        return answer
    raise DecisionValidationError(f"answer {name!r} has unknown type {kind!r}")


def _coerce_question(raw: dict[str, Any]) -> Any:
    """Rebuild a schema question from a plain dict (e.g. loaded from YAML)."""
    from .schemas import ChoiceQuestion, NoulQuestion, ScoreQuestion

    kind = raw.get("type")
    if kind == "noul":
        return NoulQuestion(**raw)
    if kind == "choice":
        return ChoiceQuestion(**raw)
    if kind == "score":
        return ScoreQuestion(**raw)
    raise DecisionValidationError(f"unknown question type {kind!r}")


__all__ = ["JevDecisionProvider"]
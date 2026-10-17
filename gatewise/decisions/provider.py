"""Provider abstraction for decision models.

The whole point of this module is that Gatewise's intelligence comes from a real
typed decision model, and that swapping the provider must not require rewriting
the product. Everything above this line (context builder, action router, audit)
depends only on :class:`DecisionProvider`, never on Jev specifics.

There is deliberately **no rule-based or heuristic implementation** in this
package. Nothing here estimates risk by counting keywords: that would be fake
intelligence wearing a model's name, which the project explicitly forbids.
"""

from __future__ import annotations

import abc
from typing import Any

from .schemas import Answer, QuestionType


class DecisionError(Exception):
    """Base class for all decision-layer failures."""


class DecisionUnavailable(DecisionError):
    """The provider could not produce a decision.

    Raised on timeout, rate limit, network failure, malformed output, or an
    unconfigured provider.

    This is the *fail-closed* signal. Callers MUST record the failure and MUST
    NOT substitute a default such as ``risk = 0`` or ``safe = true``: a missing
    decision is not a low-risk decision.
    """


class DecisionValidationError(DecisionError):
    """The provider responded, but the response failed validation."""


class DecisionProvider(abc.ABC):
    """Evaluates a state against typed questions and returns typed answers."""

    #: Stable identifier recorded in the audit log.
    name: str = "abstract"

    @property
    @abc.abstractmethod
    def model(self) -> str:
        """The concrete model identifier backing this provider."""

    @abc.abstractmethod
    async def evaluate(
        self,
        state: Any,
        questions: dict[str, Any],
    ) -> dict[str, Answer]:
        """Return one validated answer per question.

        Args:
            state: JSON-serializable engineering context.
            questions: Mapping of question name to a ``noul``/``choice``/``score``
                question. Compatible questions are batched into a single call.

        Returns:
            A mapping of question name to its validated answer.

        Raises:
            DecisionUnavailable: The decision could not be obtained.
            DecisionValidationError: The response was malformed.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Release any network resources. Safe to call more than once."""
        return None


__all__ = [
    "DecisionError",
    "DecisionProvider",
    "DecisionUnavailable",
    "DecisionValidationError",
    "QuestionType",
]

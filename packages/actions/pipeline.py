"""The decision pipeline: webhook event -> validated decisions -> run record.

This is the only place that orchestrates ingestion, the model call, and recording,
so the order of operations is auditable in one place:

    verify -> deduplicate -> parse -> build context -> evaluate -> record

The ordering is a security property, not a style choice. Deduplication runs after
signature verification (never trust an unauthenticated delivery ID) and before
evaluation (never spend a model call on a redelivery).

An :class:`EvaluationRun` records provider, model, and whether the model is
genuinely TypeSafe's hosted Jev. That last field matters: a local Jev-compatible
server speaks the same wire format, so without it, results from a different model
could be misattributed to hosted Jev.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from context.builder import PullRequestContext
from decisions.provider import DecisionProvider, DecisionUnavailable
from decisions.registry import QuestionRegistry
from decisions.schemas import Answer, NoulAnswer, ScoreAnswer
from github.dedup import action_fingerprint
from github.events import PullRequestEvent


class RunStatus(str, Enum):
    """Outcome of an evaluation run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class EvaluationRun:
    """A complete, auditable record of one evaluation."""

    repository: str
    pull_request_number: int
    provider: str
    model: str
    is_official_jev: bool
    question_versions: list[str]
    status: RunStatus = RunStatus.FAILED
    answers: dict[str, Answer] = field(default_factory=dict)
    state_hash: str = ""
    latency_ms: int = 0
    error: str | None = None
    injection_flags: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.SUCCEEDED


def hash_state(state: dict[str, Any]) -> str:
    """Stable hash of the exact context sent to the model.

    Recorded so a decision can be traced to the precise input that produced it,
    and so identical context is recognizable without storing the whole payload.
    """
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DecisionPipeline:
    """Runs one pull request through context building and the decision provider."""

    def __init__(
        self,
        provider: DecisionProvider,
        registry: QuestionRegistry,
        *,
        is_official_jev: bool = True,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._is_official_jev = is_official_jev

    async def evaluate(
        self, event: PullRequestEvent, context: PullRequestContext
    ) -> EvaluationRun:
        """Evaluate a pull request and always return a run record.

        Never raises for a provider failure: a failed evaluation is recorded with
        its error and returned, because an unrecorded failure is indistinguishable
        from a system that silently did nothing.
        """
        run = EvaluationRun(
            repository=event.repository,
            pull_request_number=event.number,
            provider=self._provider.name,
            model=self._provider.model,
            is_official_jev=self._is_official_jev,
            question_versions=self._registry.identifiers(),
            state_hash=hash_state(context.state),
            injection_flags=context.flagged_fields(),
        )
        started = time.perf_counter()
        try:
            run.answers = await self._provider.evaluate(
                context.state, self._registry.build_request()
            )
        except DecisionUnavailable as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
        else:
            run.status = RunStatus.SUCCEEDED
        finally:
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            run.completed_at = datetime.now(UTC)
        return run

    def plan_actions(self, run: EvaluationRun) -> list[dict[str, Any]]:
        """Derive the actions a run justifies.

        Routing is deliberately coarse and expressed in terms of levels and
        probability bands, never exact floats: Jev is not deterministic, so a
        threshold such as ``score > 2.07`` would behave inconsistently between
        runs. See docs/architecture/jev-contract.md.

        Returns an empty list for a failed run. A missing decision authorizes
        nothing.
        """
        if not run.succeeded:
            return []

        answers = run.answers
        risk = answers.get("pr_risk")
        security = answers.get("pr_security_review")
        testing = answers.get("pr_additional_testing")
        review = answers.get("pr_maintainer_review")

        labels: list[str] = []
        triggers: list[str] = []

        # Risk level >= 3 is the top three of five levels, i.e. moderate and above.
        if isinstance(risk, ScoreAnswer) and risk.resolve_level() >= 3:
            labels.append("risk:high")

        if isinstance(security, NoulAnswer) and security.noul >= 0.5:
            labels.append("security:review")

        if isinstance(testing, NoulAnswer) and testing.noul >= 0.7:
            triggers.append("extended-ci")

        if isinstance(review, NoulAnswer) and review.noul >= 0.5:
            triggers.append("request-review")

        planned: list[dict[str, Any]] = []
        for label in labels:
            planned.append(
                {
                    "action_type": "add_label",
                    "target": label,
                    "fingerprint": action_fingerprint(
                        repository=run.repository,
                        pull_request_number=run.pull_request_number,
                        action_type="add_label",
                        decision_run_id=run.state_hash,
                    ),
                }
            )
        for trigger in triggers:
            action_type = "trigger_workflow" if trigger == "extended-ci" else "request_review"
            planned.append(
                {
                    "action_type": action_type,
                    "target": trigger,
                    "fingerprint": action_fingerprint(
                        repository=run.repository,
                        pull_request_number=run.pull_request_number,
                        action_type=action_type,
                        decision_run_id=run.state_hash,
                    ),
                }
            )
        return planned

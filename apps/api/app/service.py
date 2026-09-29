"""Application service: the seam between HTTP and the decision pipeline.

The webhook endpoint must not contain decision logic, so this module owns the
flow and the endpoints stay thin:

    verify signature -> deduplicate -> parse -> build context -> evaluate
    -> record -> plan actions

Two invariants live here rather than in the route handlers, because they are
security properties rather than transport concerns:

- **An unsigned delivery never reaches the model.** Verification is the first
  step and raises before any parsing happens.
- **A failed evaluation is recorded, then reported as unavailable.** It is never
  converted into a decision, and the response says so explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from actions.pipeline import DecisionPipeline, EvaluationRun
from audit import AuditStore
from context.builder import build_context
from github import (
    DeliveryDeduplicator,
    PullRequestEvent,
    SignatureError,
    WebhookParseError,
    compute_signature,
    fetch_pull_request,
    parse_pull_request_event,
    verify_signature,
)


@dataclass
class WebhookOutcome:
    """What happened while handling one delivery."""

    status: str
    detail: str
    run: EvaluationRun | None = None
    actions: list[dict[str, Any]] | None = None
    injection_flags: list[str] | None = None
    #: The event that produced this outcome, when there was one. Carried on the
    #: result rather than stashed on shared state, so two concurrent reviews cannot
    #: read each other's pull request.
    event: PullRequestEvent | None = None
    #: The primary key of the stored run. ``EvaluationRun`` is the in-memory result
    #: and has no id of its own; the audit store assigns one on insert, so this can
    #: only be known after recording.
    run_id: int | None = None

    @property
    def http_status(self) -> int:
        return {
            "accepted": 202,
            "duplicate": 200,
            "ignored": 202,
            "unauthorized": 401,
            "failed": 200,
        }.get(self.status, 200)


class GatewiseService:
    """Owns ingestion, evaluation, and recording for one process."""

    def __init__(
        self,
        pipeline: DecisionPipeline,
        store: AuditStore,
        dedup: DeliveryDeduplicator | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._dedup = dedup or DeliveryDeduplicator()

    async def review_pull_request(
        self, repository: str, number: int, *, token: str | None = None
    ) -> WebhookOutcome:
        """Fetch a pull request on demand and evaluate it.

        This is the manual counterpart to :meth:`handle_delivery`, and it exists so
        the dashboard can drive a real review. It deliberately reuses the same
        evaluate-then-record sequence rather than calling the model directly, so a
        run created from the UI is indistinguishable from one created by a webhook:
        same context builder, same question versions, same audit rows, same action
        plan. A separate path would let the dashboard record verdicts that the
        product's own ingestion path could not justify.

        Actions are *planned*, not performed. Executing them needs a token and is a
        separate, explicit step, so a click in a browser can never write to GitHub
        by accident.
        """
        event = await fetch_pull_request(repository, number, token=token)

        context = build_context(
            number=event.number,
            title=event.title,
            description=event.description,
            author=event.author,
            base_branch=event.base_branch,
            head_branch=event.head_branch,
            labels=event.labels,
            changed_files=event.changed_files,
            draft=event.draft,
        )

        run = await self._pipeline.evaluate(event, context)
        actions = self._pipeline.plan_actions(run)
        record = await self._store.record_run(event, run, actions)

        if not run.succeeded:
            return WebhookOutcome(
                status="failed",
                detail=run.error or "evaluation failed",
                run=run,
                actions=actions,
                injection_flags=run.injection_flags,
                event=event,
                run_id=record.id,
            )
        return WebhookOutcome(
            status="accepted",
            detail="evaluated",
            run=run,
            actions=actions,
            injection_flags=run.injection_flags,
            event=event,
            run_id=record.id,
        )

    async def handle_delivery(
        self,
        body: bytes,
        *,
        signature: str | None,
        delivery_id: str | None,
        event: str | None,
        secret: str,
    ) -> WebhookOutcome:
        """Process one webhook delivery.

        Order matters: verification precedes deduplication (never trust an
        unauthenticated delivery ID) and deduplication precedes evaluation (never
        spend a model call on a redelivery).
        """
        try:
            verify_signature(body, signature, secret)
        except SignatureError as exc:
            return WebhookOutcome(status="unauthorized", detail=str(exc))

        if self._dedup.is_duplicate(delivery_id):
            return WebhookOutcome(
                status="duplicate", detail=f"delivery {delivery_id} already processed"
            )

        try:
            parsed = parse_pull_request_event(body, event=event)
        except WebhookParseError as exc:
            # Unsupported events are normal: GitHub sends many we do not handle.
            return WebhookOutcome(status="ignored", detail=str(exc))

        context = build_context(
            number=parsed.number,
            title=parsed.title,
            description=parsed.description,
            author=parsed.author,
            base_branch=parsed.base_branch,
            head_branch=parsed.head_branch,
            labels=parsed.labels,
            changed_files=parsed.changed_files,
            draft=parsed.draft,
        )

        run = await self._pipeline.evaluate(parsed, context)
        actions = self._pipeline.plan_actions(run)
        await self._store.record_run(parsed, run, actions)

        if not run.succeeded:
            return WebhookOutcome(
                status="failed",
                detail=run.error or "evaluation failed",
                run=run,
                actions=actions,
                injection_flags=run.injection_flags,
            )

        return WebhookOutcome(
            status="accepted",
            detail="evaluated",
            run=run,
            actions=actions,
            injection_flags=run.injection_flags,
        )

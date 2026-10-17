"""One pull request through the whole loop, without a server.

``run_review`` is the full loop in one awaitable:

    fetch the real PR -> build isolated context -> ask the real model
    -> record the run -> perform only the actions it justifies

The webhook flow verifies a signature before it parses a payload; there is no
signature to verify here because there is no request to verify — the event is
constructed from the response GitHub just gave us. That is not a shortcut past
the parser: :func:`github.fetch.fetch_pull_request` returns the same normalized
:class:`github.events.PullRequestEvent` a real delivery produces, so nothing
downstream can tell the two apart.

Recording always happens, including for failed runs. An evaluation the model
never produced must still be visible in the audit store; that is the contract
the webhook path already keeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from gatewise.actions.executor import ActionResult, GitHubActionExecutor
from gatewise.actions.pipeline import DecisionPipeline, EvaluationRun
from gatewise.audit import AuditStore, create_engine, create_schema, session_scope
from gatewise.config import Settings
from gatewise.context import PullRequestContext, build_context
from gatewise.decisions.jev import JevDecisionProvider
from gatewise.decisions.provider import DecisionProvider
from gatewise.decisions.registry import load_registry
from gatewise.github.events import PullRequestEvent
from gatewise.github.fetch import fetch_pull_request


@dataclass
class ReviewResult:
    """Everything one review produced, for printing or for a comment payload."""

    event: PullRequestEvent
    run: EvaluationRun
    context: PullRequestContext
    actions: list[dict[str, Any]] = field(default_factory=list)
    #: The actions whose persisted rows this run claimed atomically — the
    #: subset this loop is actually allowed to perform.
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    action_results: list[ActionResult] = field(default_factory=list)
    #: Whether any GitHub write was even attempted; ``False`` means plan-only.
    token_used: bool = False
    database_url: str = ""


async def run_review(
    repository: str,
    number: int,
    *,
    token: str | None = None,
    settings: Settings | None = None,
    github_client: httpx.AsyncClient | None = None,
    decision_provider: DecisionProvider | None = None,
    action_executor: Any = None,
    execute_actions: bool = True,
) -> ReviewResult:
    """Review one live pull request end to end.

    Args:
        repository: The ``owner/name`` to fetch.
        number: The pull request number.
        token: A GitHub token, used for *reads* (authenticated fetch, needed for
            private repositories) and, when ``execute_actions`` is set, for the
            write-permitted planned actions. Fetching a public repository works
            unauthenticated.
        settings: Injected configuration; read from the environment when None.
        github_client: Injected HTTP client for the GitHub API, so tests can
            stub the network without contacting GitHub.
        decision_provider: Injected provider, so tests can stub the model's
            network without substituting any decision logic. When None, the real
            Jev provider is built from the configured credentials — unconfigured
            credentials raise and no run exists at all.
        action_executor: Injected executor, for the same reason.
        execute_actions: When False (``--no-execute``), planned actions are
            recorded but never performed, even with a token present.

    Returns:
        A :class:`ReviewResult`. A provider failure is recorded on the run, not
        raised: a missing decision authorizes nothing but is still a fact.
    """
    settings = settings or Settings()

    event = await fetch_pull_request(repository, number, token=token, client=github_client)
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

    provider = decision_provider
    if provider is None:
        api_key, base_url = settings.jev_credentials()
        provider = JevDecisionProvider(
            api_key,
            settings.jev_model,
            base_url=base_url,
            transport_name=settings.jev_transport,
        )

    pipeline = DecisionPipeline(
        provider,
        load_registry(),
        is_official_jev=getattr(provider, "is_official_jev", False),
    )
    try:
        run = await pipeline.evaluate(event, context)
        result = ReviewResult(
            event=event,
            run=run,
            context=context,
            actions=pipeline.plan_actions(run, head_sha=event.head_sha),
            # Truthiness, not `is not None`: an empty string was never usable
            # and would leave claimed rows unsettled.
            token_used=bool(token) and execute_actions,
            database_url=settings.database_url,
        )

        # Record first (the audit truth). Perform only what this run can claim
        # atomically in the audit store: the claim UPDATE winning rowcount is
        # the eligibility verdict, so two concurrent reviews cannot both perform
        # the same action, a `--no-execute` run leaves rows ready to claim
        # later, and a failed write stays claimable while a performed one is
        # closed permanently. A new head commit changes the fingerprint, so
        # re-reviewing new code re-justifies actions on purpose.
        engine = create_engine(settings.database_url)
        await create_schema(engine)
        async with session_scope(engine) as session:
            store = AuditStore(session)
            record = await store.record_run(event, run, result.actions)
            if result.token_used:
                result.pending_actions = await store.claim_pending(
                    result.actions, run_id=record.id
                )
        await engine.dispose()
    finally:
        await provider.close()

    if result.pending_actions:
        executor = action_executor or GitHubActionExecutor(token or "")
        try:
            for action in result.pending_actions:
                try:
                    outcome = await executor.perform(
                        action, repository=event.repository, number=event.number
                    )
                except Exception as exc:
                    # A transport crash must not strand the claim in
                    # `executing` for a day: settle it as failed now, so the
                    # action stays retryable and audited on this run's row.
                    outcome = ActionResult(
                        action["action_type"], "failed", str(exc)
                    )
                result.action_results.append(outcome)
        finally:
            final_close = getattr(executor, "close", None)
            if final_close is not None:
                await final_close()

        # Settle the claims with what actually happened, under each action's
        # own claim token: a reclaimed row owned by a newer claim is never
        # overwritten by this run's late result. After settlement only
        # failures stay claimable.
        result_engine = create_engine(settings.database_url)
        await create_schema(result_engine)
        async with session_scope(result_engine) as session:
            store = AuditStore(session)
            for action, applied in zip(
                result.pending_actions, result.action_results
            ):
                await store.mark_action(
                    action["fingerprint"],
                    applied.status,
                    claim_token=action["claim_token"],
                    detail=applied.detail,
                )
        await result_engine.dispose()

    return result

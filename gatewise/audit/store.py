"""Persistence for evaluation runs.

The store's job is to make a run reconstructable later: which model answered,
which question version was asked, what came back, what followed, and when. A
decision whose provenance is unknown is not auditable, so nothing is written
without its provider, model, and question version attached.

Two behaviours are worth calling out because they are easy to get wrong:

- **A failed run is written, not skipped.** ``record_run`` persists the failure
  with its error. If only successes were stored, "we could not decide" would be
  indistinguishable from "nothing happened", and only one of those is safe to
  treat as low risk.
- **Action fingerprints are unique.** A replayed webhook hits the unique
  constraint and is reported as already-planned rather than inserted twice, which
  extends deduplication across process restarts.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gatewise.actions.pipeline import EvaluationRun
from gatewise.decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer
from gatewise.github.dedup import _legacy_action_fingerprint
from gatewise.github.events import PullRequestEvent

from .models import (
    ActionRecord,
    DecisionRecord,
    DecisionRunRecord,
    PullRequestRecord,
    Repository,
    utcnow,
)

#: Store the version separately so a rubric bump cannot rewrite history.
_VERSION_SUFFIX = "@"


def _parse_version(identifier: str) -> tuple[str, int]:
    """Split ``pr_risk@1`` into ``("pr_risk", 1)``."""
    name, _, version = identifier.partition(_VERSION_SUFFIX)
    try:
        return name, int(version)
    except ValueError:
        return name, 1


class AuditStore:
    """Writes and reads evaluation results."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_or_create_repository(self, full_name: str) -> Repository:
        owner, _, name = full_name.partition("/")
        existing = await self._session.scalar(
            select(Repository).where(
                Repository.owner == owner, Repository.name == name
            )
        )
        if existing is not None:
            return existing
        repository = Repository(owner=owner, name=name)
        self._session.add(repository)
        await self._session.flush()
        return repository

    async def _get_or_create_pull_request(
        self, event: PullRequestEvent
    ) -> PullRequestRecord:
        repository = await self._get_or_create_repository(event.repository)
        existing = await self._session.scalar(
            select(PullRequestRecord).where(
                PullRequestRecord.repository_id == repository.id,
                PullRequestRecord.number == event.number,
            )
        )
        if existing is not None:
            existing.title = event.title
            existing.author = event.author
            existing.head_sha = event.head_sha
            existing.updated_at = utcnow()
            await self._session.flush()
            return existing
        pull_request = PullRequestRecord(
            repository_id=repository.id,
            number=event.number,
            title=event.title,
            author=event.author,
            head_sha=event.head_sha,
        )
        self._session.add(pull_request)
        await self._session.flush()
        return pull_request


    async def record_run(
        self,
        event: PullRequestEvent,
        run: EvaluationRun,
        actions: Sequence[dict[str, Any]] = (),
    ) -> DecisionRunRecord:
        """Persist an evaluation and its planned actions.

        Returns the stored run. Safe to call for a failed run; the failure is
        recorded with its error rather than dropped.
        """
        pull_request = await self._get_or_create_pull_request(event)
        record = DecisionRunRecord(
            pull_request_id=pull_request.id,
            provider=run.provider,
            model=run.model,
            is_official_jev=run.is_official_jev,
            state_hash=run.state_hash,
            head_sha=event.head_sha,
            question_versions=list(run.question_versions),
            planned_actions=[
                {
                    "action_type": a.get("action_type"),
                    "target": a.get("target"),
                    "fingerprint": a.get("fingerprint"),
                }
                for a in actions
            ],
            latency_ms=run.latency_ms,
            status=run.status.value,
            error=run.error,
            injection_flags=list(run.injection_flags),
            started_at=run.started_at,
            completed_at=run.completed_at,
        )
        self._session.add(record)
        await self._session.flush()

        versions = {
            name: version
            for name, version in (_parse_version(v) for v in run.question_versions)
        }
        for name, answer in run.answers.items():
            self._session.add(self._decision_row(name, answer, versions, record.id))
        await self._session.flush()

        # The fingerprint is derived from the context hash, target, and head
        # commit, so re-evaluating an unchanged pull request (a `synchronize`
        # with no real content change, or a replay after a restart) produces the
        # same action identity. That is dedup working, not a failure. The skip
        # below is racy at read time, so the insert is attempted inside a
        # savepoint and a lost race collapses to "already recorded" rather than
        # aborting the transaction.
        for action in actions:
            legacy_fingerprint = _legacy_action_fingerprint(
                repository=event.repository,
                pull_request_number=event.number,
                action_type=action["action_type"],
                decision_run_id=run.state_hash,
            )
            if await self.has_fingerprint(
                action["fingerprint"], legacy_fingerprint=legacy_fingerprint
            ):
                continue
            # The IntegrityError is caught *outside* the savepoint: exiting a
            # savepoint normally on a failed flush leaves the dependency
            # uncertain, while unwinding through it restores the transaction.
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        ActionRecord(
                            decision_run_id=record.id,
                            fingerprint=action["fingerprint"],
                            action_type=action["action_type"],
                            target=action.get("target"),
                            status="planned",
                        )
                    )
                    await self._session.flush()
            except IntegrityError:
                continue
        await self._session.flush()
        return record

    def _decision_row(
        self,
        name: str,
        answer: Any,
        versions: dict[str, int],
        run_id: int,
    ) -> DecisionRecord:
        """Flatten one typed answer into a storable row.

        Confidence is stored where the model provides it. Noul answers have no
        confidence field in the Jev contract, so it stays null rather than being
        fabricated from the probability.
        """
        row = DecisionRecord(
            decision_run_id=run_id,
            question_name=name,
            question_version=versions.get(name, 1),
        )
        if isinstance(answer, NoulAnswer):
            row.question_type = "noul"
            row.answer = f"{answer.noul:.4f}"
            row.confidence = None
        elif isinstance(answer, ChoiceAnswer):
            row.question_type = "choice"
            row.answer = answer.choice
            row.confidence = answer.confidence
        elif isinstance(answer, ScoreAnswer):
            row.question_type = "score"
            row.answer = f"{answer.score:.4f}"
            row.confidence = answer.confidence
            row.level = answer.resolve_level()
        else:  # pragma: no cover - guarded by the answer union
            raise TypeError(f"unsupported answer type {type(answer).__name__}")
        return row


    async def list_pull_requests(
        self, *, repository: str | None = None, limit: int = 50
    ) -> list[tuple[PullRequestRecord, Repository]]:
        """List pull requests with their repository, newest first.

        The repository is joined explicitly rather than read through the ORM
        relationship: lazy loading outside a greenlet context raises
        MissingGreenlet under asyncio, so the join is the correct approach rather
        than a workaround.
        """
        query = (
            select(PullRequestRecord, Repository)
            .join(Repository, PullRequestRecord.repository_id == Repository.id)
            .order_by(PullRequestRecord.id.desc())
            .limit(limit)
        )
        if repository:
            owner, _, name = repository.partition("/")
            query = query.where(Repository.owner == owner, Repository.name == name)
        rows = await self._session.execute(query)
        return [(record, repo) for record, repo in rows.all()]

    async def get_pull_request(self, pull_request_id: int) -> PullRequestRecord | None:
        return await self._session.get(PullRequestRecord, pull_request_id)

    async def get_runs(self, pull_request_id: int) -> list[DecisionRunRecord]:
        query = (
            select(DecisionRunRecord)
            .where(DecisionRunRecord.pull_request_id == pull_request_id)
            .order_by(DecisionRunRecord.id.desc())
        )
        return list(await self._session.scalars(query))

    async def get_decisions(self, run_id: int) -> list[DecisionRecord]:
        query = select(DecisionRecord).where(DecisionRecord.decision_run_id == run_id)
        return list(await self._session.scalars(query))

    async def get_actions(self, run_id: int) -> list[ActionRecord]:
        query = select(ActionRecord).where(ActionRecord.decision_run_id == run_id)
        return list(await self._session.scalars(query))

    async def has_fingerprint(
        self, fingerprint: str, *, legacy_fingerprint: str | None = None
    ) -> bool:
        """Whether an action with this identity was already planned.

        Survives a restart, unlike the in-memory deduplicator, so a replayed
        webhook is still recognised as a repeat. A legacy fingerprint is also
        checked against runs without a saved head SHA, whose original head
        cannot be recovered safely for migration.
        """
        identities = [ActionRecord.fingerprint == fingerprint]
        if legacy_fingerprint is not None:
            identities.append(
                and_(
                    ActionRecord.fingerprint == legacy_fingerprint,
                    DecisionRunRecord.head_sha.is_(None),
                )
            )
        existing = await self._session.scalar(
            select(ActionRecord.id)
            .join(DecisionRunRecord)
            .where(or_(*identities))
        )
        return existing is not None

    async def claim_pending(
        self, actions: Sequence[dict[str, Any]], *, run_id: int
    ) -> list[dict[str, Any]]:
        """Atomically claim the actions this run may perform.

        Every action gets a persisted row (created here when missing, with the
        dedup rules of :meth:`record_run`), and is then claimed with an
        ``UPDATE ... WHERE <eligible>`` whose modified row count is the
        verdict. Two concurrent reviews cannot both own the same row: only one
        ``UPDATE`` modifies it, and the loser proceeds as if the action had
        been performed already.

        Eligible statuses: ``planned`` (never executed), and ``failed`` (a
        former attempt was rejected by GitHub and may be retried). Terminal
        statuses -- ``performed`` and ``skipped`` -- are never claimed again.
        A row stuck in ``executing`` (its claiming process died mid-flight) is
        reclaimed only after its *claim time* goes clearly stale, so a crash
        cannot suppress an action forever while a live execution stays owned.

        Each claimed action is copied with a ``claim_token`` the caller must
        pass back to :meth:`mark_action`; a stale worker whose claim was
        reclaimed cannot settle outcomes onto the newer claim.

        Returns the action dicts belonging to rows this call claimed.
        """
        identity = (
            await self._session.execute(
                select(
                    DecisionRunRecord.state_hash,
                    PullRequestRecord.number,
                    Repository.owner,
                    Repository.name,
                )
                .join(
                    PullRequestRecord,
                    DecisionRunRecord.pull_request_id == PullRequestRecord.id,
                )
                .join(Repository, PullRequestRecord.repository_id == Repository.id)
                .where(DecisionRunRecord.id == run_id)
            )
        ).one_or_none()
        stale = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
        claimed: list[dict[str, Any]] = []
        for action in actions:
            fingerprint = action["fingerprint"]
            legacy_fingerprint = (
                _legacy_action_fingerprint(
                    repository=f"{identity.owner}/{identity.name}",
                    pull_request_number=identity.number,
                    action_type=action["action_type"],
                    decision_run_id=identity.state_hash,
                )
                if identity is not None
                else None
            )
            if not await self.has_fingerprint(
                fingerprint, legacy_fingerprint=legacy_fingerprint
            ):
                try:
                    async with self._session.begin_nested():
                        self._session.add(
                            ActionRecord(
                                decision_run_id=run_id,
                                fingerprint=fingerprint,
                                action_type=action["action_type"],
                                target=action.get("target"),
                                status="planned",
                            )
                        )
                        await self._session.flush()
                except IntegrityError:
                    pass  # A concurrent claim created it first.
            claim_token = secrets.token_hex(8)
            claim_update = await self._session.execute(
                update(ActionRecord)
                .where(
                    ActionRecord.fingerprint == fingerprint,
                    or_(
                        ActionRecord.status.in_(("planned", "failed")),
                        and_(
                            ActionRecord.status == "executing",
                            ActionRecord.claimed_at < stale,
                        ),
                    ),
                )
                .values(
                    status="executing", claimed_at=utcnow(), claim_token=claim_token
                )
            )
            # rowcount exists for UPDATE results; the typed Result stub omits it.
            if claim_update.rowcount:  # type: ignore[attr-defined]
                claimed.append({**action, "claim_token": claim_token})
        await self._session.flush()
        return claimed

    async def mark_action(
        self, fingerprint: str, status: str, *, claim_token: str, detail: str = ""
    ) -> None:
        """Record the outcome of one claimed action.

        ``performed`` and ``skipped`` close the action's identity permanently
        (``skipped`` is a designed decline, e.g. the request-review sentinel,
        so retrying would keep guessing a reviewer); ``failed`` leaves it
        eligible for a later run. The update matches the claim token, so a
        reclaimed row owned by a newer claim is never overwritten by the
        older worker's late result.
        """
        await self._session.execute(
            update(ActionRecord)
            .where(
                ActionRecord.fingerprint == fingerprint,
                ActionRecord.claim_token == claim_token,
                ActionRecord.status == "executing",
            )
            .values(status=status, result=detail or None, completed_at=utcnow())
        )
        await self._session.flush()

    async def list_recent_decisions(self, limit: int = 100) -> list[Any]:
        """Most recent decisions across all runs, newest first."""
        from .models import DecisionRecord

        query = (
            select(DecisionRecord)
            .order_by(DecisionRecord.id.desc())
            .limit(limit)
        )
        return list(await self._session.scalars(query))

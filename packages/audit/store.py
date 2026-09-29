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

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from actions.pipeline import EvaluationRun
from decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer
from github.events import PullRequestEvent

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

        for action in actions:
            # The fingerprint is derived from the context hash, so re-evaluating an
            # unchanged pull request (a `synchronize` with no real content change,
            # or a replay after a restart) produces the same action identity. That
            # is the dedup guarantee working, not a failure: skip rather than
            # attempt an insert that would violate the unique constraint.
            if await self.has_fingerprint(action["fingerprint"]):
                continue
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
    ) -> list[PullRequestRecord]:
        """List pull requests, newest first, optionally filtered by repository."""
        query = select(PullRequestRecord).order_by(PullRequestRecord.id.desc()).limit(limit)
        if repository:
            owner, _, name = repository.partition("/")
            query = (
                query.join(Repository)
                .where(Repository.owner == owner, Repository.name == name)
            )
        return list(await self._session.scalars(query))

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

    async def has_fingerprint(self, fingerprint: str) -> bool:
        """Whether an action with this identity was already planned.

        Survives a restart, unlike the in-memory deduplicator, so a replayed
        webhook is still recognised as a repeat.
        """
        existing = await self._session.scalar(
            select(ActionRecord.id).where(ActionRecord.fingerprint == fingerprint)
        )
        return existing is not None

    async def list_recent_decisions(self, limit: int = 100) -> list[Any]:
        """Most recent decisions across all runs, newest first."""
        from .models import DecisionRecord

        query = (
            select(DecisionRecord)
            .order_by(DecisionRecord.id.desc())
            .limit(limit)
        )
        return list(await self._session.scalars(query))
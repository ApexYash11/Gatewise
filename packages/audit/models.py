"""SQLAlchemy models for the audit store.

Every decision is recorded together with the ``name@version`` of the question that
produced it. That pairing is the whole point of the store: without the version, a
later rubric change would silently reinterpret history, and a stored ``pr_risk``
level of 4 would no longer mean what it meant when it was written.

Three deliberate constraints:

- **Secrets are never stored.** No table has a column for a key, token, or the
  webhook secret. The context hash identifies what was evaluated; the context
  itself is not persisted in full.
- **Failures are rows, not absences.** ``decision_runs.status`` distinguishes
  succeeded from failed and ``error`` records why. A failed run is data, not a
  gap, because "we never looked" and "we looked and could not tell" are different
  facts and only one of them is safe to treat as low risk.
- **Action identity is deterministic.** ``actions.fingerprint`` is derived from
  stable facts, so a retry is detectable in the database rather than only in
  process memory.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all audit tables."""


def utcnow() -> datetime:
    return datetime.now(UTC)


class Repository(Base):
    """A GitHub repository Gatewise has seen."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[str | None] = mapped_column(String(64), index=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    pull_requests: Mapped[list["PullRequestRecord"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repo_owner_name"),)


class PullRequestRecord(Base):
    """A pull request Gatewise has evaluated."""

    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    github_pr_id: Mapped[str | None] = mapped_column(String(64), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255))
    head_sha: Mapped[str | None] = mapped_column(String(64))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    repository: Mapped[Repository] = relationship(back_populates="pull_requests")
    runs: Mapped[list["DecisionRunRecord"]] = relationship(
        back_populates="pull_request", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "number", name="uq_pr_repo_number"),
    )



class DecisionRunRecord(Base):
    """One evaluation attempt, successful or not.

    ``is_official_jev`` is stored rather than derived, because a local
    Jev-compatible server (Kev, Rizzo Flow) answers on the same wire format. If the
    two were conflated, results from a different model would be attributed to
    TypeSafe's Jev, which is exactly the misattribution this project avoids.
    """

    __tablename__ = "decision_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    is_official_jev: Mapped[bool] = mapped_column(Boolean, default=True)
    state_hash: Mapped[str] = mapped_column(String(64), index=True)
    question_versions: Mapped[list] = mapped_column(JSON, default=list)
    #: What this run justified, regardless of whether the action was already
    #: recorded by an earlier run. Kept separate from the ``actions`` rows because
    #: a replayed or re-evaluated pull request dedupes to the same action, and a
    #: run that merely re-derived the same verdict must still be able to show why.
    planned_actions: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    injection_flags: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    pull_request: Mapped[PullRequestRecord] = relationship(back_populates="runs")
    decisions: Mapped[list["DecisionRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    actions: Mapped[list["ActionRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )



class DecisionRecord(Base):
    """A single typed answer, stored with the question version that produced it."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(ForeignKey("decision_runs.id"))
    question_name: Mapped[str] = mapped_column(String(128), index=True)
    question_version: Mapped[int] = mapped_column(Integer, default=1)
    question_type: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    # Level for score answers, None for noul/choice.
    level: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[DecisionRunRecord] = relationship(back_populates="decisions")


class ActionRecord(Base):
    """An action the run justified, keyed by a deterministic fingerprint.

    The unique constraint on ``fingerprint`` is the durable half of the
    deduplication strategy: even across a restart, a replayed webhook cannot
    insert a second copy of the same action.
    """

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(ForeignKey("decision_runs.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    target: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="planned")
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    run: Mapped[DecisionRunRecord] = relationship(back_populates="actions")


Index("ix_runs_pr_status", DecisionRunRecord.pull_request_id, DecisionRunRecord.status)

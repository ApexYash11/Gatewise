"""Audit store: durable, reconstructable records of every decision.

Tables cover repositories, pull requests, decision runs, individual decisions, and
planned actions. The design principle is that a decision must be traceable to its
provenance — which model answered, which question *version* was asked, what the
context hash was, and what followed. A decision whose provenance is unknown is not
auditable, so nothing is written without it.

Failures are rows, not absences. See ``store.py`` for why that distinction matters.
"""

from .db import Base, create_engine, create_schema, session_scope
from .models import (
    ActionRecord,
    DecisionRecord,
    DecisionRunRecord,
    PullRequestRecord,
    Repository,
)
from .store import AuditStore

__all__ = [
    "ActionRecord",
    "AuditStore",
    "Base",
    "DecisionRecord",
    "DecisionRunRecord",
    "PullRequestRecord",
    "Repository",
    "create_engine",
    "create_schema",
    "session_scope",
]

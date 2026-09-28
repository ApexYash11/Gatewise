"""Delivery deduplication.

GitHub retries webhook deliveries, and a redelivery carries the **same**
``X-GitHub-Delivery`` ID. Without deduplication, a single pull request could
trigger repeated review requests, duplicate comments, and repeated CI runs.

Two independent layers guard against this:

1. **Delivery-ID deduplication** (:class:`DeliveryDeduplicator`) rejects a
   redelivery outright, before any work is done.
2. **Deterministic action identifiers** (:func:`action_fingerprint`) let the action
   layer recognize a repeat even if the delivery ID differs -- for example when a
   maintainer re-sends an event. The fingerprint is derived only from stable facts
   (repository, pull request, action type, decision run), never from a timestamp,
   so it is stable across processes and restarts.

The second layer matters because layer 1 alone still leaves a window: a genuinely
new delivery for an already-acted-upon decision run would otherwise duplicate work.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any


class DeliveryDeduplicator:
    """Remembers processed delivery IDs, with bounded memory.

    Bounded because this process may run for a long time: an unbounded set would
    grow without limit. Oldest IDs are evicted first, which is acceptable since
    GitHub's own retry window is short compared to the retained capacity.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._seen: dict[str, None] = {}
        self._lock = threading.Lock()

    def is_duplicate(self, delivery_id: str | None) -> bool:
        """Return True if this delivery was already processed.

        A missing delivery ID is **not** treated as a duplicate. Rejecting it is
        the endpoint's job; deciding here would conflate "no ID" with "seen before"
        and could silently drop a legitimate first delivery.
        """
        if not delivery_id:
            return False
        with self._lock:
            if delivery_id in self._seen:
                return True
            self._seen[delivery_id] = None
            if len(self._seen) > self._max_entries:
                # dict preserves insertion order, so the first key is the oldest.
                oldest = next(iter(self._seen))
                del self._seen[oldest]
            return False

    def seen_count(self) -> int:
        with self._lock:
            return len(self._seen)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


def action_fingerprint(
    *,
    repository: str,
    pull_request_number: int,
    action_type: str,
    decision_run_id: Any,
) -> str:
    """Build a stable identifier for an action about to be taken.

    Deterministic by construction: the same decision run always yields the same
    fingerprint, so a redelivery or a retried job can detect that the action was
    already performed. Excludes any timestamp or random component, which would
    make every attempt look new.
    """
    parts = (
        str(repository),
        str(pull_request_number),
        str(action_type),
        str(decision_run_id),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]

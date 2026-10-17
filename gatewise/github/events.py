"""Parse verified GitHub webhook payloads into a decision context.

Only the pull request events the MVP subscribes to are accepted:

- ``pull_request.opened``
- ``pull_request.synchronize``
- ``pull_request.reopened``

Parsing happens only after signature verification, and produces the trusted
structural facts plus the untrusted content, which
:func:`context.build_context` then isolates.

GitHub's payload nests the interesting values several levels deep, and the shapes
differ subtly between event types (a ``synchronize`` event has no meaningful
``created_at`` for the PR body, drafts live under ``draft``, and so on). This
module normalizes those differences so the rest of the pipeline sees one shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: Event/action pairs the MVP handles.
SUPPORTED_ACTIONS = frozenset({"opened", "synchronize", "reopened"})

#: Guard against absurd payloads before they reach the context builder.
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


class WebhookParseError(Exception):
    """The payload is not a supported, well-formed GitHub event."""


@dataclass(frozen=True)
class PullRequestEvent:
    """The normalized facts Gatewise needs from a pull request webhook."""

    delivery_id: str | None
    action: str
    repository: str
    number: int
    title: str
    description: str | None
    author: str
    base_branch: str
    head_branch: str
    labels: tuple[str, ...]
    changed_files: tuple[str, ...]
    draft: bool
    head_sha: str
    raw: dict[str, Any]


def parse_pull_request_event(
    body: bytes, *, event: str | None, action_hint: str | None = None
) -> PullRequestEvent:
    """Parse and validate a pull request webhook payload.

    Args:
        body: Raw request body. Must be JSON.
        event: Value of the ``X-GitHub-Event`` header.
        action_hint: Optional action override, used by tests and replays.

    Raises:
        WebhookParseError: If the event type is unsupported or the payload is
            missing required fields. Unsupported events are skipped rather than
            treated as errors, because GitHub sends many event types.
    """
    if len(body) > MAX_PAYLOAD_BYTES:
        raise WebhookParseError("payload too large")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"payload is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise WebhookParseError("payload must be a JSON object")

    if event != "pull_request":
        raise WebhookParseError(f"unsupported event type {event!r}")

    action = action_hint or payload.get("action")
    if action not in SUPPORTED_ACTIONS:
        # Not an error: GitHub sends many PR actions we do not subscribe to.
        raise WebhookParseError(f"unsupported pull_request action {action!r}")

    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        raise WebhookParseError("payload has no pull_request object")

    repository = payload.get("repository")
    if not isinstance(repository, dict):
        raise WebhookParseError("payload has no repository object")
    full_name = repository.get("full_name")
    if not full_name:
        raise WebhookParseError("repository has no full_name")

    number = pull_request.get("number")
    if not isinstance(number, int):
        raise WebhookParseError("pull request has no numeric number")

    base = pull_request.get("base") or {}
    head = pull_request.get("head") or {}
    user = pull_request.get("user") or {}

    files = tuple(
        str(entry.get("filename"))
        for entry in (pull_request.get("changed_files_list") or [])
        if isinstance(entry, dict) and entry.get("filename")
    )

    return PullRequestEvent(
        delivery_id=None,
        action=str(action),
        repository=str(full_name),
        number=number,
        title=str(pull_request.get("title") or ""),
        description=pull_request.get("body") or None,
        author=str(user.get("login") or "unknown"),
        base_branch=str(base.get("ref") or ""),
        head_branch=str(head.get("ref") or ""),
        labels=tuple(
            str(label.get("name"))
            for label in (pull_request.get("labels") or [])
            if isinstance(label, dict) and label.get("name")
        ),
        changed_files=files,
        draft=bool(pull_request.get("draft", False)),
        head_sha=str(head.get("sha") or ""),
        raw=payload,
    )

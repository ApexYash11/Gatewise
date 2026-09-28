"""GitHub integration: webhook verification, deduplication, and event parsing.

Security properties enforced here:

- :func:`github.security.verify_signature` rejects any delivery that is unsigned or
  incorrectly signed, **before** the payload is parsed. An endpoint that accepted
  unsigned webhooks would be trivially spoofable.
- Signature comparison is constant-time, so the expected digest cannot be recovered
  through timing.
- :class:`github.dedup.DeliveryDeduplicator` drops redeliveries, which GitHub
  retries, so one pull request cannot trigger repeated reviews or comments.
- :func:`github.dedup.action_fingerprint` gives every action a deterministic
  identity, so a repeat is detectable even when the delivery ID differs.

The pull request diff is *not* part of the webhook payload. Fetching it requires an
authenticated API call, which is deliberately not implemented yet: it would need a
GitHub App installation token, and the MVP works without it.
"""

from .dedup import DeliveryDeduplicator, action_fingerprint
from .events import (
    SUPPORTED_ACTIONS,
    PullRequestEvent,
    WebhookParseError,
    parse_pull_request_event,
)
from .security import (
    DELIVERY_ID_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SignatureError,
    compute_signature,
    verify_signature,
)

__all__ = [
    "DELIVERY_ID_HEADER",
    "EVENT_HEADER",
    "SIGNATURE_HEADER",
    "SUPPORTED_ACTIONS",
    "DeliveryDeduplicator",
    "PullRequestEvent",
    "SignatureError",
    "WebhookParseError",
    "action_fingerprint",
    "compute_signature",
    "parse_pull_request_event",
    "verify_signature",
]

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

The pull request diff is *not* part of the webhook payload, because GitHub sends a
file *count* rather than a list. :mod:`github.fetch` closes that gap for on-demand
reviews by calling the files endpoint and folding the names into
``changed_files_list`` before parsing, so a manually reviewed pull request is
described to the model exactly as a webhook-delivered one is.
"""

from .dedup import DeliveryDeduplicator, action_fingerprint
from .events import (
    SUPPORTED_ACTIONS,
    PullRequestEvent,
    WebhookParseError,
    parse_pull_request_event,
)
from .fetch import (
    MAX_FILES,
    PullRequestFetchError,
    build_webhook_payload,
    fetch_pull_request,
    validate_repository,
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
    "MAX_FILES",
    "SIGNATURE_HEADER",
    "SUPPORTED_ACTIONS",
    "DeliveryDeduplicator",
    "PullRequestEvent",
    "PullRequestFetchError",
    "SignatureError",
    "WebhookParseError",
    "action_fingerprint",
    "build_webhook_payload",
    "compute_signature",
    "fetch_pull_request",
    "parse_pull_request_event",
    "validate_repository",
    "verify_signature",
]

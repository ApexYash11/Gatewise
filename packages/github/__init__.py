"""GitHub integration.

Not yet implemented. This will contain webhook signature verification,
delivery-ID based deduplication, and pull request fetching.

Security requirements for this package, when it is built:
- verify the ``X-Hub-Signature-256`` header before parsing any payload;
- reject unsigned webhooks outright rather than processing them;
- deduplicate on the delivery ID, and use deterministic action identifiers so a
  redelivered event cannot trigger a duplicate review request or comment.
"""

__all__: list[str] = []

"""GitHub webhook signature verification.

GitHub signs each delivery with HMAC-SHA256 using a shared webhook secret and sends
the digest in ``X-Hub-Signature-256`` as ``sha256=<hex>``.

The rule enforced here is strict: **an unsigned or incorrectly signed delivery is
rejected outright, before the payload is parsed.** There is no "unsigned is fine"
mode, because a webhook endpoint that accepts unsigned requests is trivially
spoofable -- anyone could then fabricate a high-risk pull request and drive actions.

The comparison uses :func:`hmac.compare_digest`, which is constant-time, so a
timing side channel cannot be used to recover the expected digest byte by byte.
"""

from __future__ import annotations

import hashlib
import hmac

#: Header carrying the delivery signature.
SIGNATURE_HEADER = "X-Hub-Signature-256"

#: Header carrying the unique delivery ID, used for deduplication.
DELIVERY_ID_HEADER = "X-GitHub-Delivery"

#: Header carrying the event type, e.g. ``pull_request``.
EVENT_HEADER = "X-GitHub-Event"

_SHA256_PREFIX = "sha256="


class SignatureError(Exception):
    """The delivery signature is missing, malformed, or does not match."""


def compute_signature(payload: bytes, secret: str) -> str:
    """Return the expected ``sha256=<hex>`` signature for ``payload``."""
    if not secret:
        raise SignatureError("no webhook secret is configured")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{_SHA256_PREFIX}{digest}"


def verify_signature(payload: bytes, signature: str | None, secret: str) -> None:
    """Verify a delivery signature, raising :class:`SignatureError` on any problem.

    Args:
        payload: The **raw** request body, exactly as received. Re-serializing
            parsed JSON would change byte-for-byte content and break the digest.
        signature: Value of the ``X-Hub-Signature-256`` header, if present.
        secret: The shared webhook secret.

    Raises:
        SignatureError: If the secret is unset, the header is missing or
            malformed, or the digest does not match.
    """
    if not secret:
        raise SignatureError("no webhook secret is configured; refusing all deliveries")

    if not signature:
        raise SignatureError(f"missing {SIGNATURE_HEADER} header")

    if not signature.startswith(_SHA256_PREFIX):
        raise SignatureError(f"{SIGNATURE_HEADER} must be prefixed with 'sha256='")

    expected = compute_signature(payload, secret)
    # Constant-time comparison: never leak the digest through timing.
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("signature does not match the request body")

"""Security tests for GitHub webhook signature verification."""

from __future__ import annotations

import json

import pytest

from github.security import (
    SIGNATURE_HEADER,
    SignatureError,
    compute_signature,
    verify_signature,
)

SECRET = "a-well-known-test-webhook-secret"
PAYLOAD = json.dumps({"action": "opened", "number": 7}).encode("utf-8")


def test_valid_signature_is_accepted():
    signature = compute_signature(PAYLOAD, SECRET)
    verify_signature(PAYLOAD, signature, SECRET)


def test_missing_signature_is_rejected():
    with pytest.raises(SignatureError, match="missing"):
        verify_signature(PAYLOAD, None, SECRET)


def test_empty_signature_is_rejected():
    with pytest.raises(SignatureError, match="missing"):
        verify_signature(PAYLOAD, "", SECRET)


def test_wrong_secret_is_rejected():
    signature = compute_signature(PAYLOAD, "a-different-secret")
    with pytest.raises(SignatureError, match="does not match"):
        verify_signature(PAYLOAD, signature, SECRET)


def test_tampered_body_is_rejected():
    """The classic attack: keep a valid header but alter the body."""
    signature = compute_signature(PAYLOAD, SECRET)
    tampered = json.dumps({"action": "opened", "number": 999}).encode("utf-8")
    with pytest.raises(SignatureError, match="does not match"):
        verify_signature(tampered, signature, SECRET)


def test_signature_from_sha1_scheme_is_rejected():
    """Only sha256 is accepted; a sha1 digest must not pass."""
    import hashlib
    import hmac

    legacy = "sha1=" + hmac.new(
        SECRET.encode(), PAYLOAD, hashlib.sha1
    ).hexdigest()
    with pytest.raises(SignatureError, match="sha256"):
        verify_signature(PAYLOAD, legacy, SECRET)


def test_malformed_signature_is_rejected():
    with pytest.raises(SignatureError, match="sha256"):
        verify_signature(PAYLOAD, "not-a-digest", SECRET)


def test_unconfigured_secret_rejects_everything():
    """Fail closed: with no secret configured, nothing is trustworthy."""
    signature = compute_signature(PAYLOAD, SECRET)
    with pytest.raises(SignatureError, match="no webhook secret"):
        verify_signature(PAYLOAD, signature, "")


def test_signature_is_deterministic():
    assert compute_signature(PAYLOAD, SECRET) == compute_signature(PAYLOAD, SECRET)


def test_signature_changes_with_body():
    assert compute_signature(PAYLOAD, SECRET) != compute_signature(PAYLOAD + b" ", SECRET)


def test_verification_is_constant_time():
    """Guards against a regression to a naive == comparison."""
    import inspect

    from github import security

    source = inspect.getsource(security.verify_signature)
    assert "compare_digest" in source, "must use hmac.compare_digest, not =="

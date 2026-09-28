"""Unit tests for configuration and secret handling."""

from __future__ import annotations

import pytest

from config import Settings


def test_requires_jev_key_and_explains_how_to_supply_it(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    settings = Settings()
    assert not settings.has_jev_key
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        settings.require_jev_key()


def test_reads_canonical_typesafe_api_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-value")
    settings = Settings()
    assert settings.has_jev_key
    assert settings.require_jev_key() == "sk-test-value"


def test_accepts_legacy_jev_api_key_alias(monkeypatch):
    """The spec named JEV_API_KEY; the SDK reads TYPESAFE_API_KEY. Both work."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEV_API_KEY", "sk-legacy")
    assert Settings().require_jev_key() == "sk-legacy"


def test_whitespace_only_key_counts_as_absent(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    assert Settings().has_jev_key is False


def test_safe_summary_never_exposes_secret_values(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsec-super-secret")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----abc")

    summary = Settings().safe_summary()
    rendered = repr(summary)

    assert summary["typesafe_api_key_configured"] is True
    assert summary["github_webhook_secret_configured"] is True
    for secret in ("sk-super-secret-value", "whsec-super-secret", "BEGIN PRIVATE KEY"):
        assert secret not in rendered


def test_default_model_is_jev_latest(monkeypatch):
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")
    assert Settings().jev_model == "jev-latest"

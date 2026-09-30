"""Unit tests for configuration and secret handling."""

from __future__ import annotations

import pytest

from config import Settings


@pytest.fixture(autouse=True)
def _isolated_from_real_credentials(monkeypatch, tmp_path):
    """Keep every test in this module independent of real credentials.

    Two sources have to be neutralised, not one. The obvious case is an exported
    environment variable, but ``Settings`` also reads a ``.env`` file relative to
    the working directory. A developer who has followed the setup instructions
    therefore has a real key on disk, and any assertion of the form "no key
    configured" fails -- so the suite only passed on a machine that had never run
    the product. The working directory is moved to an empty temporary one, which
    removes the file source for every test here without repeating the setup.

    A real credential must never be loaded by a unit test, let alone asserted
    against, so this is isolation rather than convenience.
    """
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def _clear_keys(monkeypatch):
    """Isolate tests from any real keys present in the ambient environment."""
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_requires_jev_key_and_explains_how_to_supply_it(monkeypatch):
    _clear_keys(monkeypatch)
    settings = Settings()
    assert not settings.has_jev_key
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        settings.require_jev_key()


def test_reads_canonical_typesafe_api_key(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-value")
    settings = Settings()
    assert settings.has_jev_key
    assert settings.require_jev_key() == "sk-test-value"


def test_accepts_legacy_jev_api_key_alias(monkeypatch):
    """The spec named JEV_API_KEY; the SDK reads TYPESAFE_API_KEY. Both work."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("JEV_API_KEY", "sk-legacy")
    assert Settings().require_jev_key() == "sk-legacy"


def test_whitespace_only_key_counts_as_absent(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    assert Settings().has_jev_key is False


def test_safe_summary_never_exposes_secret_values(monkeypatch):
    _clear_keys(monkeypatch)
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


def test_openrouter_key_selects_the_openrouter_transport(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    settings = Settings()

    key, base_url = settings.jev_credentials()
    assert key == "sk-or-test"
    assert base_url == "https://openrouter.ai/api"
    assert settings.jev_transport == "openrouter"


def test_typesafe_key_takes_precedence_over_openrouter(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-typesafe")

    settings = Settings()
    key, base_url = settings.jev_credentials()
    assert key == "sk-typesafe"
    assert base_url is None, "direct TypeSafe access uses the SDK default base URL"
    assert settings.jev_transport == "typesafe"


def test_missing_every_key_names_both_supported_options(monkeypatch):
    _clear_keys(monkeypatch)
    with pytest.raises(RuntimeError) as excinfo:
        Settings().jev_credentials()
    message = str(excinfo.value)
    assert "TYPESAFE_API_KEY" in message
    assert "OPENROUTER_API_KEY" in message


def test_both_transports_reach_the_same_real_model(monkeypatch):
    """Switching transport must not change which model answers."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-typesafe")
    direct = Settings()
    monkeypatch.delenv("TYPESAFE_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    via_openrouter = Settings()
    assert direct.jev_model == via_openrouter.jev_model == "jev-latest"


def test_safe_summary_reports_transport_without_leaking_keys(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-super-secret")

    summary = Settings().safe_summary()
    assert summary["transport"] == "openrouter"
    assert summary["openrouter_api_key_configured"] is True
    assert "sk-or-super-secret" not in repr(summary)


def test_environment_variable_wins_over_dotenv(monkeypatch, tmp_path):
    """Regression: a stale exported variable must not silently shadow .env.

    pydantic-settings gives ambient environment variables priority over the .env
    file. During development this caused a rotated key in .env to be ignored in
    favour of an old exported key, which surfaced only as a confusing provider
    error. The key itself resolves correctly; the risk is misdiagnosis, so this
    test pins the precedence rule that the diagnostic script relies on.
    """
    _clear_keys(monkeypatch)
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENROUTER_API_KEY=from-dotenv-file\n", encoding="utf-8")

    monkeypatch.setenv("OPENROUTER_API_KEY", "from-ambient-environment")

    settings = Settings(_env_file=dotenv)
    key, base_url = settings.jev_credentials()

    assert key == "from-ambient-environment", "ambient env var takes precedence"
    assert base_url == Settings.OPENROUTER_BASE_URL

    # With no ambient variable, the .env value is used.
    _clear_keys(monkeypatch)
    from_file = Settings(_env_file=dotenv)
    assert from_file.jev_credentials()[0] == "from-dotenv-file"

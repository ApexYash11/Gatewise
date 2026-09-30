"""Tests for the provider comparison CLI's provider discovery.

Verifies that a self-comparison is never set up: comparing TypeSafe's hosted Jev
against itself would produce two identical rows and read as agreement between two
independent models, which is exactly the kind of unearned conclusion this project
exists to avoid.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from config import Settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_providers.py"


@pytest.fixture(autouse=True)
def _isolate_from_local_dotenv(monkeypatch, tmp_path):
    """Stop this module's tests from seeing a real credential.

    Two mechanisms have to be defeated, and the second is easy to miss.

    The obvious one is a ``.env`` in the working directory, which ``Settings``
    reads. The subtle one is that ``compare_providers.py`` calls
    ``load_dotenv()`` at *module* scope, and these tests re-execute the script for
    every test via ``_load()``. That re-runs the load after the test has already
    cleared the environment, putting the developer's real key straight back. An
    autouse fixture alone therefore cannot fix it, because the script is imported
    after the fixture runs.

    So ``load_dotenv`` itself is neutralised for the duration of the module. The
    tests that need a configured key set one explicitly through the environment,
    which is unaffected.
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("compare_providers", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["compare_providers"] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_no_providers_when_nothing_is_configured(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    loaded = _load()
    # _env_file=None disables the .env lookup outright. Changing directory alone is
    # not sufficient: pydantic-settings resolves the default relative to the
    # directory in force at import time, so a real .env is still found.
    assert loaded.build_providers(Settings(_env_file=None)) == []


def test_hosted_provider_is_included_with_a_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    providers = _load().build_providers(Settings())
    assert len(providers) == 1
    assert providers[0].transport == "openrouter"
    assert providers[0].is_official_jev is True


def test_pointing_base_url_at_typesafe_does_not_create_a_second_row(monkeypatch):
    """Comparing hosted Jev against itself would fake agreement."""
    _clear(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai")

    providers = _load().build_providers(Settings())
    assert len(providers) == 1, "must not compare a provider against itself"


def test_a_local_server_adds_a_second_provider(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:8009")

    providers = _load().build_providers(Settings())
    assert len(providers) == 2
    transports = {p.transport for p in providers}
    assert transports == {"typesafe", "local"}
    # The local server is a different model, so it must not be recorded as
    # TypeSafe's hosted Jev.
    local = next(p for p in providers if p.transport == "local")
    assert local.is_official_jev is False


def _clear(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def _load():
    spec = importlib.util.spec_from_file_location("compare_providers_mod", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded

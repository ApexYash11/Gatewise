"""Application configuration.

Two deliberate naming decisions:

* ``TYPESAFE_API_KEY`` is canonical, because that is the variable the official
  SDK reads. The spec's original ``JEV_API_KEY`` is still accepted as a fallback
  so existing instructions keep working, but relying on it alone would leave the
  SDK silently unauthenticated.
* Secrets are never logged, never returned by any endpoint, and never included
  in the model context. :meth:`Settings.safe_summary` exists so startup logs can
  show configuration state without exposing values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment or a ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Decision provider -------------------------------------------------- #
    # Two ways to reach the *same* real Jev model.
    typesafe_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TYPESAFE_API_KEY", "JEV_API_KEY"),
    )
    openrouter_api_key: str | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    jev_model: str = Field(default="jev-latest", validation_alias="TYPESAFE_DEFAULT_MODEL")
    jev_base_url: str | None = Field(default=None, validation_alias="TYPESAFE_BASE_URL")
    jev_timeout_seconds: float = 10.0

    # --- GitHub ------------------------------------------------------------- #
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str | None = None
    #: Fine-grained token used to *read* a pull request on demand and to perform
    #: actions. Optional: public repositories can be reviewed unauthenticated, and
    #: the product never requires write access to produce a decision.
    github_token: str | None = None

    # --- Storage ------------------------------------------------------------ #
    database_url: str = "sqlite+aiosqlite:///./gatewise.db"
    redis_url: str | None = None

    @field_validator(
        "typesafe_api_key",
        "openrouter_api_key",
        "github_private_key",
        "github_webhook_secret",
        "github_token",
    )
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @property
    def has_jev_key(self) -> bool:
        return bool(self.typesafe_api_key or self.openrouter_api_key)

    #: OpenRouter's System One base URL. The SDK appends ``/v1/systemone``,
    #: producing ``https://openrouter.ai/api/v1/systemone``, which serves the
    #: same real Jev model and the same request/response shape.
    OPENROUTER_BASE_URL: ClassVar[str] = "https://openrouter.ai/api"

    @property
    def jev_transport(self) -> str:
        """Which endpoint serves Jev: ``typesafe`` or ``openrouter``.

        Reflects the credential that will actually be used, so a configured
        OpenRouter key does not mislabel a run that goes direct to TypeSafe.
        """
        if self.typesafe_api_key:
            return "typesafe"
        return "openrouter" if self.openrouter_api_key else "typesafe"

    def jev_credentials(self) -> tuple[str, str | None]:
        """Return ``(api_key, base_url)`` for the configured transport.

        A direct TypeSafe key takes precedence. When only an OpenRouter key is
        present, the base URL is switched to OpenRouter's System One API, which
        serves the *same* Jev model -- so this is a transport change, not a
        change of model or a downgrade to a substitute.
        """
        if self.typesafe_api_key:
            return self.typesafe_api_key, self.jev_base_url
        if self.openrouter_api_key:
            return self.openrouter_api_key, self.jev_base_url or self.OPENROUTER_BASE_URL
        raise RuntimeError(
            "No decision-model API key configured. Set TYPESAFE_API_KEY (or "
            "JEV_API_KEY) for the TypeSafe endpoint, or OPENROUTER_API_KEY to "
            "reach the same Jev model through OpenRouter. Gatewise does not "
            "provide a fallback decision model."
        )

    def require_jev_key(self) -> str:
        """Return the API key or explain precisely what is missing."""
        return self.jev_credentials()[0]

    def safe_summary(self) -> dict[str, object]:
        """Configuration state for logs: presence only, never secret values."""
        return {
            "decision_provider": "jev",
            "transport": self.jev_transport,
            "model": self.jev_model,
            "typesafe_api_key_configured": bool(self.typesafe_api_key),
            "openrouter_api_key_configured": bool(self.openrouter_api_key),
            "github_app_configured": bool(self.github_app_id),
            "github_webhook_secret_configured": bool(self.github_webhook_secret),
            "database_url_scheme": self.database_url.split(":", 1)[0],
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()

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
    typesafe_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TYPESAFE_API_KEY", "JEV_API_KEY"),
    )
    jev_model: str = Field(default="jev-latest", validation_alias="TYPESAFE_DEFAULT_MODEL")
    jev_base_url: str | None = Field(default=None, validation_alias="TYPESAFE_BASE_URL")
    jev_timeout_seconds: float = 10.0

    # --- GitHub ------------------------------------------------------------- #
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str | None = None

    # --- Storage ------------------------------------------------------------ #
    database_url: str = "sqlite+aiosqlite:///./gatewise.db"
    redis_url: str | None = None

    # --- Dashboard ---------------------------------------------------------- #
    next_public_api_url: str = "http://localhost:8000"

    @field_validator("typesafe_api_key", "github_private_key", "github_webhook_secret")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @property
    def has_jev_key(self) -> bool:
        return bool(self.typesafe_api_key)

    def require_jev_key(self) -> str:
        """Return the API key or explain precisely what is missing.

        Gatewise refuses to start the decision pipeline without a real key rather
        than degrading to a simulated model.
        """
        if not self.typesafe_api_key:
            raise RuntimeError(
                "No decision-model API key configured. Set TYPESAFE_API_KEY (or "
                "JEV_API_KEY) in the environment. Gatewise does not provide a "
                "fallback decision model."
            )
        return self.typesafe_api_key

    def safe_summary(self) -> dict[str, object]:
        """Configuration state for logs: presence only, never secret values."""
        return {
            "decision_provider": "jev",
            "model": self.jev_model,
            "typesafe_api_key_configured": self.has_jev_key,
            "github_app_configured": bool(self.github_app_id),
            "github_webhook_secret_configured": bool(self.github_webhook_secret),
            "database_url_scheme": self.database_url.split(":", 1)[0],
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()

"""Application configuration.

System-level settings (host, port, paths) are read from environment variables
with sensible defaults. User-level settings (API base URL / API key) live in
``data/config.json`` and are managed by :mod:`backend.services.settings_service`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppConfig(BaseSettings):
    """System configuration for the local AI Chat application."""

    model_config = SettingsConfigDict(
        env_prefix="AICHAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", description="Bind host for the server.")
    port: int = Field(default=8005, description="Bind port for the server.")
    open_browser: bool = Field(
        default=True, description="Open the browser automatically on startup."
    )
    log_level: str = Field(default="INFO", description="Root log level.")

    data_dir: Path = Field(
        default=PROJECT_ROOT / "data",
        description="Directory for local user data (config + database).",
    )
    frontend_dir: Path = Field(
        default=PROJECT_ROOT / "frontend",
        description="Directory containing the static frontend assets.",
    )

    request_timeout: float = Field(
        default=120.0, description="Timeout (seconds) for non-streaming API calls."
    )
    connect_timeout: float = Field(
        default=15.0, description="Timeout (seconds) for establishing a connection."
    )

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "chat.db"

    def ensure_data_dir(self) -> Path:
        """Create the data directory if it does not exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return the cached application configuration."""
    config = AppConfig()
    config.ensure_data_dir()
    return config


def reset_config_cache() -> None:
    """Clear the cached configuration (used by tests)."""
    get_config.cache_clear()


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean-ish environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
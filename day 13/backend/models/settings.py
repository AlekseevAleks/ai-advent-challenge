"""Pydantic schemas for user settings."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SettingsBase(BaseModel):
    api_base_url: str = Field(
        default="",
        description="Base URL of the OpenAI-compatible API, e.g. https://api.openai.com/v1",
    )
    api_key: str = Field(default="", description="API key (never returned to the client).")


class SettingsUpdate(BaseModel):
    """Payload for updating settings.

    ``api_key`` may be omitted (``None``) to keep the stored key unchanged.
    """

    api_base_url: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("api_base_url")
    @classmethod
    def _normalize_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("Base URL должен начинаться с http:// или https://")
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def _strip_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()


class SettingsPublic(BaseModel):
    """Settings as exposed to the frontend (key is masked)."""

    api_base_url: str = ""
    api_key_masked: str = ""
    has_api_key: bool = False
    is_configured: bool = False


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    models_count: Optional[int] = None
    latency_ms: Optional[int] = None
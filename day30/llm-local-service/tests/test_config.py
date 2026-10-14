"""Проверки конфигурационных инвариантов и безопасных значений по умолчанию."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_settings_bind_api_and_ollama_locally() -> None:
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.allow_remote_ollama is False
    assert settings.api_key is None


def test_remote_ollama_is_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="ALLOW_REMOTE_OLLAMA"):
        Settings(
            _env_file=None,
            ollama_base_url="http://192.168.1.20:11434",
        )


def test_private_lan_ollama_requires_explicit_opt_in() -> None:
    settings = Settings(
        _env_file=None,
        ollama_base_url="http://192.168.1.20:11434",
        allow_remote_ollama=True,
    )
    assert settings.ollama_base_url == "http://192.168.1.20:11434"


def test_context_window_must_include_output_reserve() -> None:
    with pytest.raises(ValidationError, match="OLLAMA_NUM_CTX"):
        Settings(
            _env_file=None,
            ollama_num_ctx=1024,
            max_context_tokens=1024,
            max_output_tokens=512,
        )


def test_ollama_url_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError, match="логин/пароль"):
        Settings(
            _env_file=None,
            ollama_base_url="http://user:password@127.0.0.1:11434",
        )

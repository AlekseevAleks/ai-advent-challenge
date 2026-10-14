"""Общие фикстуры тестов. Все обращения к модели подменяются моками."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Изолированная конфигурация с небольшими, быстрыми лимитами."""
    return Settings(
        _env_file=None,
        host="127.0.0.1",
        port=5002,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-model",
        ollama_timeout=0.1,
        ollama_connect_timeout=0.1,
        ollama_max_retries=0,
        ollama_num_ctx=2048,
        ollama_max_concurrency=1,
        max_message_chars=100,
        max_history_messages=4,
        max_context_tokens=1024,
        max_output_tokens=128,
        context_token_tolerance=0.0,
        tokenizer="heuristic",
        rate_limit="10/minute",
        trust_proxy_headers=False,
        trusted_proxies="127.0.0.1,::1",
        request_log_enabled=True,
        request_log_dir=str(tmp_path / "request-logs"),
        request_log_max_entries=50,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """FastAPI-клиент без реального вызова Ollama."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.llm.chat = AsyncMock(return_value="Тестовый ответ.")
        app.state.llm.health = AsyncMock(
            return_value=type(
                "Health", (),
                {
                    "status": "ok",
                    "model_available": True,
                    "detail": "Тестовая модель доступна.",
                },
            )()
        )
        yield test_client


@pytest.fixture
def payload() -> dict[str, object]:
    """Минимальный валидный запрос чата."""
    return {"messages": [{"role": "user", "content": "Привет"}]}

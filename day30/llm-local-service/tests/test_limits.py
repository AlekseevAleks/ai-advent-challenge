"""Проверки rate limit и безопасной идентификации IP-клиента."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_rate_limit_returns_429_with_retry_after(settings: Settings) -> None:
    limited = Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "rate_limit": "2/minute",
        },
    )
    app = create_app(limited)
    with TestClient(app) as client:
        app.state.llm.chat = AsyncMock(return_value="Мок-ответ")
        first = client.post("/chat", json={"messages": [{"role": "user", "content": "1"}]})
        second = client.post("/chat", json={"messages": [{"role": "user", "content": "2"}]})
        third = client.post("/chat", json={"messages": [{"role": "user", "content": "3"}]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("retry-after")
    assert third.json()["error"]["code"] == "rate_limit_exceeded"
    assert "2/minute" in third.json()["error"]["message"]


def test_forwarded_for_is_ignored_by_default(settings: Settings) -> None:
    """Произвольный X-Forwarded-For не может менять ключ rate limit."""
    limited = Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "rate_limit": "1/minute",
            "trust_proxy_headers": False,
        },
    )
    app = create_app(limited)
    with TestClient(app) as client:
        app.state.llm.chat = AsyncMock(return_value="Мок-ответ")
        one = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "1"}]},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        two = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "2"}]},
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
    assert one.status_code == 200
    assert two.status_code == 429


def test_rate_limit_rejects_invalid_rate_format() -> None:
    try:
        Settings(_env_file=None, rate_limit="ten/minute")
    except Exception as exc:
        assert "RATE_LIMIT" in str(exc)
    else:  # pragma: no cover - если валидатор сломан, тест явно провалится
        raise AssertionError("Ожидалась ошибка конфигурации")

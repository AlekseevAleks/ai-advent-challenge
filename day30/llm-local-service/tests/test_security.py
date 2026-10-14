"""Проверки необязательной аутентификации API key."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


API_KEY = "local-demo-key-that-is-at-least-32-chars"


def _app_with_key() -> TestClient:
    settings = Settings(
        _env_file=None,
        api_key=API_KEY,
        ollama_num_ctx=2048,
        max_context_tokens=1024,
        max_output_tokens=128,
        request_log_enabled=False,
    )
    app = create_app(settings)
    return TestClient(app)


def test_chat_requires_api_key_if_configured() -> None:
    with _app_with_key() as client:
        response = client.post(
            "/chat", json={"messages": [{"role": "user", "content": "привет"}]}
        )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json()["error"]["code"] == "authentication_required"
    assert API_KEY not in response.text


def test_chat_accepts_bearer_api_key() -> None:
    with _app_with_key() as client:
        client.app.state.llm.chat = AsyncMock(return_value="Мок-ответ")
        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "привет"}]},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
    assert response.status_code == 200
    assert response.json()["response"] == "Мок-ответ"


def test_chat_accepts_x_api_key_header() -> None:
    with _app_with_key() as client:
        client.app.state.llm.chat = AsyncMock(return_value="Мок-ответ")
        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "привет"}]},
            headers={"X-API-Key": API_KEY},
        )
    assert response.status_code == 200


def test_empty_api_key_from_env_is_disabled() -> None:
    settings = Settings(_env_file=None, api_key="")
    assert settings.api_key is None


def test_api_key_requires_minimum_length() -> None:
    try:
        Settings(_env_file=None, api_key="short")
    except Exception as exc:
        assert "api_key" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Короткий API_KEY должен быть отклонён")

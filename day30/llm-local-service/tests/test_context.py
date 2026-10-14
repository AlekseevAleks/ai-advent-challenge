"""Проверки длины сообщений, количества истории и токенов контекста."""

from fastapi.testclient import TestClient


def test_message_over_max_chars_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "x" * 101}]},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "message_too_long"
    assert error["details"]["limit_name"] == "MAX_MESSAGE_CHARS"


def test_history_over_max_messages_is_rejected(client: TestClient) -> None:
    messages = []
    for index in range(5):
        messages.append(
            {
                "role": "user" if index == 4 else ("assistant" if index % 2 else "user"),
                "content": f"message {index}",
            }
        )
    response = client.post("/chat", json={"messages": messages})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_messages"
    assert response.json()["error"]["details"]["limit_name"] == "MAX_HISTORY_MESSAGES"


def test_token_context_over_limit_is_rejected(client: TestClient) -> None:
    """В пределах размера сообщения, но с превышением общего токен-бюджета."""
    # Тестовая эвристика: символы / 2. 100 символов дают ~50 токенов;
    # четыре длинных сообщения превышают 1024 токена при длине <= 100 chars?
    # Используем переопределённый лимитер для короткого бюджета.
    from app.limits import ContextLimiter

    settings = client.app.state.settings.model_copy(
        update={"max_context_tokens": 20, "context_token_tolerance": 0.0}
    )
    client.app.state.context_limiter = ContextLimiter(settings)
    response = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "x" * 50}]}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "context_too_large"
    assert response.json()["error"]["details"]["limit_name"] == "MAX_CONTEXT_TOKENS"


def test_system_message_must_be_first(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "user", "content": "Вопрос"},
                {"role": "system", "content": "Инструкция"},
                {"role": "user", "content": "Ещё вопрос"},
            ]
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_history"


def test_request_body_hard_limit(client: TestClient) -> None:
    """ASGI middleware отклоняет большой body ещё до JSON/Pydantic parsing."""
    response = client.post(
        "/chat",
        content=b"x" * 70_000,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"

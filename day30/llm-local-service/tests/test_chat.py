"""Проверки API чата, валидации, истории и ошибок Ollama."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.llm import OllamaModelNotFoundError, OllamaTimeoutError, OllamaUnavailableError


def test_chat_success(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "response": "Тестовый ответ.",
        "model": "test-model",
        "done": True,
    }


def test_chat_forwards_complete_history(client: TestClient) -> None:
    """История отправляется модели в исходном порядке."""
    payload = {
        "messages": [
            {"role": "system", "content": "Отвечай кратко."},
            {"role": "user", "content": "Как меня зовут?"},
            {"role": "assistant", "content": "Пока не знаю."},
            {"role": "user", "content": "Меня зовут Анна."},
        ]
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    call_messages = client.app.state.llm.chat.await_args.args[0]
    assert [message.role for message in call_messages] == [
        "system", "user", "assistant", "user"
    ]
    assert call_messages[-1].content == "Меня зовут Анна."


def test_empty_message_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "   "}]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_empty_messages_list_is_rejected(client: TestClient) -> None:
    response = client.post("/chat", json={"messages": []})
    assert response.status_code == 422


def test_invalid_role_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/chat", json={"messages": [{"role": "tool", "content": "hi"}]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_assistant_cannot_be_last_message(client: TestClient) -> None:
    response = client.post(
        "/chat", json={"messages": [{"role": "assistant", "content": "Ответ"}]}
    )
    assert response.status_code == 422


def test_malformed_json_is_safe(client: TestClient) -> None:
    response = client.post(
        "/chat",
        content=b'{"messages":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "traceback" not in response.text.lower()


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "extra": "no"},
    )
    assert response.status_code == 422


def test_timeout_is_returned_as_504(client: TestClient, payload: dict[str, object]) -> None:
    client.app.state.llm.chat = AsyncMock(side_effect=OllamaTimeoutError())
    response = client.post("/chat", json=payload)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ollama_timeout"
    assert "Traceback" not in response.text


def test_ollama_unavailable_is_returned_as_503(
    client: TestClient, payload: dict[str, object]
) -> None:
    client.app.state.llm.chat = AsyncMock(side_effect=OllamaUnavailableError())
    response = client.post("/chat", json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ollama_unavailable"


def test_missing_model_is_returned_as_503(
    client: TestClient, payload: dict[str, object]
) -> None:
    client.app.state.llm.chat = AsyncMock(side_effect=OllamaModelNotFoundError())
    response = client.post("/chat", json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_found"


def test_error_does_not_leak_internal_exception(
    client: TestClient, payload: dict[str, object]
) -> None:
    client.app.state.llm.chat = AsyncMock(
        side_effect=OllamaUnavailableError("internal /private/path")
    )
    response = client.post("/chat", json=payload)
    assert response.status_code == 503
    assert "/private/path" not in response.text
    assert "Traceback" not in response.text

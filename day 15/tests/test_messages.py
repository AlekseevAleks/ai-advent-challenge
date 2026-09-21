"""Tests for sending messages, streaming and error handling."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.services.chat_service import derive_title


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def _create_chat(client: TestClient, model: str = "gpt-4o-mini") -> dict:
    return client.post("/api/chats", json={"model": model}).json()


def test_send_message_requires_settings(client: TestClient) -> None:
    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "settings_not_configured"


def test_send_message(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)

    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Привет!"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_message"]["content"] == "Привет!"
    assert payload["assistant_message"]["content"] == "Привет!"
    assert payload["assistant_message"]["role"] == "assistant"

    messages = client.get(f"/api/chats/{chat['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_send_message_sends_full_history(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)

    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Первый"})
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Второй"})

    last_request = fake_api.chat_requests()[-1]
    assert last_request["url"] == "https://api.example.com/v1/chat/completions"
    sent = last_request["json"]["messages"]
    # The first message is the system prompt that carries the agent memory;
    # the rest is the short-term dialogue of this chat.
    assert sent[0]["role"] == "system"
    assert [message["role"] for message in sent[1:]] == [
        "user",
        "assistant",
        "user",
    ]
    assert sent[-1]["content"] == "Второй"
    assert last_request["json"]["model"] == "gpt-4o-mini"


def test_chat_renamed_after_first_message(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    assert chat["title"] == "Новый чат"

    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Расскажи про Python"},
    )
    updated = client.get(f"/api/chats/{chat['id']}").json()
    assert updated["title"] == "Расскажи про Python"


def test_empty_message_rejected(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "   "}
    )
    assert response.status_code == 422


def test_send_message_to_missing_chat(client: TestClient, fake_api) -> None:
    _configure(client)
    response = client.post("/api/chats/nope/messages", json={"content": "Привет"})
    assert response.status_code == 404


def test_send_message_api_error(client: TestClient, fake_api) -> None:
    fake_api.completion_response = fake_api.completion_response.__class__(
        401, {"error": {"message": "Invalid API key"}}
    )
    _configure(client)
    chat = _create_chat(client)

    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "api_auth_error"

    # The user message is still stored, so nothing is lost.
    messages = client.get(f"/api/chats/{chat['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user"]


def test_send_message_bad_response_format(client: TestClient, fake_api) -> None:
    fake_api.completion_response = fake_api.completion_response.__class__(
        200, {"unexpected": "payload"}
    )
    _configure(client)
    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "api_bad_response"


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            events.append((name, json.loads(data)))
    return events


def test_stream_message(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)

    response = client.post(
        f"/api/chats/{chat['id']}/messages/stream", json={"content": "Привет"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "user_message"
    assert "delta" in names
    assert names[-2] == "done"
    assert names[-1] == "end"

    deltas = "".join(data["content"] for name, data in events if name == "delta")
    assert deltas == "Привет"

    done = next(data for name, data in events if name == "done")
    assert done["content"] == "Привет"

    messages = client.get(f"/api/chats/{chat['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "Привет"


def test_stream_message_api_error(client: TestClient, fake_api) -> None:
    fake_api.stream_status = 500
    fake_api.stream_body = b'{"error": {"message": "boom"}}'
    _configure(client)
    chat = _create_chat(client)

    response = client.post(
        f"/api/chats/{chat['id']}/messages/stream", json={"content": "Привет"}
    )
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert "error" in names
    error = next(data for name, data in events if name == "error")
    assert "500" in error["message"]


def test_stream_falls_back_to_json(client: TestClient, fake_api) -> None:
    fake_api.stream_content_type = "application/json"
    fake_api.stream_lines = []
    fake_api.stream_body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "Привет"}}]}
    ).encode("utf-8")
    _configure(client)
    chat = _create_chat(client)

    response = client.post(
        f"/api/chats/{chat['id']}/messages/stream", json={"content": "Привет"}
    )
    events = _parse_sse(response.text)
    deltas = "".join(data["content"] for name, data in events if name == "delta")
    assert deltas == "Привет"


def test_regenerate(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    response = client.post(f"/api/chats/{chat['id']}/regenerate")
    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Привет!"

    messages = client.get(f"/api/chats/{chat['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_regenerate_without_messages(client: TestClient, fake_api) -> None:
    """A chat with no messages still has a system prompt, so regeneration works."""
    _configure(client)
    chat = _create_chat(client)
    response = client.post(f"/api/chats/{chat['id']}/regenerate")
    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Привет!"


def test_derive_title() -> None:
    assert derive_title("Привет") == "Привет"
    assert derive_title("   ") == "Новый чат"
    assert derive_title("# Заголовок") == "Заголовок"
    long_text = "слово " * 40
    title = derive_title(long_text)
    assert len(title) <= 61
    assert title.endswith("…")
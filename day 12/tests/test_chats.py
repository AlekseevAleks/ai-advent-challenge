"""Tests for chat CRUD endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_chat(client: TestClient) -> None:
    response = client.post("/api/chats", json={"model": "gpt-4o-mini"})
    assert response.status_code == 201
    chat = response.json()
    assert chat["model"] == "gpt-4o-mini"
    assert chat["title"] == "Новый чат"
    assert chat["id"]
    assert chat["message_count"] == 0


def test_create_chat_requires_model(client: TestClient) -> None:
    response = client.post("/api/chats", json={"model": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_list_chats(client: TestClient) -> None:
    assert client.get("/api/chats").json()["chats"] == []

    first = client.post("/api/chats", json={"model": "gpt-4o-mini"}).json()
    second = client.post("/api/chats", json={"model": "gpt-4o"}).json()

    chats = client.get("/api/chats").json()["chats"]
    assert len(chats) == 2
    assert {chat["id"] for chat in chats} == {first["id"], second["id"]}


def test_get_chat(client: TestClient) -> None:
    created = client.post("/api/chats", json={"model": "gpt-4o-mini"}).json()
    response = client.get(f"/api/chats/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_missing_chat_returns_404(client: TestClient) -> None:
    response = client.get("/api/chats/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_delete_chat(client: TestClient) -> None:
    created = client.post("/api/chats", json={"model": "gpt-4o-mini"}).json()
    response = client.delete(f"/api/chats/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/chats/{created['id']}").status_code == 404
    assert client.get("/api/chats").json()["chats"] == []


def test_delete_missing_chat_returns_404(client: TestClient) -> None:
    assert client.delete("/api/chats/nope").status_code == 404


def test_chats_persist_across_restart(
    client: TestClient, app_config, database, settings_service
) -> None:
    created = client.post("/api/chats", json={"model": "gpt-4o-mini"}).json()

    # Simulate a restart: new app instance, same data directory.
    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        chats = second_client.get("/api/chats").json()["chats"]
        assert [chat["id"] for chat in chats] == [created["id"]]


def test_update_chat_title(client: TestClient) -> None:
    created = client.post("/api/chats", json={"model": "gpt-4o-mini"}).json()
    response = client.patch(
        f"/api/chats/{created['id']}", json={"title": "Мой чат"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Мой чат"
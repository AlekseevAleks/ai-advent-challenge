"""Проверки веб-панели, runtime-настроек, проверки моделей и журналов."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient


def test_admin_panel_and_static_assets_are_served(client: TestClient) -> None:
    page = client.get("/")
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")
    assert page.status_code == 200
    assert "Local LLM" in page.text
    assert "logs-title" in page.text
    assert script.status_code == 200
    assert "function loadLogs" in script.text
    assert styles.status_code == 200
    assert "background" in styles.text


def test_admin_settings_hide_api_key_and_mark_immutable_fields(client: TestClient) -> None:
    result = client.get("/api/admin/settings")
    assert result.status_code == 200
    body = result.json()
    assert body["settings"]["ollama_model"] == "test-model"
    assert body["read_only"]["api_key_configured"] is False
    assert "api_key" not in body["read_only"]
    assert "host" in body["immutable_fields"]
    assert body["context_budget"]["ollama_num_ctx"] == 2048


def test_runtime_model_setting_applies_immediately_and_can_reset(client: TestClient) -> None:
    patched = client.patch(
        "/api/admin/settings", json={"ollama_model": "new-local-model:latest"}
    )
    assert patched.status_code == 200
    assert patched.json()["settings"]["ollama_model"] == "new-local-model:latest"
    assert patched.json()["modified"] is True

    client.app.state.llm.chat = AsyncMock(return_value="Модельная строка")
    chat = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "проверка"}]}
    )
    assert chat.status_code == 200
    assert chat.json()["model"] == "new-local-model:latest"

    reset = client.post("/api/admin/settings/reset")
    assert reset.status_code == 200
    assert reset.json()["settings"]["ollama_model"] == "test-model"
    assert reset.json()["modified"] is False


def test_runtime_context_settings_validate_cross_fields(client: TestClient) -> None:
    result = client.patch(
        "/api/admin/settings",
        json={"max_context_tokens": 1900, "max_output_tokens": 200},
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "invalid_setting"
    assert client.app.state.settings.max_context_tokens == 1024


def test_runtime_setting_cannot_change_host_or_api_key(client: TestClient) -> None:
    result = client.patch("/api/admin/settings", json={"host": "0.0.0.0"})
    assert result.status_code == 422  # Pydantic extra=forbid


def test_admin_endpoints_require_api_key_when_configured() -> None:
    from app.config import Settings
    from app.main import create_app

    app = create_app(
        Settings(
            _env_file=None,
            api_key="this-is-a-test-api-key-longer-than-32-chars",
            request_log_enabled=False,
        )
    )
    with TestClient(app) as client:
        response = client.get("/api/admin/settings")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_model_probe_lists_local_tags_without_applying_settings(
    client: TestClient, monkeypatch
) -> None:
    class MockAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "llama3.2:3b",
                            "size": 2_000_000_000,
                            "details": {
                                "family": "llama",
                                "parameter_size": "3.2B",
                                "quantization_level": "Q4_K_M",
                                "context_length": 131072,
                            },
                        },
                        {"name": "qwen2.5:7b", "details": {}},
                    ]
                },
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    before = client.app.state.settings.ollama_model
    response = client.post(
        "/api/admin/models/probe",
        json={
            "ollama_base_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.2:3b",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["model_available"] is True
    assert "qwen2.5:7b" in body["installed_models"]
    assert client.app.state.settings.ollama_model == before


def test_request_log_persists_full_conversation_in_private_json_file(
    client: TestClient, payload: dict[str, object]
) -> None:
    client.app.state.llm.chat = AsyncMock(return_value="ответ-секрет")
    response = client.post("/chat", json=payload)
    assert response.status_code == 200

    listing = client.get("/api/admin/logs?limit=10")
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["status"] == "ok"
    assert "messages" not in item

    detail = client.get(f"/api/admin/logs/{item['id']}")
    assert detail.status_code == 200
    entry = detail.json()
    assert entry["messages"][0]["content"] == "Привет"
    assert entry["response"] == "ответ-секрет"
    assert entry["file"].endswith(".json")

    log_path = client.app.state.request_log_store.directory / entry["file"]
    saved = json.loads(log_path.read_text(encoding="utf-8"))
    assert saved["messages"][0]["content"] == "Привет"
    assert saved["response"] == "ответ-секрет"


def test_rejected_context_is_logged_with_full_message(client: TestClient) -> None:
    response = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "x" * 101}]}
    )
    assert response.status_code == 413
    logs = client.get("/api/admin/logs?status=rejected")
    assert logs.status_code == 200
    entry_id = logs.json()["items"][0]["id"]
    detail = client.get(f"/api/admin/logs/{entry_id}")
    assert detail.json()["messages"][0]["content"] == "x" * 101
    assert detail.json()["error_code"] == "message_too_long"


def test_disabling_request_log_prevents_new_files(client: TestClient) -> None:
    client.app.state.llm.chat = AsyncMock(return_value="temporary")
    before = client.get("/api/admin/logs/stats").json()["files"]
    result = client.patch(
        "/api/admin/settings", json={"request_log_enabled": False}
    )
    assert result.status_code == 200
    response = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "not saved"}]}
    )
    assert response.status_code == 200
    after = client.get("/api/admin/logs/stats").json()["files"]
    assert after == before


def test_delete_logs_removes_json_files_and_index(
    client: TestClient, payload: dict[str, object]
) -> None:
    client.app.state.llm.chat = AsyncMock(return_value="answer")
    client.post("/chat", json=payload)
    result = client.delete("/api/admin/logs")
    assert result.status_code == 200
    assert result.json()["deleted"] >= 1
    assert client.get("/api/admin/logs").json()["items"] == []
    assert client.app.state.request_log_store.stats()["files"] == 0

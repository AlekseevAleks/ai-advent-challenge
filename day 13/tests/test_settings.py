"""Tests for settings endpoints and local storage."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.services.settings_service import mask_api_key


def test_get_settings_defaults(client: TestClient) -> None:
    payload = client.get("/api/settings").json()
    assert payload["api_base_url"] == ""
    assert payload["has_api_key"] is False
    assert payload["is_configured"] is False


def test_save_settings(client: TestClient, app_config) -> None:
    response = client.put(
        "/api/settings",
        json={
            "api_base_url": "https://api.example.com/v1/",
            "api_key": "sk-secret-value-123456",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_base_url"] == "https://api.example.com/v1"
    assert payload["has_api_key"] is True
    assert payload["is_configured"] is True
    # The key must never be returned in clear text.
    assert "sk-secret-value-123456" not in json.dumps(payload)
    assert payload["api_key_masked"].startswith("sk-s")

    stored = json.loads(app_config.config_file.read_text(encoding="utf-8"))
    assert stored["api_key"] == "sk-secret-value-123456"


def test_settings_persist_across_restart(client: TestClient, app_config) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-abc123456"},
    )

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        payload = second_client.get("/api/settings").json()
        assert payload["api_base_url"] == "https://api.example.com/v1"
        assert payload["has_api_key"] is True


def test_api_key_kept_when_omitted(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-keepme12345"},
    )
    response = client.put(
        "/api/settings", json={"api_base_url": "https://other.example.com/v1"}
    )
    assert response.json()["has_api_key"] is True
    assert response.json()["api_base_url"] == "https://other.example.com/v1"


def test_invalid_base_url_rejected(client: TestClient) -> None:
    response = client.put("/api/settings", json={"api_base_url": "not-a-url"})
    assert response.status_code == 422


def test_mask_api_key() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "*****"
    masked = mask_api_key("sk-1234567890abcdef")
    assert masked.startswith("sk-1")
    assert masked.endswith("cdef")
    assert "567890" not in masked


def test_test_connection_without_base_url(client: TestClient) -> None:
    response = client.post("/api/settings/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "Base URL" in payload["message"]


def test_test_connection_success(client: TestClient, fake_api) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )
    response = client.post("/api/settings/test")
    payload = response.json()
    assert payload["ok"] is True
    assert payload["models_count"] == 2


def test_test_connection_auth_error(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        401, {"error": {"message": "Invalid API key"}}
    )
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-bad123456"},
    )
    payload = client.post("/api/settings/test").json()
    assert payload["ok"] is False
    assert "401" in payload["message"]
"""Tests for the model listing endpoint and the AI client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.services.ai_client import AIClient
from backend.utils.errors import (
    AIAuthError,
    AIConnectionError,
    AIResponseFormatError,
    AIRateLimitError,
    NoModelsError,
    SettingsNotConfiguredError,
)


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def test_models_require_settings(client: TestClient) -> None:
    response = client.get("/api/models")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "settings_not_configured"


def test_models_success(client: TestClient, fake_api) -> None:
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert [model["id"] for model in models] == ["gpt-4o", "gpt-4o-mini"]


def test_models_uses_configured_base_url(client: TestClient, fake_api) -> None:
    _configure(client)
    client.get("/api/models")
    requests = fake_api.last_requests()
    assert requests[-1]["url"] == "https://api.example.com/v1/models"
    assert requests[-1]["headers"]["Authorization"] == "Bearer sk-test123456"


def test_models_auth_error(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        401, {"error": {"message": "Invalid API key"}}
    )
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "api_auth_error"
    assert "Invalid API key" in body["message"]


def test_models_rate_limit(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        429, {"error": {"message": "Too many requests"}}
    )
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "api_rate_limit"


def test_models_server_error(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        500, {"error": {"message": "boom"}}
    )
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 502
    assert "500" in response.json()["error"]["message"]


def test_models_empty_list(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        200, {"object": "list", "data": []}
    )
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "no_models"


def test_models_bad_format(client: TestClient, fake_api) -> None:
    fake_api.models_response = fake_api.models_response.__class__(
        200, {"unexpected": True}
    )
    _configure(client)
    response = client.get("/api/models")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "api_bad_response"


@pytest.mark.asyncio
async def test_client_requires_base_url() -> None:
    client = AIClient("", "sk-test")
    with pytest.raises(SettingsNotConfiguredError):
        await client.list_models()


@pytest.mark.asyncio
async def test_client_connection_error(monkeypatch) -> None:
    import httpx

    class BrokenClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", BrokenClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    with pytest.raises(AIConnectionError):
        await client.list_models()


@pytest.mark.asyncio
async def test_client_parses_plain_list(monkeypatch) -> None:
    from tests.conftest import FakeAsyncClient, FakeResponse

    class ListClient(FakeAsyncClient):
        def _route(self, method, url, payload=None):
            return FakeResponse(200, [{"id": "model-a"}, {"id": "model-b"}])

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", ListClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    models = await client.list_models()
    assert [model.id for model in models] == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_client_raises_on_bad_json(monkeypatch) -> None:
    from tests.conftest import FakeAsyncClient, FakeResponse

    class BadJsonClient(FakeAsyncClient):
        def _route(self, method, url, payload=None):
            return FakeResponse(200, None, text="<html>oops</html>")

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", BadJsonClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    with pytest.raises(AIResponseFormatError):
        await client.list_models()


@pytest.mark.asyncio
async def test_client_auth_error_type(monkeypatch) -> None:
    from tests.conftest import FakeAsyncClient, FakeResponse

    class AuthClient(FakeAsyncClient):
        def _route(self, method, url, payload=None):
            return FakeResponse(403, {"error": {"message": "forbidden"}})

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", AuthClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    with pytest.raises(AIAuthError):
        await client.list_models()


@pytest.mark.asyncio
async def test_client_rate_limit_type(monkeypatch) -> None:
    from tests.conftest import FakeAsyncClient, FakeResponse

    class RateClient(FakeAsyncClient):
        def _route(self, method, url, payload=None):
            return FakeResponse(429, {"error": {"message": "slow down"}})

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", RateClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    with pytest.raises(AIRateLimitError):
        await client.list_models()


@pytest.mark.asyncio
async def test_client_no_models(monkeypatch) -> None:
    from tests.conftest import FakeAsyncClient, FakeResponse

    class EmptyClient(FakeAsyncClient):
        def _route(self, method, url, payload=None):
            return FakeResponse(200, {"data": []})

    monkeypatch.setattr("backend.services.ai_client.httpx.AsyncClient", EmptyClient)
    client = AIClient("https://api.example.com/v1", "sk-test")
    with pytest.raises(NoModelsError):
        await client.list_models()
"""Unit-тесты протокольного клиента Ollama без сетевых обращений.

Все HTTP-запросы обрабатываются httpx.MockTransport, поэтому тесты не могут
отправить содержимое сообщений в Ollama, интернет или сторонний сервис.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.llm import (
    OllamaClient,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from app.schemas import ChatMessage


def run(coro):
    """Запускает coroutine в обычном sync pytest-тесте."""
    return asyncio.run(coro)


def make_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Привет")]


def test_chat_sends_history_and_generation_limits(settings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Здравствуйте!"}, "done": True},
        )

    async def scenario() -> str:
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.chat(
                [
                    ChatMessage(role="system", content="Отвечай кратко"),
                    ChatMessage(role="user", content="Привет"),
                ],
                temperature=0.2,
            )
        finally:
            await client.close()

    assert run(scenario()) == "Здравствуйте!"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == settings.ollama_model
    assert payload["stream"] is False
    assert payload["options"]["num_ctx"] == settings.ollama_num_ctx
    assert payload["options"]["num_predict"] == settings.max_output_tokens
    assert payload["options"]["temperature"] == 0.2
    assert len(payload["messages"]) == 2


def test_chat_maps_connection_error_to_unavailable(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def scenario() -> None:
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.chat(make_messages())
        finally:
            await client.close()

    with pytest.raises(OllamaUnavailableError):
        run(scenario())


def test_chat_maps_timeout_to_safe_timeout_error(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow private operation", request=request)

    async def scenario() -> None:
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.chat(make_messages())
        finally:
            await client.close()

    with pytest.raises(OllamaTimeoutError) as caught:
        run(scenario())
    assert "private" not in caught.value.safe_message


def test_chat_maps_missing_model_response(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found, try pulling"})

    async def scenario() -> None:
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.chat(make_messages())
        finally:
            await client.close()

    with pytest.raises(OllamaModelNotFoundError):
        run(scenario())


def test_health_reports_missing_model(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "other:latest"}]})

    async def scenario():
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.health()
        finally:
            await client.close()

    result = run(scenario())
    assert result.status == "model_missing"
    assert result.model_available is False


def test_health_reports_unavailable_without_hanging(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no server", request=request)

    async def scenario():
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.health()
        finally:
            await client.close()

    result = run(scenario())
    assert result.status == "unavailable"
    assert result.model_available is False

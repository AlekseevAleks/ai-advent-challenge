"""Проверяет, что runtime-настройки Ollama используются новым запросом."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.llm import OllamaClient
from app.schemas import ChatMessage


def test_ollama_client_reads_model_and_limits_from_runtime_provider(settings) -> None:
    current = [settings]
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "new model"}},
            request=request,
        )

    async def scenario() -> str:
        client = OllamaClient(settings)
        client.bind_settings_provider(lambda: current[0])
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )
        current[0] = settings.model_copy(
            update={
                "ollama_model": "runtime-model:latest",
                "ollama_num_ctx": 2304,
                "max_output_tokens": 96,
            }
        )
        try:
            return await client.chat([ChatMessage(role="user", content="test")])
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "new model"
    payload = captured["payload"]
    assert payload["model"] == "runtime-model:latest"
    assert payload["options"]["num_ctx"] == 2304
    assert payload["options"]["num_predict"] == 96

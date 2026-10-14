"""Проверки OpenAI-compatible слоя: модели, авторизация, ошибки, стрим.

Все тесты используют моки Ollama: настоящая модель не запускается и
внешние AI-сервисы не вызываются.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import (
    OllamaGeneration,
    OllamaStreamEvent,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from app.main import create_app

ALIAS = "local-llm"
BACKING_MODEL = "test-model"
OPENAI_KEY = "openai-test-key-0123456789abcdef"
PANEL_KEY = "panel-api-key-0123456789abcdefghij"


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(
        _env_file=None,
        host="127.0.0.1",
        port=5012,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model=BACKING_MODEL,
        ollama_timeout=5.0,
        ollama_connect_timeout=1.0,
        ollama_max_retries=0,
        ollama_num_ctx=2048,
        ollama_max_concurrency=1,
        max_message_chars=100,
        max_history_messages=4,
        max_context_tokens=1024,
        max_output_tokens=128,
        context_token_tolerance=0.0,
        tokenizer="heuristic",
        rate_limit="10/minute",
        request_log_enabled=True,
        request_log_dir=str(tmp_path / "request-logs"),
        request_log_max_entries=50,
        openai_model_alias=ALIAS,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def openai_client(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        yield client


def payload(**overrides) -> dict:
    body = {"model": ALIAS, "messages": [{"role": "user", "content": "Привет"}]}
    body.update(overrides)
    return body


def stream_events(*chunks: str, finish_reason: str = "stop"):
    """Подменяет настоящий поток Ollama детерминированными чанками."""

    async def generator():
        for piece in chunks:
            yield OllamaStreamEvent(content=piece)
        yield OllamaStreamEvent(done=True, finish_reason=finish_reason)

    return generator()


def parse_sse(raw: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in raw.split("\n\n")
        if line.startswith("data: {")
    ]


# ------------------------------- /v1/models --------------------------------


def test_models_lists_alias_and_backing_model(openai_client: TestClient) -> None:
    response = openai_client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    ids = [item["id"] for item in body["data"]]
    assert ids == [ALIAS, BACKING_MODEL]
    assert all(item["object"] == "model" for item in body["data"])


def test_models_does_not_invent_created_timestamp(openai_client: TestClient) -> None:
    body = openai_client.get("/v1/models").json()
    assert all(item["created"] == 0 for item in body["data"])


# ------------------------------ Авторизация --------------------------------


def test_models_requires_key_when_configured(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, openai_api_key=OPENAI_KEY))
    with TestClient(app) as client:
        missing = client.get("/v1/models")
        wrong = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
        right = client.get("/v1/models", headers={"Authorization": f"Bearer {OPENAI_KEY}"})
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["type"] == "authentication_error"
    assert right.status_code == 200


def test_models_stays_open_when_flag_disabled(tmp_path) -> None:
    app = create_app(
        make_settings(
            tmp_path,
            openai_api_key=OPENAI_KEY,
            openai_require_api_key_for_models=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/v1/models").status_code == 200


def test_chat_requires_key_when_configured(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, openai_api_key=OPENAI_KEY))
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json=payload())
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert OPENAI_KEY not in response.text


def test_chat_accepts_x_api_key_header(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, openai_api_key=OPENAI_KEY))
    with TestClient(app) as client:
        client.app.state.llm.chat_result = AsyncMock(
            return_value=OllamaGeneration(content="ok")
        )
        response = client.post(
            "/v1/chat/completions", json=payload(), headers={"X-API-Key": OPENAI_KEY}
        )
    assert response.status_code == 200


def test_panel_key_does_not_open_v1_routes(tmp_path) -> None:
    """Разные ключи для панели и для агента не подменяют друг друга."""
    app = create_app(
        make_settings(tmp_path, api_key=PANEL_KEY, openai_api_key=OPENAI_KEY)
    )
    with TestClient(app) as client:
        panel = client.get(
            "/api/admin/settings", headers={"Authorization": f"Bearer {PANEL_KEY}"}
        )
        v1_with_openai_key = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {OPENAI_KEY}"}
        )
        v1_with_panel_key = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {PANEL_KEY}"}
        )
    assert panel.status_code == 200
    assert v1_with_openai_key.status_code == 200
    assert v1_with_panel_key.status_code == 401


def test_openai_key_falls_back_to_api_key_when_not_set(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, api_key=PANEL_KEY))
    with TestClient(app) as client:
        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {PANEL_KEY}"}
        )
    assert response.status_code == 200


# --------------------------- Ответ без стрима ------------------------------


def test_chat_completion_success_shape(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(
            content="Привет! Чем помочь?",
            finish_reason="stop",
            prompt_eval_count=11,
            eval_count=7,
        )
    )
    response = openai_client.post("/v1/chat/completions", json=payload())
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    assert body["model"] == ALIAS
    assert isinstance(body["created"], int) and body["created"] > 0
    choice = body["choices"][0]
    assert choice["message"] == {
        "role": "assistant",
        "content": "Привет! Чем помочь?",
    }
    assert choice["finish_reason"] == "stop"
    assert body["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }


def test_usage_is_omitted_without_real_counters(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="ok")
    )
    body = openai_client.post("/v1/chat/completions", json=payload()).json()
    assert "usage" not in body


def test_length_finish_reason_is_mapped(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="обрезано", finish_reason="length")
    )
    body = openai_client.post("/v1/chat/completions", json=payload()).json()
    assert body["choices"][0]["finish_reason"] == "length"


def test_accepts_real_ollama_model_name(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="ok")
    )
    response = openai_client.post(
        "/v1/chat/completions", json=payload(model=BACKING_MODEL)
    )
    assert response.status_code == 200


def test_full_history_and_sampling_params_are_forwarded(
    openai_client: TestClient,
) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="4")
    )
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(
            messages=[
                {"role": "system", "content": "Отвечай кратко."},
                {"role": "user", "content": "2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "Спасибо"},
            ],
            temperature=0.3,
            max_tokens=64,
        ),
    )
    assert response.status_code == 200
    call = openai_client.app.state.llm.chat_result.await_args
    assert [message.role for message in call.args[0]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert call.kwargs["temperature"] == 0.3
    assert call.kwargs["max_output_tokens"] == 64


def test_max_tokens_is_capped_by_server_limit(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="ok")
    )
    openai_client.post("/v1/chat/completions", json=payload(max_tokens=4096))
    passed = openai_client.app.state.llm.chat_result.await_args.kwargs["max_output_tokens"]
    assert passed == 128


# ------------------------------ Ошибки запроса -----------------------------


def test_unknown_model_returns_404(openai_client: TestClient) -> None:
    response = openai_client.post("/v1/chat/completions", json=payload(model="gpt-4o"))
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "model_not_found"
    assert "gpt-4o" in error["message"]


def test_empty_message_is_rejected(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(messages=[{"role": "user", "content": "   "}]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_unsupported_role_is_rejected(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(messages=[{"role": "tool", "content": "x"}]),
    )
    assert response.status_code == 400
    assert "role" in response.json()["error"]["message"]


def test_unsupported_parameter_is_rejected(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions", json=payload(tools=[{"type": "function"}])
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_parameter"


def test_malformed_json_returns_openai_error(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert "Traceback" not in response.text


def test_assistant_as_last_message_is_rejected(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(messages=[{"role": "assistant", "content": "готово"}]),
    )
    assert response.status_code == 400


def test_stream_options_is_accepted_and_ignored(openai_client: TestClient) -> None:
    """Агенты (в т.ч. OpenAI SDK) добавляют stream_options: запрос не падает."""
    openai_client.app.state.llm.stream_chat = lambda *a, **k: stream_events("ok")
    with openai_client.stream(
        "POST",
        "/v1/chat/completions",
        json=payload(stream=True, stream_options={"include_usage": True}),
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())
    # include_usage не реализован: usage-чанк не выдумывается
    assert "prompt_tokens" not in raw
    assert raw.rstrip().endswith("data: [DONE]")


def test_stream_options_without_stream_is_accepted(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="ok")
    )
    response = openai_client.post(
        "/v1/chat/completions", json=payload(stream_options={"include_usage": True})
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"


def test_stream_rejects_non_boolean_flag(openai_client: TestClient) -> None:
    response = openai_client.post("/v1/chat/completions", json=payload(stream="yes"))
    assert response.status_code == 400


# -------------------------- Ограничения контекста ---------------------------


def test_message_over_char_limit_returns_413(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(messages=[{"role": "user", "content": "x" * 101}]),
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["type"] == "context_length_exceeded"
    assert error["code"] == "message_too_long"


def test_history_over_message_limit_returns_413(openai_client: TestClient) -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
    response = openai_client.post("/v1/chat/completions", json=payload(messages=messages))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_messages"


def test_token_budget_exceeded_returns_413(openai_client: TestClient) -> None:
    from app.limits import ContextLimiter

    narrowed = openai_client.app.state.settings.model_copy(
        update={"max_context_tokens": 20, "context_token_tolerance": 0.0}
    )
    openai_client.app.state.context_limiter = ContextLimiter(narrowed)
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(messages=[{"role": "user", "content": "x" * 50}]),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "context_too_large"


def test_system_message_out_of_position_returns_400(
    openai_client: TestClient,
) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(
            messages=[
                {"role": "user", "content": "Вопрос"},
                {"role": "system", "content": "Инструкция"},
                {"role": "user", "content": "Ещё вопрос"},
            ]
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_history"


# ------------------------------- Rate limit --------------------------------


def test_rate_limit_returns_429_in_openai_format(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, rate_limit="1/minute"))
    with TestClient(app) as client:
        client.app.state.llm.chat_result = AsyncMock(
            return_value=OllamaGeneration(content="ok")
        )
        first = client.post("/v1/chat/completions", json=payload())
        second = client.post("/v1/chat/completions", json=payload())
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get("retry-after")
    assert second.json()["error"]["code"] == "rate_limit_exceeded"


# ------------------------------- Ошибки Ollama -----------------------------


def test_ollama_unavailable_returns_503(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        side_effect=OllamaUnavailableError()
    )
    response = openai_client.post("/v1/chat/completions", json=payload())
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "ollama_unavailable"
    assert error["type"] == "server_error"


def test_timeout_returns_504(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(side_effect=OllamaTimeoutError())
    response = openai_client.post("/v1/chat/completions", json=payload())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ollama_timeout"


# --------------------------- Потоковая генерация ----------------------------


def test_stream_returns_openai_sse_chunks(openai_client: TestClient) -> None:
    openai_client.app.state.llm.stream_chat = lambda *a, **k: stream_events(
        "Привет", ", ", "мир"
    )
    with openai_client.stream(
        "POST", "/v1/chat/completions", json=payload(stream=True)
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())

    chunks = parse_sse(raw)
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert all(item["object"] == "chat.completion.chunk" for item in chunks)
    assert all(item["model"] == ALIAS for item in chunks)
    text = "".join(
        item["choices"][0]["delta"].get("content", "") for item in chunks[1:-1]
    )
    assert text == "Привет, мир"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert raw.rstrip().endswith("data: [DONE]")


def test_stream_maps_length_finish_reason(openai_client: TestClient) -> None:
    openai_client.app.state.llm.stream_chat = lambda *a, **k: stream_events(
        "обрезано", finish_reason="length"
    )
    with openai_client.stream(
        "POST", "/v1/chat/completions", json=payload(stream=True)
    ) as response:
        raw = "".join(response.iter_text())
    assert parse_sse(raw)[-1]["choices"][0]["finish_reason"] == "length"


def test_stream_does_not_invent_usage(openai_client: TestClient) -> None:
    openai_client.app.state.llm.stream_chat = lambda *a, **k: stream_events("ok")
    with openai_client.stream(
        "POST", "/v1/chat/completions", json=payload(stream=True)
    ) as response:
        raw = "".join(response.iter_text())
    assert "prompt_tokens" not in raw
    assert "total_tokens" not in raw


def test_stream_reports_error_then_finishes(openai_client: TestClient) -> None:
    async def failing_stream():
        yield OllamaStreamEvent(content="часть")
        raise OllamaUnavailableError()

    openai_client.app.state.llm.stream_chat = lambda *a, **k: failing_stream()
    with openai_client.stream(
        "POST", "/v1/chat/completions", json=payload(stream=True)
    ) as response:
        raw = "".join(response.iter_text())
    compact = raw.replace(" ", "").replace("\n", "")
    assert '"code":"ollama_unavailable"' in compact
    assert raw.rstrip().endswith("data: [DONE]")


def test_context_rejection_happens_before_stream(openai_client: TestClient) -> None:
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(stream=True, messages=[{"role": "user", "content": "x" * 101}]),
    )
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/json")


# ------------------------------ Журналирование ------------------------------


def test_openai_requests_are_recorded_with_full_content(
    openai_client: TestClient,
) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="журнал-ответ")
    )
    openai_client.post("/v1/chat/completions", json=payload())
    listing = openai_client.get("/api/admin/logs?limit=5").json()
    assert listing["total"] == 1
    entry_id = listing["items"][0]["id"]
    detail = openai_client.get(f"/api/admin/logs/{entry_id}").json()
    assert detail["messages"][0]["content"] == "Привет"
    assert detail["response"] == "журнал-ответ"
    assert ALIAS in detail["model"]


def test_stream_options_are_accepted(openai_client: TestClient) -> None:
    """Некоторые OpenAI-клиенты добавляют stream_options сами: это не ошибка."""
    openai_client.app.state.llm.stream_chat = lambda *a, **k: stream_events("ok")
    with openai_client.stream(
        "POST",
        "/v1/chat/completions",
        json=payload(stream=True, stream_options={"include_usage": True}),
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())
    assert raw.rstrip().endswith("data: [DONE]")
    # include_usage не реализован: usage-чанк не отправляется и не подделывается.
    assert "prompt_tokens" not in raw


def test_stream_options_alone_does_not_enable_streaming(openai_client: TestClient) -> None:
    openai_client.app.state.llm.chat_result = AsyncMock(
        return_value=OllamaGeneration(content="полный ответ")
    )
    response = openai_client.post(
        "/v1/chat/completions",
        json=payload(stream_options={"include_usage": True}),
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "полный ответ"

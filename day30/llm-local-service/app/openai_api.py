"""Минимальный OpenAI-compatible Chat Completions API поверх Ollama.

Поддерживаемое подмножество:
* ``GET /v1/models`` — локальный model alias и реальное имя Ollama;
* ``POST /v1/chat/completions`` — messages, model, temperature, max_tokens,
  stream; поток преобразуется из настоящего Ollama NDJSON в OpenAI SSE.

Ключи API читаются из конфигурации, сообщения валидируются Pydantic,
контекст проходит те же проверки, что и legacy ``POST /chat``.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .limits import ContextLimiter, enforce_rate_limit
from .llm import OllamaError, OllamaGeneration
from .request_log import RequestLogStore, new_record
from .schemas import (
    ChatMessage,
    OpenAIChatChoice,
    OpenAIChatCompletionChunk,
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
    OpenAIErrorResponse,
    OpenAIModelCard,
    OpenAIModelList,
    OpenAIStreamChoice,
    OpenAIStreamDelta,
    OpenAIUsage,
)
from .security import (
    get_client_identifier,
    require_openai_api_key,
    require_openai_models_api_key,
)

router = APIRouter()

# Причины остановки Ollama, которые совпадают с OpenAI finish_reason.
FINISH_REASON_LENGTH = "length"


def _error(
    status: int,
    message: str,
    *,
    code: str | None = None,
    error_type: str = "invalid_request_error",
    param: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Ошибка в формате, который ожидает OpenAI SDK."""
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
        headers=headers,
    )


def _finish_reason(reason: str | None) -> str:
    """Переводит done_reason Ollama в поддерживаемое значение OpenAI."""
    return FINISH_REASON_LENGTH if reason == FINISH_REASON_LENGTH else "stop"


def _usage(prompt_count: int | None, completion_count: int | None) -> OpenAIUsage | None:
    """Возвращает usage только при фактических счётчиках от Ollama.

    Оценки и догадки не подставляются: если модель не сообщила eval counts,
    поле опускается целиком.
    """
    if prompt_count is None and completion_count is None:
        return None
    prompt = prompt_count or 0
    completion = completion_count or 0
    return OpenAIUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _start_record(request: Request, messages: list[ChatMessage], output_cap: int):
    """Создаёт запись журнала с полной историей и оценкой входных токенов."""
    settings = request.app.state.settings
    limiter: ContextLimiter = request.app.state.context_limiter
    return new_record(
        client=get_client_identifier(request, settings),
        settings_model=f"{settings.openai_model_alias} ({settings.ollama_model})",
        ollama_base_url=settings.ollama_base_url,
        messages=[message.model_dump() for message in messages],
        estimated_input_tokens=limiter.estimate_messages_tokens(messages),
        max_output_tokens=output_cap,
        num_ctx=settings.ollama_num_ctx,
    )


def _finish_record(record, *, status: str, http_status: int, started: float) -> None:
    """Фиксирует исход запроса и время выполнения в журнале."""
    record.status = status
    record.http_status = http_status
    record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    record.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@router.get(
    "/v1/models",
    response_model=OpenAIModelList,
    tags=["openai"],
    summary="Список моделей в формате OpenAI Models API",
    dependencies=[Depends(require_openai_models_api_key)],
)
async def list_models(request: Request) -> OpenAIModelList:
    """Отдаёт публичный алиас и имя модели, обслуживающей запросы.

    ``created=0`` означает, что дата создания настройки неизвестна:
    сервер не придумывает метку времени. Модели при этом не скачиваются
    и не загружаются — маршрут только читает конфигурацию.
    """
    settings = request.app.state.settings
    names = list(dict.fromkeys((settings.openai_model_alias, settings.ollama_model)))
    return OpenAIModelList(
        data=[
            OpenAIModelCard(id=name, created=0, owned_by="local-ollama")
            for name in names
        ]
    )


@router.post(
    "/v1/chat/completions",
    tags=["openai"],
    summary="OpenAI Chat Completions-совместимый маршрут",
    dependencies=[Depends(require_openai_api_key), Depends(enforce_rate_limit)],
    responses={
        400: {"model": OpenAIErrorResponse},
        401: {"model": OpenAIErrorResponse},
        404: {"model": OpenAIErrorResponse},
        413: {"model": OpenAIErrorResponse},
        429: {"model": OpenAIErrorResponse},
        503: {"model": OpenAIErrorResponse},
        504: {"model": OpenAIErrorResponse},
    },
)
async def chat_completions(request: Request, payload: OpenAIChatCompletionRequest):
    """Проверяет модель и контекст, затем отдаёт JSON или SSE-поток.

    Порядок обработки: авторизация (dependency) → имя модели → лимиты
    контекста → генерация Ollama → формат OpenAI. Действуют те же rate
    limit, журналирование и обработка ошибок, что и у legacy ``/chat``.
    """
    settings = request.app.state.settings
    requested_model = payload.model.strip()
    if requested_model not in {settings.openai_model_alias, settings.ollama_model}:
        return _error(
            404,
            f"Модель '{requested_model}' недоступна. Используйте "
            f"'{settings.openai_model_alias}' или '{settings.ollama_model}'.",
            code="model_not_found",
        )

    messages = [ChatMessage(role=item.role, content=item.content) for item in payload.messages]
    limiter: ContextLimiter = request.app.state.context_limiter
    check = limiter.check(messages)
    output_cap = min(
        payload.max_tokens or settings.max_output_tokens,
        settings.max_output_tokens,
    )
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    record = _start_record(request, messages, output_cap)
    log_store: RequestLogStore = request.app.state.request_log_store
    started = time.perf_counter()

    if not check.ok:
        _finish_record(record, status="rejected", http_status=check.http_status, started=started)
        record.error_code = check.reason
        record.error_message = check.message
        await log_store.flush(record)
        return _error(
            check.http_status,
            check.message,
            code=check.reason,
            error_type="context_length_exceeded",
        )

    if not payload.stream:
        try:
            generation: OllamaGeneration = await request.app.state.llm.chat_result(
                messages,
                temperature=payload.temperature,
                max_output_tokens=output_cap,
            )
        except OllamaError as exc:
            _finish_record(record, status="error", http_status=exc.http_status, started=started)
            record.error_code = exc.code
            record.error_message = exc.safe_message
            await log_store.flush(record)
            return _error(
                exc.http_status,
                exc.safe_message,
                code=exc.code,
                error_type="server_error",
            )

        _finish_record(record, status="ok", http_status=200, started=started)
        record.response = generation.content
        record.response_chars = len(generation.content)
        await log_store.flush(record)
        completion = OpenAIChatCompletionResponse(
            id=completion_id,
            created=created,
            model=settings.openai_model_alias,
            choices=[
                OpenAIChatChoice(
                    message={"role": "assistant", "content": generation.content},
                    finish_reason=_finish_reason(generation.finish_reason),
                )
            ],
            usage=_usage(generation.prompt_eval_count, generation.eval_count),
        )
        return JSONResponse(
            content=json.loads(completion.model_dump_json(exclude_none=True))
        )

    async def event_stream() -> AsyncIterator[str]:
        """Переводит настоящий поток Ollama в чанки OpenAI SSE."""
        collected: list[str] = []
        finish = "stop"

        def sse(data: dict[str, Any]) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

        def chunk(delta: OpenAIStreamDelta, finish_reason: str | None = None):
            response = OpenAIChatCompletionChunk(
                id=completion_id,
                created=created,
                model=settings.openai_model_alias,
                choices=[OpenAIStreamChoice(delta=delta, finish_reason=finish_reason)],
            )
            return json.loads(response.model_dump_json(exclude_none=True))

        yield sse(chunk(OpenAIStreamDelta(role="assistant")))
        try:
            async for event in request.app.state.llm.stream_chat(
                messages,
                temperature=payload.temperature,
                max_output_tokens=output_cap,
            ):
                if event.content:
                    collected.append(event.content)
                    yield sse(chunk(OpenAIStreamDelta(content=event.content)))
                if event.done:
                    finish = _finish_reason(event.finish_reason)
        except OllamaError as exc:
            _finish_record(record, status="error", http_status=exc.http_status, started=started)
            record.error_code = exc.code
            record.error_message = exc.safe_message
            record.response = "".join(collected) or None
            record.response_chars = len(record.response or "")
            await log_store.flush(record)
            yield sse(
                {
                    "error": {
                        "message": exc.safe_message,
                        "type": "server_error",
                        "param": None,
                        "code": exc.code,
                    }
                }
            )
            yield "data: [DONE]\n\n"
            return

        yield sse(chunk(OpenAIStreamDelta(), finish_reason=finish))
        # В режиме stream usage не отправляется: стандартный поток OpenAI
        # не гарантирует usage-чанк, а оценка токенов была бы выдуманной.
        yield "data: [DONE]\n\n"
        _finish_record(record, status="ok", http_status=200, started=started)
        record.response = "".join(collected)
        record.response_chars = len(record.response)
        await log_store.flush(record)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

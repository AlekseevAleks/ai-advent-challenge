"""FastAPI-приложение локального LLM-сервиса.

Маршруты:
  * ``GET /health/live`` — liveness, не зависит от Ollama;
  * ``GET /health``      — проверяет API и локальную модель Ollama;
  * ``POST /chat``       — проверяет лимиты и передаёт историю локальной LLM;
  * ``GET /docs``        — автоматически генерируемая Swagger UI.

FastAPI не сохраняет историю чата между запросами: клиент передаёт полную историю
в каждом POST /chat. Если включён REQUEST_LOG_ENABLED, журнал сохраняет полные
тексты запросов и ответов в JSON-файлах (см. предупреждение в README и UI).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .config import Settings, get_settings
from .limits import (
    ContextLimiter,
    InMemoryRateLimiter,
    enforce_rate_limit,
)
from .llm import (
    OllamaClient,
    OllamaError,
    OllamaGeneration,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthStatus,
    LiveStatus,
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
    ChatMessage,
)
from .request_log import RequestLogStore, new_record
from .schemas import (
    OllamaProbeRequest,
    OllamaProbeResponse,
    RequestLogEntry,
    RequestLogPage,
    RequestLogStats,
    RuntimeSettingsPatch,
)
from .security import (
    RateLimitViolationLog,
    get_client_identifier,
    log_security_warnings,
    require_api_key,
    require_openai_api_key,
    require_openai_models_api_key,
    require_valid_api_key,
)
from .settings_store import SettingsStore


def configure_logging(settings: Settings) -> None:
    """Настраивает логи без пользовательского содержимого."""
    if settings.log_level == "SILENT":
        logging.disable(logging.CRITICAL)
        return
    logging.disable(logging.NOTSET)
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


class RequestBodySizeLimitMiddleware:
    """Ограничивает размер JSON-тела /chat, включая chunked-запросы.

    ``Content-Length`` может отсутствовать или быть подделан. Поэтому
    middleware сам читает поток ASGI до установленного максимума и только
    затем передаёт его FastAPI. Максимальный размер берётся из лимитов
    сообщения и истории, имеет минимум для JSON-обёртки и ограничен 16 MiB.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int, settings_store=None) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.settings_store = settings_store

    def _current_max_body_bytes(self) -> int:
        if self.settings_store is None:
            return self.max_body_bytes
        settings = self.settings_store.current
        return min(
            16 * 1024 * 1024,
            max(
                64 * 1024,
                settings.max_message_chars * settings.max_history_messages * 4
                + 64 * 1024,
            ),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/chat"
        ):
            await self.app(scope, receive, send)
            return

        max_body_bytes = self._current_max_body_bytes()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > self.max_body_bytes:
                    await self._too_large(send, max_body_bytes)
                    return
            except ValueError:
                await self._bad_request(send)
                return

        chunks: list[bytes] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_body_bytes:
                await self._too_large(send, max_body_bytes)
                return
            chunks.append(chunk)
            more_body = message.get("more_body", False)

        body = b"".join(chunks)
        already_sent = False

        async def replay_receive() -> Message:
            nonlocal already_sent
            if not already_sent:
                already_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    async def _too_large(self, send: Send, max_body_bytes: int) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "request_body_too_large",
                    "message": "Размер тела запроса превышает допустимый лимит.",
                    "details": {"max_body_bytes": max_body_bytes},
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _bad_request(self, send: Send) -> None:
        body = '{"error":{"code":"invalid_content_length","message":"Некорректный Content-Length."}}'.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Создаёт единый JSON-формат ошибки legacy/admin API."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }


def _openai_error_response(
    status_code: int,
    message: str,
    *,
    error_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Создаёт error object в формате OpenAI SDK."""
    return JSONResponse(
        status_code=status_code,
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; фабрика упрощает изолированные тесты."""
    active_settings = settings or get_settings()
    configure_logging(active_settings)
    log_security_warnings(active_settings)

    llm = OllamaClient(active_settings)
    settings_store = SettingsStore(active_settings)
    llm.bind_settings_provider(lambda: settings_store.current)
    context_limiter = ContextLimiter(active_settings)
    request_log_store = RequestLogStore(
        Path(active_settings.request_log_dir),
        enabled=active_settings.request_log_enabled,
        max_entries=active_settings.request_log_max_entries,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await llm.start()
        try:
            yield
        finally:
            await llm.close()

    application = FastAPI(
        title="Локальный приватный LLM API",
        description=(
            "HTTP API для локальной языковой модели через Ollama. "
            "Все генерации выполняются локально; внешние AI API не используются."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.settings = active_settings
    application.state.settings_store = settings_store
    application.state.llm = llm
    application.state.context_limiter = context_limiter
    application.state.request_log_store = request_log_store
    application.state.rate_limiter = InMemoryRateLimiter()
    application.state.rate_limit_violations = RateLimitViolationLog(
        active_settings.rate_limit_violation_buffer
    )

    max_body_bytes = min(
        16 * 1024 * 1024,
        max(
            64 * 1024,
            active_settings.max_message_chars
            * active_settings.max_history_messages
            * 4
            + 64 * 1024,
        ),
    )
    application.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_body_bytes=max_body_bytes,
        settings_store=settings_store,
    )

    static_dir = Path(__file__).with_name("static")
    application.mount(
        "/static",
        StaticFiles(directory=str(static_dir), check_dir=True),
        name="admin-static",
    )

    @application.get("/", include_in_schema=False)
    async def admin_panel() -> FileResponse:
        """Главная страница локальной панели управления."""
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Возвращает безопасные и понятные ошибки Pydantic."""
        is_openai = request.url.path.startswith("/v1/")
        errors = exc.errors()
        first = errors[0] if errors else {}
        location = ".".join(str(item) for item in first.get("loc", ()) if item not in {"body", "query"})
        error_type = str(first.get("type", ""))
        if error_type == "json_invalid":
            message = "Request body must be valid JSON."
        elif error_type == "extra_forbidden":
            message = f"Unsupported parameter: {location or 'unknown'}."
        elif location:
            message = f"Invalid value for '{location}'."
        else:
            message = "Invalid request format."
        if is_openai:
            return _openai_error_response(
                400,
                message,
                code="unsupported_parameter" if error_type == "extra_forbidden" else "invalid_request_error",
                param=location or None,
            )
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "validation_error",
                "Тело запроса некорректно. Проверьте формат и допустимые поля.",
                {"field": location or None},
            ),
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Унифицирует ошибки FastAPI и сохраняет безопасные заголовки."""
        detail = exc.detail
        if request.url.path.startswith("/v1/"):
            if isinstance(detail, dict):
                code = str(detail.get("code", "request_error"))
                message = str(detail.get("message", "Request rejected."))
            else:
                code = "request_error"
                message = str(detail) if isinstance(detail, str) else "Request rejected."
            error_type = "authentication_error" if exc.status_code == 401 else "invalid_request_error"
            return _openai_error_response(
                exc.status_code,
                message,
                error_type=error_type,
                code=code,
                headers=dict(exc.headers or {}),
            )
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            code = str(detail.get("code", "http_error"))
            message = str(detail.get("message", "Запрос не выполнен."))
            details = detail.get("details")
        else:
            code = "http_error"
            message = str(detail) if isinstance(detail, str) else "Запрос не выполнен."
            details = None
        headers = dict(exc.headers or {})
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, message, details),
            headers=headers,
        )

    @application.exception_handler(OllamaError)
    async def ollama_exception_handler(request: Request, exc: OllamaError) -> JSONResponse:
        """Преобразует внутреннюю ошибку Ollama в безопасный ответ API."""
        if request.url.path.startswith("/v1/"):
            return _openai_error_response(
                exc.http_status,
                exc.safe_message,
                error_type="server_error",
                code=exc.code,
            )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_payload(exc.code, exc.safe_message),
        )

    @application.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Последняя защита от раскрытия трассировки и внутреннего исключения."""
        logging.getLogger("app.main").error(
            "Необработанная ошибка: %s", type(exc).__name__
        )
        if request.url.path.startswith("/v1/"):
            return _openai_error_response(
                500,
                "An internal server error occurred.",
                error_type="server_error",
                code="internal_error",
            )
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "internal_error",
                "Внутренняя ошибка сервиса. Подробности не записываются в API-ответ.",
            ),
        )

    @application.get(
        "/api/admin/settings",
        tags=["admin"],
        summary="Прочитать изменяемые настройки (секреты не возвращаются)",
        dependencies=[Depends(require_api_key)],
    )
    async def get_runtime_settings(request: Request) -> dict[str, Any]:
        return request.app.state.settings_store.as_payload()

    def apply_runtime_settings(application: FastAPI) -> dict[str, Any]:
        """Синхронизирует runtime-зависимости после settings update/reset."""
        current = application.state.settings_store.current
        application.state.settings = current
        application.state.context_limiter = ContextLimiter(current)
        application.state.request_log_store.enabled = current.request_log_enabled
        return application.state.settings_store.as_payload()

    @application.patch(
        "/api/admin/settings",
        tags=["admin"],
        summary="Изменить настройки в памяти без перезапуска",
        dependencies=[Depends(require_api_key)],
    )
    async def patch_runtime_settings(
        request: Request, patch: RuntimeSettingsPatch
    ) -> dict[str, Any]:
        payload = request.app.state.settings_store.update(patch)
        apply_runtime_settings(request.app)
        return payload

    @application.post(
        "/api/admin/settings/reset",
        tags=["admin"],
        summary="Сбросить настройки к значениям из .env",
        dependencies=[Depends(require_api_key)],
    )
    async def reset_runtime_settings(request: Request) -> dict[str, Any]:
        request.app.state.settings_store.reset()
        return apply_runtime_settings(request.app)

    async def probe_ollama(
        request: Request, probe: OllamaProbeRequest
    ) -> dict[str, Any]:
        """Безопасно проверяет Ollama и список моделей без скачивания."""
        current = request.app.state.settings
        overrides = probe.model_dump(exclude_none=True)
        try:
            candidate = Settings(**{**current.model_dump(), **overrides})
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_ollama_settings",
                    "message": str(exc).split("\n")[0],
                    "details": None,
                },
            ) from exc

        try:
            timeout = httpx.Timeout(
                min(8.0, candidate.ollama_timeout),
                connect=min(3.0, candidate.ollama_connect_timeout),
            )
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                headers={"User-Agent": "local-llm-service/1.0"},
            ) as client:
                response = await client.get(
                    f"{candidate.ollama_base_url}/api/tags"
                )
        except httpx.TimeoutException:
            return OllamaProbeResponse(
                reachable=False,
                model_available=False,
                installed_models=[],
                detail="Таймаут при проверке Ollama.",
                current_model=candidate.ollama_model,
                base_url=candidate.ollama_base_url,
            ).model_dump()
        except httpx.HTTPError as exc:
            logging.getLogger("app.main").info(
                "Проверка Ollama завершилась ошибкой соединения: %s",
                type(exc).__name__,
            )
            return OllamaProbeResponse(
                reachable=False,
                model_available=False,
                installed_models=[],
                detail="Не удалось подключиться к Ollama по указанному адресу.",
                current_model=candidate.ollama_model,
                base_url=candidate.ollama_base_url,
            ).model_dump()

        if response.status_code >= 400:
            return OllamaProbeResponse(
                reachable=False,
                model_available=False,
                installed_models=[],
                detail=f"Ollama вернула HTTP {response.status_code}.",
                current_model=candidate.ollama_model,
                base_url=candidate.ollama_base_url,
            ).model_dump()

        try:
            raw_models = response.json().get("models", [])
            model_names = [
                str(item.get("name", ""))
                for item in raw_models
                if isinstance(item, dict) and item.get("name")
            ]
        except (ValueError, AttributeError, TypeError):
            return OllamaProbeResponse(
                reachable=True,
                model_available=False,
                installed_models=[],
                detail="Ответ Ollama имеет неизвестный формат.",
                current_model=candidate.ollama_model,
                base_url=candidate.ollama_base_url,
            ).model_dump()

        available = any(
            OllamaClient._matches_model(name, candidate.ollama_model)
            for name in model_names
        )
        detail = (
            "Модель установлена и доступна."
            if available
            else "Ollama доступна, но выбранной модели нет в списке."
        )
        return OllamaProbeResponse(
            reachable=True,
            model_available=available,
            installed_models=model_names,
            detail=detail,
            current_model=candidate.ollama_model,
            base_url=candidate.ollama_base_url,
        ).model_dump()

    @application.get(
        "/api/admin/models",
        tags=["admin"],
        summary="Проверить Ollama и получить список установленных моделей",
        dependencies=[Depends(require_api_key)],
    )
    async def list_local_models(request: Request) -> dict[str, Any]:
        current = request.app.state.settings
        return await probe_ollama(
            request,
            OllamaProbeRequest(
                ollama_base_url=current.ollama_base_url,
                ollama_model=current.ollama_model,
            ),
        )

    @application.post(
        "/api/admin/models/probe",
        tags=["admin"],
        summary="Проверить адрес Ollama и модель до применения",
        dependencies=[Depends(require_api_key)],
    )
    async def probe_local_models(
        request: Request, probe: OllamaProbeRequest
    ) -> dict[str, Any]:
        return await probe_ollama(request, probe)

    @application.get(
        "/api/admin/logs/stats",
        response_model=RequestLogStats,
        tags=["admin"],
        summary="Сводка по JSON-журналу запросов",
        dependencies=[Depends(require_api_key)],
    )
    async def request_log_stats(request: Request) -> dict[str, Any]:
        return request.app.state.request_log_store.stats()

    @application.get(
        "/api/admin/logs",
        response_model=RequestLogPage,
        tags=["admin"],
        summary="Список запросов к модели (метаданные)",
        dependencies=[Depends(require_api_key)],
    )
    async def request_log_list(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None, max_length=32),
        client: str | None = Query(default=None, max_length=128),
        model: str | None = Query(default=None, max_length=128),
        search: str | None = Query(default=None, max_length=128),
    ) -> dict[str, Any]:
        return request.app.state.request_log_store.list_entries(
            limit=limit,
            offset=offset,
            status=status,
            client=client,
            model=model,
            search=search,
        )

    @application.get(
        "/api/admin/logs/{record_id}",
        response_model=RequestLogEntry,
        tags=["admin"],
        summary="Прочитать запись журнала целиком (включая сообщения и ответ)",
        dependencies=[Depends(require_api_key)],
    )
    async def request_log_detail(request: Request, record_id: str) -> dict[str, Any]:
        record = request.app.state.request_log_store.get_entry(record_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "log_entry_not_found",
                    "message": "Запись не найдена в текущем журнале.",
                    "details": None,
                },
            )
        return record.to_dict()

    @application.delete(
        "/api/admin/logs",
        tags=["admin"],
        summary="Удалить JSON-файлы журнала и очистить индекс",
        dependencies=[Depends(require_api_key)],
    )
    async def delete_request_logs(request: Request) -> dict[str, Any]:
        return request.app.state.request_log_store.clear()

    @application.get(
        "/health/live",
        response_model=LiveStatus,
        tags=["health"],
        summary="Проверить, что процесс API работает",
    )
    async def health_live() -> LiveStatus:
        """Liveness probe: не обращается к Ollama и не зависает."""
        return LiveStatus(version=__version__)

    @application.get(
        "/health",
        response_model=HealthStatus,
        responses={503: {"model": HealthStatus}},
        tags=["health"],
        summary="Проверить API и доступность локальной модели",
    )
    async def health(request: Request) -> JSONResponse:
        """Проверяет Ollama с коротким таймаутом (не более 3 секунд)."""
        result = await request.app.state.llm.health()
        current = request.app.state.settings
        payload = HealthStatus(
            status="ok" if result.status == "ok" else "degraded",
            api="ok",
            ollama=result.status,
            ollama_url=current.ollama_base_url,
            model=current.ollama_model,
            model_available=result.model_available,
            detail=result.detail,
        )
        return JSONResponse(
            status_code=200 if result.status == "ok" else 503,
            content=payload.model_dump(),
        )

    @application.post(
        "/chat",
        response_model=ChatResponse,
        responses={
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
        tags=["chat"],
        summary="Отправить историю сообщений локальной модели",
        dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
    )
    async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
        """Валидирует запрос, пишет полный журнал и вызывает локальную модель."""
        current = request.app.state.settings
        limiter: ContextLimiter = request.app.state.context_limiter
        log_store: RequestLogStore = request.app.state.request_log_store
        result = limiter.check(payload.messages)
        message_dicts = [message.model_dump() for message in payload.messages]
        estimated = result.estimated_tokens or limiter.estimate_messages_tokens(
            payload.messages
        )
        record = new_record(
            client=get_client_identifier(request, current),
            settings_model=current.ollama_model,
            ollama_base_url=current.ollama_base_url,
            messages=message_dicts,
            estimated_input_tokens=estimated,
            max_output_tokens=current.max_output_tokens,
            num_ctx=current.ollama_num_ctx,
        )
        started = time.perf_counter()

        if not result.ok:
            record.status = "rejected"
            record.http_status = result.http_status
            record.error_code = result.reason
            record.error_message = result.message
            record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            await log_store.flush(record)
            return JSONResponse(
                status_code=result.http_status,
                content=_error_payload(result.reason, result.message, result.details),
            )  # type: ignore[return-value]

        try:
            response_text = await request.app.state.llm.chat(
                payload.messages,
                temperature=payload.temperature,
            )
        except OllamaError as exc:
            record.status = "error"
            record.http_status = exc.http_status
            record.error_code = exc.code
            record.error_message = exc.safe_message
            record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            await log_store.flush(record)
            raise
        except Exception:
            record.status = "error"
            record.http_status = 500
            record.error_code = "internal_error"
            record.error_message = "Внутренняя ошибка сервиса."
            record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            await log_store.flush(record)
            raise

        record.status = "ok"
        record.http_status = 200
        record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record.response = response_text
        record.response_chars = len(response_text)
        record.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        await log_store.flush(record)
        return ChatResponse(
            response=response_text,
            model=current.ollama_model,
            done=True,
        )

    from .openai_api import router as openai_router

    application.include_router(openai_router)
    return application


# ASGI entrypoint: uvicorn app.main:app
app = create_app()

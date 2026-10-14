"""Асинхронный клиент для локального Ollama HTTP API.

Используются только два локальных endpoint Ollama:
  * ``GET /api/tags`` — проверка доступности и наличия модели;
  * ``POST /api/chat`` — генерация ответа по истории сообщений.

Запросы никогда не отправляются внешним AI-провайдерам. Таймауты,
ошибки соединения и отсутствие модели преобразуются в типизированные
исключения без передачи внутренних деталей API-клиенту.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

import httpx

from .config import Settings
from .schemas import ChatMessage

logger = logging.getLogger("app.llm")


class OllamaError(Exception):
    """Базовая ошибка взаимодействия с Ollama."""

    code = "ollama_error"
    safe_message = "Ошибка при обращении к локальной модели."
    http_status = 502


class OllamaUnavailableError(OllamaError):
    """Ollama не запущена либо недоступна по сети."""

    code = "ollama_unavailable"
    safe_message = "Локальный сервер Ollama недоступен. Запустите Ollama и повторите запрос."
    http_status = 503


class OllamaModelNotFoundError(OllamaError):
    """Запрошенная модель не установлена в Ollama."""

    code = "model_not_found"
    safe_message = (
        "Модель не установлена в Ollama. Выполните `ollama pull <имя-модели>` "
        "и проверьте OLLAMA_MODEL."
    )
    http_status = 503


class OllamaTimeoutError(OllamaError):
    """Истёк таймаут соединения или генерации."""

    code = "ollama_timeout"
    safe_message = (
        "Локальная модель не успела ответить за отведённое время. "
        "Попробуйте повторить запрос или увеличить OLLAMA_TIMEOUT."
    )
    http_status = 504


class OllamaResponseError(OllamaError):
    """Ollama вернула некорректный ответ либо HTTP-ошибку."""

    code = "ollama_response_error"
    safe_message = "Локальный сервер модели вернул ошибку."
    http_status = 502


@dataclass(frozen=True)
class OllamaHealth:
    """Результат проверки Ollama и наличия выбранной модели."""

    status: str  # ok | unavailable | model_missing | error
    model_available: bool
    detail: str


@dataclass(frozen=True)
class OllamaGeneration:
    """Ответ Ollama и только фактически сообщённая моделью статистика."""

    content: str
    finish_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@dataclass(frozen=True)
class OllamaStreamEvent:
    """Один фрагмент реального Ollama stream либо терминальная статистика."""

    content: str | None = None
    done: bool = False
    finish_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class OllamaClient:
    """Жизненный цикл HTTPX-клиента и запросы к Ollama."""

    def __init__(self, settings: Settings) -> None:
        self._base_settings = settings
        self._settings_provider: Callable[[], Settings] | None = None
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_limit = -1

    @property
    def settings(self) -> Settings:
        """Текущие настройки; могут поступать из runtime-хранилища."""
        if self._settings_provider is not None:
            return self._settings_provider()
        return self._base_settings

    def bind_settings_provider(self, provider: Callable[[], Settings]) -> None:
        """Подключает источник настроек, изменяемых на лету."""
        self._settings_provider = provider

    async def start(self) -> None:
        """Создаёт HTTPX-пул соединений. Вызывать один раз при старте API."""
        if self._client is not None:
            return
        # Для простого lifecycle клиента нужны только connection pool и
        # общие заголовки; адрес/таймаут передаются каждому запросу отдельно,
        # чтобы runtime-настройки применялись без пересоздания пула.
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=16)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=5.0),
            limits=limits,
            headers={"User-Agent": "local-llm-service/1.0"},
            follow_redirects=False,
        )
        self._set_semaphore(self.settings.ollama_max_concurrency)
        logger.info(
            "HTTP-клиент Ollama инициализирован (base_url=%s, model=%s)",
            self.settings.ollama_base_url,
            self.settings.ollama_model,
        )

    def _set_semaphore(self, limit: int) -> None:
        """Обновляет очередь запросов, если её лимит изменился."""
        if limit == self._semaphore_limit:
            return
        self._semaphore_limit = limit
        self._semaphore = asyncio.Semaphore(limit) if limit > 0 else None

    async def close(self) -> None:
        """Закрывает пул HTTP-соединений при остановке API."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._semaphore = None
            self._semaphore_limit = -1

    def _http_client(self) -> httpx.AsyncClient:
        """Возвращает клиент или объясняет ошибку жизненного цикла."""
        if self._client is None:
            raise OllamaUnavailableError("Клиент Ollama ещё не инициализирован")
        return self._client

    @staticmethod
    def _matches_model(installed: str, requested: str) -> bool:
        """Сопоставляет имена модели с учётом тега latest по умолчанию."""
        installed_normalized = installed.strip()
        requested_normalized = requested.strip()
        if installed_normalized == requested_normalized:
            return True
        if ":" not in requested_normalized:
            return installed_normalized in {
                requested_normalized,
                f"{requested_normalized}:latest",
            }
        if ":" not in installed_normalized:
            return f"{installed_normalized}:latest" == requested_normalized
        return False

    async def health(self) -> OllamaHealth:
        """Проверяет доступность Ollama и наличие выбранной модели.

        Использует короткий таймаут, чтобы ``GET /health`` не зависал
        во время запуска/остановки локального сервера.
        """
        try:
            response = await self._http_client().get(
                f"{self.settings.ollama_base_url}/api/tags",
                timeout=httpx.Timeout(3.0, connect=1.0),
            )
        except httpx.TimeoutException:
            return OllamaHealth(
                status="unavailable",
                model_available=False,
                detail="Таймаут проверки локального Ollama.",
            )
        except (httpx.ConnectError, httpx.NetworkError, OllamaUnavailableError):
            return OllamaHealth(
                status="unavailable",
                model_available=False,
                detail="Ollama не запущена или недоступна по указанному адресу.",
            )
        except httpx.HTTPError:
            return OllamaHealth(
                status="error",
                model_available=False,
                detail="Не удалось проверить состояние Ollama.",
            )

        if response.status_code >= 400:
            logger.warning("Ollama health endpoint вернул HTTP %s", response.status_code)
            return OllamaHealth(
                status="error",
                model_available=False,
                detail="Ollama вернула ошибку при проверке состояния.",
            )

        try:
            data = response.json()
            models = data.get("models", [])
            installed_names = [
                item.get("name", "") for item in models if isinstance(item, dict)
            ]
        except (ValueError, AttributeError, TypeError):
            return OllamaHealth(
                status="error",
                model_available=False,
                detail="Ollama вернула ответ в неожиданном формате.",
            )

        settings = self.settings
        found = any(
            self._matches_model(name, settings.ollama_model)
            for name in installed_names
        )
        if not found:
            return OllamaHealth(
                status="model_missing",
                model_available=False,
                detail=(
                    f"Ollama работает, но модель {settings.ollama_model!r} "
                    "не установлена. Выполните `ollama pull <имя-модели>`."
                ),
            )
        return OllamaHealth(
            status="ok",
            model_available=True,
            detail="Ollama доступна, модель установлена.",
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        """Совместимость с legacy API: возвращает только сгенерированный текст."""
        result = await self.chat_result(
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        return result.content

    async def chat_result(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> OllamaGeneration:
        """Генерирует полный non-stream ответ и возвращает только фактические usage counts."""
        settings = self.settings
        client = self._http_client()
        self._set_semaphore(settings.ollama_max_concurrency)
        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": False,
            "options": {
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": min(
                    max_output_tokens or settings.max_output_tokens,
                    settings.max_output_tokens,
                ),
            },
        }
        if temperature is not None:
            payload["options"]["temperature"] = temperature

        async def _perform() -> httpx.Response:
            last_error: Exception | None = None
            for attempt in range(settings.ollama_max_retries + 1):
                try:
                    return await client.post(
                        f"{settings.ollama_base_url}/api/chat",
                        json=payload,
                        timeout=httpx.Timeout(
                            settings.ollama_timeout,
                            connect=settings.ollama_connect_timeout,
                        ),
                    )
                except httpx.TimeoutException as exc:
                    # Генерация могла уже начаться; повтор может дублировать
                    # вычисление, поэтому таймаут не повторяем.
                    raise OllamaTimeoutError() from exc
                except (httpx.ConnectError, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt >= settings.ollama_max_retries:
                        break
                    await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
            raise OllamaUnavailableError() from last_error

        try:
            if self._semaphore is None:
                response = await _perform()
            else:
                async with self._semaphore:
                    response = await _perform()
        except OllamaError:
            raise
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError() from exc
        except httpx.HTTPError as exc:
            logger.warning("Ошибка HTTP-клиента при обращении к Ollama: %s", type(exc).__name__)
            raise OllamaUnavailableError() from exc

        if response.status_code >= 400:
            # Внутреннее тело ответа может содержать системные сведения;
            # не передаём его клиенту API и не пишем в лог.
            if response.status_code == 404:
                raise OllamaModelNotFoundError()
            logger.warning("Ollama /api/chat вернула HTTP %s", response.status_code)
            raise OllamaResponseError()

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaResponseError() from exc

        # Ollama обычно сообщает об отсутствующей модели HTTP 404, но некоторые
        # версии возвращают 200 и поле error — проверяем его тоже.
        if isinstance(data, dict) and data.get("error"):
            error_text = str(data["error"]).lower()
            if "not found" in error_text or "pull" in error_text:
                raise OllamaModelNotFoundError()
            logger.warning("Ollama вернула поле error без раскрытия текста клиенту")
            raise OllamaResponseError()

        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaResponseError() from exc
        if not isinstance(content, str):
            raise OllamaResponseError()
        return OllamaGeneration(
            content=content,
            finish_reason=(
                data.get("done_reason")
                if isinstance(data.get("done_reason"), str)
                else None
            ),
            prompt_eval_count=(
                data.get("prompt_eval_count")
                if isinstance(data.get("prompt_eval_count"), int)
                else None
            ),
            eval_count=(
                data.get("eval_count")
                if isinstance(data.get("eval_count"), int)
                else None
            ),
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[OllamaStreamEvent]:
        """Читает настоящий поток Ollama ``/api/chat`` (JSONL, stream=true).

        Каждое событие с ``content`` несёт порцию сгенерированного текста.
        Последнее событие содержит ``done=True`` и только фактически
        возвращённые Ollama usage counts. Повторного запроса при обрыве
        потока нет, чтобы не дублировать/искажать частичный ответ.
        """
        settings = self.settings
        client = self._http_client()
        self._set_semaphore(settings.ollama_max_concurrency)
        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
            "options": {
                "num_ctx": settings.ollama_num_ctx,
                "num_predict": min(
                    max_output_tokens or settings.max_output_tokens,
                    settings.max_output_tokens,
                ),
            },
        }
        if temperature is not None:
            payload["options"]["temperature"] = temperature

        async def read_stream() -> AsyncIterator[OllamaStreamEvent]:
            done_received = False
            try:
                async with client.stream(
                    "POST",
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                    timeout=httpx.Timeout(
                        settings.ollama_timeout,
                        connect=settings.ollama_connect_timeout,
                    ),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        if response.status_code == 404:
                            raise OllamaModelNotFoundError()
                        logger.warning(
                            "Ollama streaming endpoint вернул HTTP %s",
                            response.status_code,
                        )
                        raise OllamaResponseError()

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                        except ValueError as exc:
                            raise OllamaResponseError() from exc
                        if not isinstance(item, dict):
                            raise OllamaResponseError()
                        if item.get("error"):
                            error_text = str(item["error"]).lower()
                            if "not found" in error_text or "pull" in error_text:
                                raise OllamaModelNotFoundError()
                            raise OllamaResponseError()

                        message = item.get("message")
                        content = message.get("content") if isinstance(message, dict) else None
                        if content:
                            if not isinstance(content, str):
                                raise OllamaResponseError()
                            yield OllamaStreamEvent(content=content)

                        if item.get("done") is True:
                            done_received = True
                            yield OllamaStreamEvent(
                                done=True,
                                finish_reason=(
                                    item.get("done_reason")
                                    if isinstance(item.get("done_reason"), str)
                                    else None
                                ),
                                prompt_eval_count=(
                                    item.get("prompt_eval_count")
                                    if isinstance(item.get("prompt_eval_count"), int)
                                    else None
                                ),
                                eval_count=(
                                    item.get("eval_count")
                                    if isinstance(item.get("eval_count"), int)
                                    else None
                                ),
                            )
                            return
            except OllamaError:
                raise
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError() from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise OllamaUnavailableError() from exc
            except httpx.HTTPError as exc:
                logger.warning(
                    "Ошибка HTTP streaming клиента Ollama: %s", type(exc).__name__
                )
                raise OllamaUnavailableError() from exc

            if not done_received:
                raise OllamaResponseError()

        if self._semaphore is None:
            async for event in read_stream():
                yield event
        else:
            async with self._semaphore:
                async for event in read_stream():
                    yield event

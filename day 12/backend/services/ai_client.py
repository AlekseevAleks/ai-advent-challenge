"""OpenAI-compatible API client.

All communication with the external LLM provider happens here. The client is
provider-agnostic: every request is built relative to the user-provided base
URL. The API key never leaves the backend.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

import httpx

from backend.config import get_config
from backend.models.message import ModelInfo
from backend.utils.errors import (
    AIAuthError,
    AIClientError,
    AIConnectionError,
    AIResponseFormatError,
    AIRateLimitError,
    AITimeoutError,
    NoModelsError,
    SettingsNotConfiguredError,
)
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

_STATUS_MESSAGES = {
    400: "API отклонил запрос (400). Проверьте параметры запроса и выбранную модель.",
    401: "API отклонил запрос авторизации (401). Проверьте API Key.",
    403: "Доступ запрещён (403). Проверьте права API Key.",
    404: "Endpoint не найден (404). Проверьте API Base URL.",
    408: "Сервер API не ответил вовремя (408). Попробуйте ещё раз.",
    422: "API не смог обработать запрос (422). Проверьте параметры и модель.",
    429: "Превышен лимит запросов (429). Подождите и повторите попытку.",
    500: "Внутренняя ошибка API (500). Попробуйте позже.",
    502: "API вернул ошибку шлюза (502). Попробуйте позже.",
    503: "API временно недоступен (503). Попробуйте позже.",
    504: "API вернул ошибку таймаута шлюза (504). Попробуйте позже.",
}


def _extract_error_message(response: httpx.Response) -> Optional[str]:
    """Best-effort extraction of a human readable message from an error body."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        text = (response.text or "").strip()
        return text[:500] or None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]
        if isinstance(error, str) and error.strip():
            return error.strip()[:500]
        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    return None


def _raise_for_status(response: httpx.Response) -> None:
    """Translate an HTTP error response into a user-facing exception."""
    if response.is_success:
        return

    status = response.status_code
    detail = _extract_error_message(response)
    base_message = _STATUS_MESSAGES.get(status)
    if base_message is None:
        if 500 <= status < 600:
            base_message = f"Сервер API вернул ошибку {status}. Попробуйте позже."
        else:
            base_message = f"API вернул ошибку {status}."

    message = base_message
    if detail:
        message = f"{base_message}\n\nОтвет сервера: {detail}"

    if status in (401, 403):
        raise AIAuthError(message, detail=detail)
    if status == 429:
        raise AIRateLimitError(message, detail=detail)
    raise AIClientError(message, detail=detail, status_code=502)


class AIClient:
    """Async client for OpenAI-compatible ``/models`` and ``/chat/completions``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: Optional[float] = None,
        connect_timeout: Optional[float] = None,
    ) -> None:
        config = get_config()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout if timeout is not None else config.request_timeout
        self.connect_timeout = (
            connect_timeout if connect_timeout is not None else config.connect_timeout
        )

    # ------------------------------------------------------------- internals
    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _timeout(self, *, streaming: bool = False) -> httpx.Timeout:
        if streaming:
            # No read timeout while streaming: the model may think for a while.
            return httpx.Timeout(
                self.timeout,
                connect=self.connect_timeout,
                read=None,
                write=self.timeout,
                pool=self.connect_timeout,
            )
        return httpx.Timeout(
            self.timeout,
            connect=self.connect_timeout,
            read=self.timeout,
            write=self.timeout,
            pool=self.connect_timeout,
        )

    def _validate(self) -> None:
        if not self.base_url:
            raise SettingsNotConfiguredError(
                "API Base URL не указан. Откройте «Настройки» и заполните поле."
            )
        if not self.base_url.startswith(("http://", "https://")):
            raise SettingsNotConfiguredError(
                "API Base URL должен начинаться с http:// или https://."
            )

    # ---------------------------------------------------------------- models
    async def list_models(self) -> List[ModelInfo]:
        """Fetch available models via ``GET /models``."""
        self._validate()
        url = self._url("models")
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise AITimeoutError(detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AIConnectionError(detail=str(exc)) from exc

        _raise_for_status(response)

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AIResponseFormatError(
                "API вернул не JSON при запросе списка моделей.",
                detail=str(exc),
            ) from exc

        models = self._parse_models(payload)
        if not models:
            raise NoModelsError(
                "API не вернул ни одной модели.\n"
                "Проверьте, что сервер поддерживает endpoint /models."
            )
        return models

    @staticmethod
    def _parse_models(payload: Any) -> List[ModelInfo]:
        if isinstance(payload, dict):
            raw_items = payload.get("data")
            if raw_items is None:
                raw_items = payload.get("models")
        elif isinstance(payload, list):
            raw_items = payload
        else:
            raise AIResponseFormatError(
                "Неожиданный формат ответа /models: ожидался объект с полем 'data'."
            )

        if not isinstance(raw_items, list):
            raise AIResponseFormatError(
                "Неожиданный формат ответа /models: поле 'data' не является списком."
            )

        models: List[ModelInfo] = []
        for item in raw_items:
            if isinstance(item, str):
                models.append(ModelInfo(id=item))
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
                if isinstance(model_id, str) and model_id.strip():
                    models.append(
                        ModelInfo(
                            id=model_id.strip(),
                            owned_by=item.get("owned_by"),
                            created=item.get("created")
                            if isinstance(item.get("created"), int)
                            else None,
                        )
                    )
        models.sort(key=lambda model: model.id.lower())
        return models

    # ------------------------------------------------------- chat completions
    @staticmethod
    def _build_payload(
        model: str,
        messages: Iterable[Dict[str, str]],
        *,
        stream: bool,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    async def complete(
        self,
        model: str,
        messages: Iterable[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Non-streaming chat completion. Returns the assistant text."""
        self._validate()
        url = self._url("chat/completions")
        payload = self._build_payload(
            model,
            messages,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.post(
                    url, headers=self._headers(), json=payload
                )
        except httpx.TimeoutException as exc:
            raise AITimeoutError(detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AIConnectionError(detail=str(exc)) from exc

        _raise_for_status(response)

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AIResponseFormatError(
                "API вернул не JSON в ответе на chat/completions.",
                detail=str(exc),
            ) from exc

        return self._extract_content(data)

    @staticmethod
    def _extract_content(data: Any) -> str:
        if not isinstance(data, dict):
            raise AIResponseFormatError(
                "Неожиданный формат ответа chat/completions."
            )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIResponseFormatError(
                "Ответ API не содержит поля 'choices'.",
                detail=json.dumps(data, ensure_ascii=False)[:500],
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise AIResponseFormatError("Некорректный элемент 'choices' в ответе API.")

        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Some providers return content as a list of parts.
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                ]
                return "".join(parts)

        text = first.get("text")
        if isinstance(text, str):
            return text

        raise AIResponseFormatError(
            "Не удалось извлечь текст ответа из ответа API.",
            detail=json.dumps(first, ensure_ascii=False)[:500],
        )

    async def stream_completion(
        self,
        model: str,
        messages: Iterable[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text deltas.

        Falls back transparently to a non-streaming request when the provider
        does not support SSE streaming.
        """
        self._validate()
        url = self._url("chat/completions")
        payload = self._build_payload(
            model,
            messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout(streaming=True)) as client:
                async with client.stream(
                    "POST", url, headers=self._headers(), json=payload
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        _raise_for_status(response)

                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" not in content_type.lower():
                        # Provider ignored `stream: true` and returned plain JSON.
                        body = await response.aread()
                        yield self._extract_content(json.loads(body.decode("utf-8")))
                        return

                    produced = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data or data == "[DONE]":
                            if data == "[DONE]":
                                break
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            logger.debug("Пропущен некорректный SSE-чанк")
                            continue
                        delta = self._extract_delta(chunk)
                        if delta:
                            produced = True
                            yield delta

                    if not produced:
                        logger.debug("Streaming не вернул контента")
        except httpx.TimeoutException as exc:
            raise AITimeoutError(detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AIConnectionError(detail=str(exc)) from exc

    @staticmethod
    def _extract_delta(chunk: Any) -> str:
        if not isinstance(chunk, dict):
            return ""
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
        # Some providers send the full message instead of a delta.
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        text = first.get("text")
        return text if isinstance(text, str) else ""

    # ------------------------------------------------------------------ test
    async def test_connection(self) -> Dict[str, Any]:
        """Check that the configured API is reachable and usable."""
        started = time.perf_counter()
        models = await self.list_models()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"models_count": len(models), "latency_ms": latency_ms}


def build_client_from_settings() -> AIClient:
    """Create an :class:`AIClient` from the locally stored settings."""
    from backend.services.settings_service import get_settings_service

    settings = get_settings_service()
    return AIClient(settings.get_api_base_url(), settings.get_api_key())
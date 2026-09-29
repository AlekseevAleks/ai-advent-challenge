"""Асинхронная обёртка над OpenAI-совместимым HTTP API.

Модуль инкапсулирует обращения к ``/models`` и ``/chat/completions``,
включая потоковый (SSE) режим, и преобразует ошибки в понятные
русскоязычные сообщения.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

import httpx

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


class ApiError(Exception):
    """Ошибка обращения к внешнему API с готовым текстом для пользователя."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_url(api_url: str) -> str:
    """Проверяет корректность URL API и возвращает его без завершающего слэша."""
    if not api_url or not api_url.strip():
        raise ApiError("Не задан адрес API. Укажите его в настройках.")
    url = api_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ApiError("Некорректный адрес API. Пример: https://api.openai.com/v1")
    return url


def _headers(api_key: str) -> Dict[str, str]:
    """Формирует заголовки авторизации для внешнего API."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def build_request_body(
    model: str,
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Формирует тело запроса к ``/chat/completions`` (используется и для лога)."""
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return body


def masked_headers(api_key: str) -> Dict[str, str]:
    """Возвращает заголовки запроса с маскированным ключом (для лога)."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer sk-***MASKED***"
    return headers


def _friendly_error(status_code: int, body: str) -> str:
    """Преобразует HTTP-ошибку внешнего API в понятное сообщение на русском."""
    detail = ""
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = error.get("message", "")
            elif isinstance(error, str):
                detail = error
            detail = detail or payload.get("message", "")
    except (json.JSONDecodeError, TypeError):
        detail = (body or "").strip()[:300]

    if status_code == 401:
        base = "Неверный API-ключ или он не передан."
    elif status_code == 403:
        base = "Доступ запрещён: ключ не имеет прав на этот ресурс."
    elif status_code == 404:
        base = "Эндпоинт не найден. Проверьте адрес API (обычно он заканчивается на /v1)."
    elif status_code == 429:
        base = "Превышен лимит запросов или закончилась квота."
    elif 500 <= status_code < 600:
        base = "Сервер API вернул ошибку. Попробуйте позже."
    else:
        base = f"Ошибка API (код {status_code})."
    return f"{base} {detail}".strip()


async def list_models(api_url: str, api_key: str) -> List[Dict[str, Any]]:
    """Возвращает список моделей из ``GET {api_url}/models``."""
    url = validate_url(api_url)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{url}/models", headers=_headers(api_key))
    except httpx.ConnectError:
        raise ApiError("Не удалось подключиться к API. Проверьте адрес и доступность сети.")
    except httpx.TimeoutException:
        raise ApiError("Превышено время ожидания ответа от API.")
    except httpx.HTTPError as exc:
        raise ApiError(f"Ошибка сети при обращении к API: {exc}")

    if response.status_code >= 400:
        raise ApiError(_friendly_error(response.status_code, response.text), response.status_code)

    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise ApiError("API вернул ответ в неизвестном формате.")

    raw = payload.get("data", payload) if isinstance(payload, dict) else payload
    models: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                models.append({"id": item["id"], "owned_by": item.get("owned_by", "")})
            elif isinstance(item, str):
                models.append({"id": item, "owned_by": ""})
    models.sort(key=lambda m: m["id"])
    return models


async def test_connection(api_url: str, api_key: str) -> Dict[str, Any]:
    """Проверяет подключение к API через запрос списка моделей."""
    models = await list_models(api_url, api_key)
    return {"ok": True, "models_count": len(models)}


def _extract_usage(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Извлекает статистику токенов и стоимость из чанка ответа API.

    Возвращает словарь с ключами ``prompt_tokens``, ``completion_tokens``,
    ``total_tokens`` и ``cost_rub`` (если провайдер его прислал) либо
    ``None``, если данных о токенах нет.
    """
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    cost_rub = usage.get("cost_rub")
    if prompt is None and completion is None and total is None and cost_rub is None:
        return None
    prompt = int(prompt or 0)
    completion = int(completion or 0)
    total = int(total if total is not None else prompt + completion)
    result: Dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    if cost_rub is not None:
        try:
            result["cost_rub"] = float(cost_rub)
        except (TypeError, ValueError):
            pass
    return result


def _aggregate_tool_calls(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Собирает tool_calls из SSE-чанков с дельтами OpenAI.

    В стриме ``delta.tool_calls`` приходят по частям (name один раз,
    arguments — фрагментами). Результат: обычный список tool_calls,
    пригодный для повторной передачи модели.
    """
    calls: List[Dict[str, Any]] = []
    for chunk in chunks:
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            for part in delta.get("tool_calls") or []:
                index = int(part.get("index", 0))
                while len(calls) <= index:
                    calls.append(
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                    )
                target = calls[index]
                if part.get("id"):
                    target["id"] = part["id"]
                fn = part.get("function") or {}
                # name обычно приходит целиком в первом чанке,
                # arguments — кусками, их конкатенируем.
                if fn.get("name"):
                    target["function"]["name"] += fn["name"]
                if fn.get("arguments") is not None:
                    target["function"]["arguments"] += fn["arguments"]
    return [call for call in calls if call["function"]["name"]]


def _last_finish_reason(chunks: List[Dict[str, Any]]) -> Optional[str]:
    """Возвращает последний непустой ``finish_reason`` из стрим-чанков."""
    reason: Optional[str] = None
    for chunk in chunks:
        for choice in chunk.get("choices") or []:
            value = choice.get("finish_reason")
            if value:
                reason = value
    return reason


async def stream_chat(
    api_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Стримит ответ модели, отдавая фрагменты текста по мере генерации.

    Разбирает SSE-поток OpenAI-совместимого API и игнорирует служебные
    чанки (например, ``[DONE]``). Каждый элемент — словарь одного из видов:

    * ``{"type": "delta", "content": "..."}`` — фрагмент текста ответа;
    * ``{"type": "usage", "usage": {...}}`` — статистика токенов;
    * ``{"type": "meta", "status_code": ..., "body": ..., "finish_reason": ..., "tool_calls": [...]}``
      — итог стрима: агент использует ``tool_calls`` для цикла function calling.

    Статистика запрашивается через ``stream_options.include_usage``; если
    провайдер её не поддерживает, поле просто не придёт.
    """
    url = validate_url(api_url)
    body = build_request_body(model, messages, tools)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{url}/chat/completions",
                headers=_headers(api_key),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    raw = await response.aread()
                    text = raw.decode("utf-8", errors="replace")
                    raise ApiError(
                        _friendly_error(response.status_code, text), response.status_code
                    )

                raw_chunks: List[Dict[str, Any]] = []
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    raw_chunks.append(chunk)
                    usage = _extract_usage(chunk)
                    if usage:
                        yield {"type": "usage", "usage": usage}

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield {"type": "delta", "content": content}

                yield {
                    "type": "meta",
                    "status_code": response.status_code,
                    "body": {"chunks": raw_chunks},
                    "finish_reason": _last_finish_reason(raw_chunks),
                    "tool_calls": _aggregate_tool_calls(raw_chunks),
                }
    except ApiError:
        raise
    except httpx.ConnectError:
        raise ApiError("Не удалось подключиться к API. Проверьте адрес и доступность сети.")
    except httpx.TimeoutException:
        raise ApiError("Превышено время ожидания ответа от API.")
    except httpx.HTTPError as exc:
        raise ApiError(f"Ошибка сети при обращении к API: {exc}")

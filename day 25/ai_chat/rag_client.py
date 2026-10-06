"""Асинхронный клиент RAG-сервиса (семантический поиск по индексу).

RAG-сервис — учебный FastAPI-сервис (спецификация доступна на
``/docs``). Для поиска используется ``POST /api/search``; коллекция
и стратегия chunking выбираются автоматически из ``GET /api/collections``
(первая коллекция с индексами, стратегия ``fixed_size`` при наличии).

Ответ поиска приводится к простому списку чанков::

    [
      {"rank": 1, "score": 0.85, "text": "..."},
      ...
    ]
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

# Поиск делает эмбеддинг запроса через локальный Ollama — он может быть
# медленным, поэтому таймаут на чтение больше обычного.
RAG_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=10.0)

# Приоритет стратегий chunking при авто-выборе.
_STRATEGY_PRIORITY = ("fixed_size", "structural")


class RagError(Exception):
    """Ошибка обращения к RAG-сервису с готовым текстом для пользователя."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_rag_url(rag_url: str) -> str:
    """Проверяет корректность адреса RAG-сервиса и возвращает его без слэша."""
    if not rag_url or not rag_url.strip():
        raise RagError("Не задан адрес RAG-сервера. Укажите его в настройках.")
    url = rag_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RagError("Некорректный адрес RAG-сервера. Пример: http://localhost:8000")
    return url


def _friendly_error(status_code: int, body: str) -> str:
    """Преобразует HTTP-ошибку RAG-сервиса в понятное сообщение."""
    detail = ""
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or ""
    except (json.JSONDecodeError, TypeError):
        detail = (body or "").strip()[:300]
    if status_code == 404:
        base = "Эндпоинт RAG не найден. Проверьте адрес RAG-сервера."
    elif 500 <= status_code < 600:
        base = "RAG-сервер вернул ошибку."
    else:
        base = f"Ошибка RAG-сервера (код {status_code})."
    return f"{base} {detail}".strip()


async def list_collections(rag_url: str) -> List[Dict[str, Any]]:
    """Возвращает список коллекций RAG-сервиса (``GET /api/collections``)."""
    url = validate_rag_url(rag_url)
    try:
        async with httpx.AsyncClient(timeout=RAG_TIMEOUT) as client:
            response = await client.get(f"{url}/api/collections")
    except httpx.ConnectError:
        raise RagError("Не удалось подключиться к RAG-серверу. Проверьте адрес.")
    except httpx.TimeoutException:
        raise RagError("RAG-сервер не ответил вовремя.")
    except httpx.HTTPError as exc:
        raise RagError(f"Ошибка сети при обращении к RAG-серверу: {exc}")

    if response.status_code >= 400:
        raise RagError(_friendly_error(response.status_code, response.text), response.status_code)
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise RagError("RAG-сервер вернул ответ в неизвестном формате.")
    if not isinstance(payload, list):
        raise RagError("RAG-сервер вернул неожиданный список коллекций.")
    return [item for item in payload if isinstance(item, dict)]


def pick_strategy(strategies: List[str]) -> str:
    """Выбирает стратегию chunking из доступных (fixed_size приоритетнее)."""
    if not strategies:
        return ""
    return next(
        (candidate for candidate in _STRATEGY_PRIORITY if candidate in strategies),
        strategies[0],
    )


def pick_index(collections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Выбирает коллекцию и стратегию chunking для поиска.

    Берётся первая коллекция с доступными стратегиями; стратегия — первая
    из приоритетного списка ``fixed_size`` → ``structural`` → любая.
    """
    for collection in collections:
        strategies = collection.get("strategies") or []
        strategy = pick_strategy(strategies)
        if not strategy:
            continue
        return {
            "collection_id": collection.get("id") or "",
            "collection_name": collection.get("name") or "",
            "strategy": strategy,
        }
    return None


async def search(
    rag_url: str,
    query: str,
    collection_id: Optional[str] = None,
    strategy: Optional[str] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """Выполняет семантический поиск и возвращает нормализованный ответ.

    Если ``collection_id``/``strategy`` не заданы — они выбираются
    автоматически. Возвращает словарь с ключами: ``query``, ``collection_id``,
    ``strategy``, ``model``, ``n_indexed``, ``took_ms``, ``results``
    (список чанков) и ``raw`` (сырой ответ сервиса).
    """
    url = validate_rag_url(rag_url)
    query = (query or "").strip()
    if not query:
        raise RagError("Пустой поисковый запрос.")

    if not collection_id or not strategy:
        collections = await list_collections(url)
        picked = pick_index(collections)
        if picked is None:
            raise RagError("В RAG-сервисе нет коллекций с индексами.")
        collection_id = collection_id or picked["collection_id"]
        strategy = strategy or picked["strategy"]

    payload: Dict[str, Any] = {
        "collection_id": collection_id,
        "strategy": strategy,
        "query": query,
        "top_k": max(1, min(int(top_k or 5), 50)),
    }
    try:
        async with httpx.AsyncClient(timeout=RAG_TIMEOUT) as client:
            response = await client.post(
                f"{url}/api/search",
                headers={"Content-Type": "application/json"},
                json=payload,
            )
    except httpx.ConnectError:
        raise RagError("Не удалось подключиться к RAG-серверу. Проверьте адрес.")
    except httpx.TimeoutException:
        raise RagError("RAG-сервер не ответил вовремя.")
    except httpx.HTTPError as exc:
        raise RagError(f"Ошибка сети при обращении к RAG-серверу: {exc}")

    if response.status_code >= 400:
        raise RagError(_friendly_error(response.status_code, response.text), response.status_code)
    try:
        raw = response.json()
    except json.JSONDecodeError:
        raise RagError("RAG-сервер вернул ответ в неизвестном формате.")
    if not isinstance(raw, dict):
        raise RagError("RAG-сервер вернул неожиданный формат ответа поиска.")

    return {
        "query": raw.get("query", query),
        "collection_id": raw.get("collection_id", collection_id),
        "strategy": raw.get("strategy", strategy),
        "model": raw.get("model", ""),
        "n_indexed": raw.get("n_indexed", 0),
        "took_ms": raw.get("took_ms", 0),
        "results": [_normalize_result(item) for item in (raw.get("results") or [])],
        "raw": raw,
    }


def _normalize_result(item: Any) -> Dict[str, Any]:
    """Приводит элемент ``results`` к единому виду с текстом чанка.

    Помимо ``rank``/``score``/``text`` сохраняются метаданные источника
    (``source_id``, ``chunk_id``, ``url`` — path/url), чтобы модель могла
    сослаться на чанк в блоке «Источники» ответа.
    """
    if not isinstance(item, dict):
        return {"rank": 0, "score": 0.0, "text": ""}
    chunk = item.get("chunk") or {}
    if not isinstance(chunk, dict):
        chunk = {}
    text = chunk.get("text") or chunk.get("content") or chunk.get("body") or ""
    if not isinstance(text, str):
        try:
            text = json.dumps(chunk, ensure_ascii=False)
        except (TypeError, ValueError):
            text = ""
    return {
        "rank": int(item.get("rank", 0) or 0),
        "score": float(item.get("score", 0.0) or 0.0),
        "text": text,
        "source_id": str(chunk.get("source_id") or item.get("source_id") or ""),
        "chunk_id": str(chunk.get("chunk_id") or item.get("chunk_id") or ""),
        "url": str(
            chunk.get("url")
            or chunk.get("path")
            or item.get("url")
            or item.get("path")
            or ""
        ),
    }



def build_context_block(results: List[Dict[str, Any]], limit: int = 2000) -> str:
    """Собирает текстовый блок контекста из найденных чанков для промта.

    В заголовке каждого чанка указываются источник и метаданные
    (``source_id``/``chunk_id``/``url``), чтобы модель могла сослаться
    на них в блоке «Источники». Размер ограничивается ``limit`` символами.
    """
    parts: List[str] = []
    used = 0
    for result in results:
        text = (result.get("text") or "").strip()
        if not text:
            continue
        source_part = _source_tag(result)
        block = f"[Чанк {result.get('rank', '?')} (score={result.get('score', 0.0):.3f}){source_part}]\n{text}"
        if used + len(block) > limit and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _source_tag(result: Dict[str, Any]) -> str:
    """Компактная строка метаданных источника в заголовке чанка.

    Формат: `` | source: {source_id} | url: {url}`` (пустые поля опускаются).
    """
    tags: List[str] = []
    source_id = (result.get("source_id") or "").strip()
    url = (result.get("url") or "").strip()
    if source_id:
        tags.append(f"source: {source_id}")
    if url:
        tags.append(f"url: {url}")
    return " | " + " | ".join(tags) if tags else ""
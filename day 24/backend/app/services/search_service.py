"""Сервис семантического поиска по индексу.

Метрика: cosine similarity. Векторы при сохранении нормализуются, поэтому
поиск выполняется как Inner Product в FAISS (IndexFlatIP).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, Optional, Tuple

import faiss
import numpy as np

from ..repositories import collections_repo
from ..schemas.api import SearchRequest, SearchResponse, SearchResultItem
from ..utils.errors import ConflictError, NotFoundError
from . import runtime
from .faiss_store import get_store
from .ollama_service import ollama_provider

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str], Tuple[str, faiss.Index, list, dict]] = {}


def _load_index_cached(collection_id: str, strategy: str):
    """Загрузить индекс с кэшем по (collection_id, strategy, updated_at)."""
    record = collections_repo.get_index(collection_id, strategy)
    if record is None:
        raise NotFoundError("Индекс не найден", code="index_not_found")
    config = record["config"] if isinstance(record["config"], dict) else __import__("json").loads(record["config"])
    updated = record.get("updated_at") or config.get("updated_at", "")
    key = (collection_id, strategy)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] == updated:
            return cached[1], cached[2], cached[3]
    store = get_store()
    index, metadata, _ = store.load(collection_id, strategy)
    with _cache_lock:
        _cache[key] = (updated, index, metadata, config)
        if len(_cache) > 16:
            _cache.clear()
    return index, metadata, config


def search(req: SearchRequest) -> SearchResponse:
    query = req.query.strip()
    if not query:
        raise ConflictError("Пустой запрос поиска", code="empty_query")

    settings = runtime.effective_settings()
    model = settings.embedding_model
    index, metadata, config = _load_index_cached(req.collection_id, req.strategy)

    if index.ntotal == 0:
        raise ConflictError("Индекс пуст — сначала выполните индексацию", code="empty_index")

    # совместимость модели индекса и текущей модели
    if config.get("embedding_model") != model:
        raise ConflictError(
            f"Индекс создан моделью «{config.get('embedding_model')}», а сейчас настроена «{model}». "
            "Выберите ту же модель в настройках или перестройте индекс.",
            code="model_mismatch",
        )
    dim = config.get("dimension")
    if dim != index.d:
        raise ConflictError("Размерность индекса не совпадает с конфигурацией", code="dimension_mismatch")

    t0 = time.time()
    client = ollama_provider.get_provider()
    vec = client.embed_one(query)
    if dim is not None and len(vec) != dim:
        raise ConflictError(
            f"Размерность эмбеддинга запроса ({len(vec)}) не совпадает с индексом ({dim})",
            code="dimension_mismatch",
        )
    q = np.asarray([vec], dtype="float32")
    norm = np.linalg.norm(q)
    if norm > 0:
        q = q / norm
    scores, ids = index.search(q, min(req.top_k, index.ntotal))

    results = []
    for rank, (score, idx) in enumerate(zip(scores[0], ids[0]), start=1):
        if idx < 0 or idx >= len(metadata):
            continue
        chunk = dict(metadata[int(idx)])
        chunk["similarity"] = round(float(score), 6)
        chunk["rank"] = rank
        results.append(SearchResultItem(rank=rank, score=round(float(score), 6), chunk=chunk))

    return SearchResponse(
        query=query,
        collection_id=req.collection_id,
        strategy=req.strategy,
        model=model,
        dimension=int(dim or index.d),
        n_indexed=index.ntotal,
        took_ms=round((time.time() - t0) * 1000, 1),
        results=results,
    )
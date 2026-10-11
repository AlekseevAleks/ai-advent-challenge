"""Сравнение стратегий chunking по фактическим результатам индексации."""

from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List

from ..repositories import collections_repo
from ..schemas.api import ComparisonMetrics, ComparisonOut
from ..utils.common import median, quantile
from . import runtime
from .faiss_store import get_store

TRADEOFFS = [
    "Fixed-size chunking даёт предсказуемый размер чанков, но может разрезать мысль посередине",
    "Structural chunking старается сохранить смысловые границы (заголовки, функции, страницы), "
    "но размер чанков менее равномерен",
    "«Лучшая» стратегия зависит от структуры корпуса и качества извлечения текста — "
    "выводы нужно делать по содержанию результатов поиска, а не только по метрикам",
    "Меньшее количество чанков не означает лучший retrieval: важна семантическая целостность"
]


def _nice_buckets(sizes: List[int], n: int = 12) -> List[Dict[str, Any]]:
    if not sizes:
        return []
    lo, hi = min(sizes), max(sizes)
    if hi <= lo:
        return [{"label": str(lo), "count": len(sizes)}]
    step = max(1, int((hi - lo) / n) or 1)
    lo = max(0, int(lo))
    buckets: Dict[int, int] = {}
    for s in sizes:
        b = int((s - lo) // step) * step + lo
        buckets[b] = buckets.get(b, 0) + 1
    return [{"label": f"{b}–{b + step}", "count": c} for b, c in sorted(buckets.items())]


def _metrics_for(collection_ids: List[str], strategy: str) -> ComparisonMetrics:
    store = get_store()
    sizes: List[int] = []
    n_chunks = 0
    empty = 0
    index_bytes = 0
    time_chunking = time_emb = time_total = None
    errors = 0
    docs_seen = set()

    for cid in collection_ids:
        cfg = collections_repo.get_index(cid, strategy)
        if cfg is None or not store.has_index(cid, strategy):
            continue
        config = cfg["config"] if isinstance(cfg["config"], dict) else json.loads(cfg["config"])
        meta_file = store.metadata_file(cid, strategy)
        if meta_file.exists():
            metas = json.loads(meta_file.read_text(encoding="utf-8"))
            sizes.extend(m["char_count"] for m in metas)
            n_chunks += len(metas)
            empty += sum(1 for m in metas if m.get("char_count", 0) == 0)
            docs_seen.update(m["document_id"] for m in metas)
        index_bytes += store.index_size_bytes(cid, strategy)
        time_chunking = config.get("time_chunking_ms") if time_chunking is None else time_chunking
        time_emb = config.get("time_embeddings_ms") if time_emb is None else time_emb
        time_total = config.get("time_total_ms") if time_total is None else time_total
        errors += int(config.get("errors_count", 0))

    if not sizes:
        return ComparisonMetrics()

    return ComparisonMetrics(
        documents=len(docs_seen),
        chunks=n_chunks,
        mean_chars=round(statistics.fmean(sizes), 1),
        median_chars=median(sizes),
        min_chars=min(sizes),
        max_chars=max(sizes),
        std_chars=round(statistics.pstdev(sizes), 1),
        empty_chunks=empty,
        index_size_bytes=index_bytes,
        time_chunking_ms=time_chunking,
        time_embeddings_ms=time_emb,
        time_total_ms=time_total,
        errors=errors,
    )


def _per_document(collection_ids: List[str], strategy: str) -> List[Dict[str, Any]]:
    store = get_store()
    counts: Dict[str, Dict[str, Any]] = {}
    for cid in collection_ids:
        meta_file = store.metadata_file(cid, strategy)
        if not meta_file.exists():
            continue
        metas = json.loads(meta_file.read_text(encoding="utf-8"))
        for m in metas:
            key = m.get("document_id", "?")
            entry = counts.setdefault(key, {"document_id": key, "title": m.get("title", key), "chunks": 0})
            entry["chunks"] += 1
    out = sorted(counts.values(), key=lambda x: -x["chunks"])
    return out[:50]


def get_comparison(collection_id: str | None = None) -> ComparisonOut:
    if collection_id:
        row = collections_repo.get_collection(collection_id)
        if row is None:
            from ..utils.errors import NotFoundError
            raise NotFoundError("Коллекция не найдена", code="collection_not_found")
        collection_ids = [collection_id]
        name = row["name"]
    else:
        collection_ids = [c["id"] for c in collections_repo.list_collections()]
        name = "Все коллекции"
        collection_id = "__all__"

    strategies = ["fixed_size", "structural"]
    store = get_store()
    present = [
        s for s in strategies
        if any(collections_repo.get_index(cid, s) is not None and store.has_index(cid, s) for cid in collection_ids)
    ]

    metrics = {s: _metrics_for(collection_ids, s) for s in present}
    return ComparisonOut(
        collection_id=collection_id or "__all__",
        collection_name=name,
        strategies=present,
        metrics=metrics,
        sizes={s: _sizes_for(collection_ids, s) for s in present},
        histogram={s: _nice_buckets(_sizes_for(collection_ids, s)) for s in present},
        per_document={s: _per_document(collection_ids, s) for s in present},
        timings={s: {
            "chunking_ms": metrics[s].time_chunking_ms,
            "embeddings_ms": metrics[s].time_embeddings_ms,
            "total_ms": metrics[s].time_total_ms,
        } for s in present},
        tradeoffs=list(TRADEOFFS),
    )


def _sizes_for(collection_ids: List[str], strategy: str) -> List[int]:
    store = get_store()
    sizes: List[int] = []
    for cid in collection_ids:
        f = store.metadata_file(cid, strategy)
        if f.exists():
            metas = json.loads(f.read_text(encoding="utf-8"))
            sizes.extend(m["char_count"] for m in metas)
    sizes.sort()
    return sizes
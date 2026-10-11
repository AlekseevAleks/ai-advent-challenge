"""Pipeline engine: rewrite → retrieval → dedup/MMR → filter → rerank → final.

Выход содержит данные ВСЕХ этапов, чтобы фронтенд мог показать каждый шаг
и почему конкретный чанк попал или не попал в финальный контекст.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ...repositories import collections_repo
from ...schemas.rag import QUERY_MAX_LENGTH, RetrievalConfig
from ...utils.errors import ConflictError, NotFoundError, ValidationError2
from ...utils.logging import get_logger
from .. import runtime
from ..ollama_service import ollama_provider
from ..search_service import _load_index_cached
from .query_rewriter import RewriteResult, rewriter_holder
from .rerankers import BaseReranker, RerankerUnavailable, build_reranker

logger = get_logger(__name__)


class RetrievalPipeline:
    """Единый конвейер поиска с промежуточными этапами."""

    def __init__(self, rewriter=None, embedding_provider=None):
        self._rewriter = rewriter
        self._provider = embedding_provider

    # ------------------------------------------------------------------
    def _resolve_index(self, collection_id: Optional[str], index_id: Optional[str],
                       strategy: Optional[str]) -> Tuple[str, str, dict]:
        if index_id:
            rec = collections_repo.find_index_by_id(index_id)
            if rec is None:
                raise NotFoundError("Индекс не найден", code="index_not_found")
            return rec["collection_id"], rec["strategy"], rec.get("config", {})
        if not collection_id:
            raise ValidationError2("Укажите коллекцию или index_id", code="validation_error")
        strat = strategy or "structural"
        rec = collections_repo.get_index(collection_id, strat)
        if rec is None:
            raise NotFoundError(
                f"Индекс «{strat}» для коллекции «{collection_id}» не найден",
                code="index_not_found",
            )
        cfg = rec["config"] if isinstance(rec["config"], dict) else __import__("json").loads(rec["config"])
        return collection_id, strat, cfg

    def _embed(self, text: str) -> Tuple[List[float], float]:
        provider = self._provider or ollama_provider.get_provider()
        t0 = time.perf_counter()
        vec = provider.embed_one(text[:QUERY_MAX_LENGTH])
        return vec, (time.perf_counter() - t0) * 1000

    # ------------------------------------------------------------------
    def run(
        self,
        query: str,
        config: RetrievalConfig,
        collection_id: Optional[str] = None,
        index_id: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("experiment_started")
        t_start = time.perf_counter()
        query = (query or "").strip()
        if not query:
            raise ValidationError2("Пустой запрос поиска", code="empty_query")
        if len(query) > QUERY_MAX_LENGTH:
            raise ValidationError2(
                f"Запрос слишком длинный: {len(query) if len(query) < 100000 else '>100k'} > {QUERY_MAX_LENGTH}",
                code="query_too_long",
            )
        if config.initial_top_k < config.final_top_k:
            raise ValidationError2(
                "initial_top_k должен быть не меньше final_top_k", code="topk_invalid"
            )

        # ----- 0. Query Rewrite -----
        rewritten: Optional[str] = None
        rewrite_ms: Optional[float] = None
        rewrite_model: Optional[str] = None
        if config.query_rewrite:
            rw = self._rewriter or rewriter_holder.get()
            settings0 = runtime.effective_settings()
            rw_model = config.query_rewrite_model or settings0.query_rewrite_model
            res: RewriteResult = rw.rewrite(query, model=rw_model)
            rewritten, rewrite_ms, rewrite_model = res.rewritten, res.latency_ms, res.model
            logger.info("query_rewritten len=%d", len(rewritten))
        search_query = rewritten or query

        # ----- 1. Retrieval -----
        t0 = time.perf_counter()
        vec, embed_ms = self._embed(search_query)
        cid, strat, index_cfg = self._resolve_index(collection_id, index_id, strategy)
        index, metadata, _ = _load_index_cached(cid, strat)
        settings = runtime.effective_settings()

        if index.ntotal == 0:
            raise ConflictError("Индекс пуст — сначала выполните индексацию", code="empty_index")
        if index_cfg.get("embedding_model") != settings.embedding_model:
            raise ConflictError(
                f"Индекс создан моделью «{index_cfg.get('embedding_model')}», а сейчас настроена "
                f"«{settings.embedding_model}» — перестройте индекс или смените модель в настройках.",
                code="model_mismatch",
            )
        dim = index_cfg.get("dimension")
        if dim and dim != index.d:
            raise ConflictError("Размерность индекса не совпадает с конфигурацией", code="dimension_mismatch")
        if dim and len(vec) != dim:
            raise ConflictError(
                f"Размерность эмбеддинга запроса ({len(vec)}) не совпадает с индексом ({dim})",
                code="dimension_mismatch",
            )
        q = np.asarray([vec], dtype="float32")
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        k = min(config.initial_top_k, index.ntotal)
        scores, ids = index.search(q, k)
        retrieval_ms = (time.perf_counter() - t0) * 1000
        ids_flat = [int(i) for i in ids[0]]

        items: List[Dict[str, Any]] = []
        for rank, (sc, i) in enumerate(zip(scores[0], ids[0]), start=1):
            if i < 0 or i >= len(metadata):
                continue
            chunk = dict(metadata[int(i)])
            chunk["retrieval_rank"] = rank
            chunk["retrieval_score"] = round(float(sc), 6)
            chunk["filter_score"] = round(float(sc), 6)
            chunk["passed_filter"] = True
            chunk["deduplicated"] = False
            chunk["mmr_removed"] = False
            chunk["reranker_score"] = None
            chunk["reranker_rank"] = None
            chunk["mmr_rank"] = None
            chunk["final_rank"] = None
            chunk["status"] = "kept"
            items.append(chunk)

        # эмбеддинги кандидатов (для dedup/MMR) — лениво при необходимости
        def _candidate_vectors() -> np.ndarray:
            if index.ntotal == 0 or not ids_flat:
                return np.zeros((0, index.d), dtype="float32")
            return index.reconstruct_n(0, index.ntotal)[np.asarray(ids_flat[: len(items)])]

        # ----- 2. Deduplication -----
        dedup_ms = 0.0
        dedup_removed = 0
        if config.deduplicate:
            t0 = time.perf_counter()
            cand_v = _candidate_vectors()
            keep_idx: List[int] = []
            for i in range(len(items)):
                if keep_idx:
                    sims = cand_v[i] @ cand_v[np.asarray(keep_idx)].T
                    if sims.max() > config.dedup_threshold:
                        items[i]["deduplicated"] = True
                        items[i]["status"] = "deduplicated"
                        dedup_removed += 1
                        continue
                keep_idx.append(i)
            dedup_ms = (time.perf_counter() - t0) * 1000

        # ----- 3. MMR (изменяет порядок оставшихся кандидатов) -----
        mmr_ms = 0.0
        mmr_note = None
        mmr_applied = False
        if config.mmr:
            t0 = time.perf_counter()
            active = [i for i, it in enumerate(items) if it["status"] == "kept"]
            if len(active) > 1:
                vecs = _candidate_vectors()
                lam = config.mmr_lambda
                rel = np.array([items[i]["retrieval_score"] for i in active], dtype="float64")
                sim = vecs[np.asarray([items[i]["retrieval_rank"] - 1 for i in active])]
                order: List[int] = []
                remaining = list(range(len(active)))
                while remaining:
                    if not order:
                        j = int(np.argmax(rel[remaining]))
                    else:
                        max_sim = sim[np.asarray(remaining)] @ sim[np.asarray(order)].T
                        max_sim = max_sim.max(axis=1) if max_sim.size else np.zeros(len(remaining))
                        mr_ = lam * rel[remaining] - (1 - lam) * max_sim
                        j = int(np.argmax(mr_))
                    order.append(remaining.pop(j))
                # зафиксировать MMR-порядок отдельным полем (исходный ранг не трогаем)
                for pos, j in enumerate(order, start=1):
                    items[active[j]]["mmr_rank"] = pos
                mmr_applied = True
                mmr_note = (
                    "MMR переупорядочивает кандидатов (lambda → релевантность, "
                    "1-lambda → разнообразие). Порядок применяется, когда реранкер выключен."
                )
            mmr_ms = (time.perf_counter() - t0) * 1000

        # ----- 4. Similarity filter -----
        filter_ms = 0.0
        passed = 0
        filtered_out = 0
        if config.enable_filter:
            t0 = time.perf_counter()
            th = config.similarity_threshold
            for it in items:
                if it["status"] != "kept":
                    continue
                ok = it["retrieval_score"] >= th
                it["passed_filter"] = ok
                if ok:
                    passed += 1
                else:
                    it["status"] = "filtered"
                    filtered_out += 1
            filter_ms = (time.perf_counter() - t0) * 1000
        else:
            passed = sum(1 for it in items if it["status"] == "kept")

        # ----- 5. Reranking -----
        rerank_ms = 0.0
        rerank_kind: Optional[str] = None
        rerank_model: Optional[str] = None
        candidates = [it for it in items if it["status"] == "kept"]
        if config.enable_reranker and candidates:
            t0 = time.perf_counter()
            base = [it["retrieval_score"] for it in candidates]
            q_rerank = rewritten if (config.reranker_query == "rewritten" and rewritten) else query
            try:
                reranker: BaseReranker = build_reranker(
                    config.reranker,
                    model=config.reranker_model or settings.reranker_model,
                    base_scores=base,
                )
                scores_r = reranker.rerank(q_rerank, [it.get("text", "") for it in candidates])
                rerank_kind = reranker.kind
                rerank_model = getattr(reranker, "model", None) or config.reranker_model or settings.reranker_model
            except RerankerUnavailable as e:
                raise ConflictError(
                    f"{e} Вы можете: 1) установить модель/библиотеку ({e.install_hint or 'см. README'}), "
                    "2) выбрать heuristic-реранкинг, 3) отключить реранкинг.",
                    code="reranker_unavailable",
                )
            order = sorted(range(len(candidates)), key=lambda j: (-scores_r[j], j))
            for new_rank, j in enumerate(order, start=1):
                candidates[j]["reranker_score"] = round(float(scores_r[j]), 6)
                candidates[j]["reranker_rank"] = new_rank
            rerank_ms = (time.perf_counter() - t0) * 1000
            logger.info("reranking_completed n=%d", len(candidates))

        # ----- 6. Final selection -----
        final_pool = list(candidates)
        if rerank_kind:
            final_pool.sort(key=lambda it: it["reranker_rank"] or 0)
        elif config.mmr and mmr_applied:
            final_pool.sort(key=lambda it: it.get("mmr_rank") or it["retrieval_rank"])
        else:
            final_pool.sort(key=lambda it: it["retrieval_rank"])
        final = final_pool[: config.final_top_k]
        final_ids = {it["chunk_id"] for it in final}
        for it in items:
            if it["status"] == "kept" and it["chunk_id"] not in final_ids:
                it["status"] = "outside_final_top_k"
        for rank, it in enumerate(final, start=1):
            it["final_rank"] = rank
            it["status"] = "kept"

        total_ms = (time.perf_counter() - t_start) * 1000
        logger.info("experiment_completed")

        return {
            "original_query": query,
            "rewritten_query": rewritten,
            "rewrite": {
                "enabled": config.query_rewrite,
                "model": rewrite_model,
                "latency_ms": rewrite_ms,
            },
            "retrieval": {
                "initial_top_k": config.initial_top_k,
                "candidates": len(items),
                "strategy": strat,
                "collection_id": cid,
                "index_id": index_cfg.get("index_id"),
                "latency_ms": round(retrieval_ms, 2),
            },
            "deduplication": {
                "enabled": config.deduplicate,
                "threshold": config.dedup_threshold,
                "before": len(items) + dedup_removed,
                "after": len(items) - dedup_removed,
                "removed": dedup_removed,
                "latency_ms": round(dedup_ms, 2),
            },
            "mmr": {
                "enabled": config.mmr,
                "lambda": config.mmr_lambda,
                "applied": mmr_applied,
                "latency_ms": round(mmr_ms, 2),
                "note": mmr_note,
            },
            "filtering": {
                "enabled": config.enable_filter,
                "threshold": config.similarity_threshold,
                "passed": passed,
                "filtered": filtered_out,
                "latency_ms": round(filter_ms, 2),
                "rule": "score >= threshold → оставлен; score < threshold → отброшен",
            },
            "reranking": {
                "enabled": config.enable_reranker,
                "reranker": rerank_kind,
                "model": rerank_model,
                "query_used": ("rewritten" if (config.reranker_query == "rewritten" and rewritten) else "original"),
                "n_reranked": len(candidates),
                "latency_ms": round(rerank_ms, 2),
            },
            "final": {"top_k": config.final_top_k, "count": len(final), "results": final},
            "items": items,
            "latency": {
                "query_rewrite_ms": round(rewrite_ms or 0.0, 2),
                "embedding_ms": round(embed_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "filtering_ms": round(filter_ms, 2),
                "reranking_ms": round(rerank_ms, 2),
                "deduplication_ms": round(dedup_ms, 2),
                "mmr_ms": round(mmr_ms, 2),
                "total_ms": round(total_ms, 2),
            },
            "config": config.model_dump(),
            "note": (
                "similarity_score — близость embedding'ов query и чанка; reranker_score — "
                "оценка релевантности пары query+chunk отдельной моделью; эти значения "
                "не являются напрямую сопоставимыми."
            ),
        }


pipeline = RetrievalPipeline()
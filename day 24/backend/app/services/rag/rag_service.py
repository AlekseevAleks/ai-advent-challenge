"""Rag Answer Service: оркестрация grounded-ответа.

Pipeline:
  retrieval → relevance gate → context → LLM → grounding validator → citations → response

Два gate:
  Gate 1 (relevance): если retrieved контекст нерелевантен — «не знаю», LLM не вызывается.
  Gate 2 (grounding): если ответ не подтверждается чанками — grounding_failed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ...schemas.rag import (
    AnswerConfig,
    AnswerLLMOutput,
    AnswerSource,
    RetrievalConfig,
)
from ...utils.errors import ValidationError2
from ...utils.ids import new_id
from ...utils.logging import get_logger
from .. import runtime
from . import answer_repo
from .answer_generator import answer_generator_holder
from .citation_builder import build_citations, build_source
from .context_builder import build_context
from .grounding_validator import GroundingValidator
from .pipeline import RetrievalPipeline
from .relevance_gate import evaluate as relevance_evaluate

logger = get_logger(__name__)

# Настраиваемый текст «не знаю»
INSUFFICIENT_ANSWER = (
    "Не знаю: в найденных документах недостаточно информации, "
    "чтобы надёжно ответить на этот вопрос. Пожалуйста, уточните вопрос "
    "или добавьте более подходящие документы."
)
GROUNDING_FAILED_ANSWER = (
    "Не знаю: найденные документы не позволяют надёжно подтвердить "
    "сформированный ответ. Пожалуйста, уточните вопрос."
)


def _retrieval_config(cfg: AnswerConfig) -> RetrievalConfig:
    return RetrievalConfig(
        query_rewrite=cfg.query_rewrite,
        query_rewrite_model=cfg.query_rewrite_model,
        initial_top_k=cfg.initial_top_k,
        final_top_k=cfg.final_top_k,
        enable_filter=cfg.enable_filter,
        similarity_threshold=cfg.similarity_threshold,
        enable_reranker=cfg.enable_reranker,
        reranker=cfg.reranker,
        reranker_model=cfg.reranker_model,
    )


class RagAnswerService:
    """Сервис генерации grounded-ответа. DI через конструктор для тестов."""

    def __init__(
        self,
        pipeline: Optional[RetrievalPipeline] = None,
        generator=None,
        validator: Optional[GroundingValidator] = None,
        save: bool = True,
    ):
        self._pipeline = pipeline
        self._generator = generator
        self._validator = validator or GroundingValidator()
        self._save = save

    def _get_pipeline(self) -> RetrievalPipeline:
        return self._pipeline if self._pipeline is not None else RetrievalPipeline()

    def _get_generator(self):
        return self._generator if self._generator is not None else answer_generator_holder.get()

    # ------------------------------------------------------------------
    def answer(
        self,
        query: str,
        config: AnswerConfig,
        collection_id: Optional[str] = None,
        index_id: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        t_start = time.perf_counter()
        query = (query or "").strip()
        if not query:
            raise ValidationError2("Пустой запрос для генерации ответа", code="empty_query")

        settings = runtime.effective_settings()
        lat: Dict[str, float] = {}
        pipeline = self._get_pipeline()

        # ---- Retrieval ----
        result = pipeline.run(
            query, _retrieval_config(config), collection_id=collection_id, index_id=index_id, strategy=strategy,
        )
        pl_lat = result.get("latency", {})
        lat["rewrite_ms"] = pl_lat.get("query_rewrite_ms", 0.0)
        lat["embedding_ms"] = pl_lat.get("embedding_ms", 0.0)
        lat["retrieval_ms"] = pl_lat.get("retrieval_ms", 0.0)
        lat["filtering_ms"] = pl_lat.get("filtering_ms", 0.0)
        lat["reranking_ms"] = pl_lat.get("reranking_ms", 0.0)

        final_chunks: List[dict] = result["final"]["results"]
        rewritten = result.get("rewritten_query")
        retrieval_meta = result["retrieval"]

        # ---- Gate 1: Relevance ----
        t0 = time.perf_counter()
        relevance_threshold = config.answer_relevance_threshold
        verdict = relevance_evaluate(
            final_chunks, threshold=relevance_threshold, min_supporting_chunks=config.min_supporting_chunks,
        )
        lat["gate_ms"] = (time.perf_counter() - t0) * 1000

        retrieval_block = {
            "initial_top_k": config.initial_top_k,
            "final_top_k": config.final_top_k,
            "threshold": relevance_threshold,
            "relevance_score": round(verdict.relevance_score, 6),
            "relevance_threshold": relevance_threshold,
            "candidates": retrieval_meta.get("candidates", len(final_chunks)),
            "collection_id": retrieval_meta.get("collection_id"),
            "index_id": retrieval_meta.get("index_id"),
            "strategy": retrieval_meta.get("strategy"),
        }

        if not verdict.passed:
            return self._respond(
                status="insufficient_context", answer=INSUFFICIENT_ANSWER,
                claims=[], grounding_score=0.0, claims_total=0, claims_supported=0,
                sources=[], citations=[], query=query, rewritten=rewritten,
                config=config, retrieval=retrieval_block, latency=lat, t_start=t_start, pl_lat=pl_lat,
            )

        # ---- Context ----
        t0 = time.perf_counter()
        context = build_context(final_chunks)
        lat["context_ms"] = (time.perf_counter() - t0) * 1000

        # ---- LLM generation ----
        answer_model = config.answer_model or settings.answer_model
        prompt_version = settings.answer_prompt_version
        t0 = time.perf_counter()
        gen = self._get_generator()
        llm: AnswerLLMOutput = gen.generate(query, context, model=answer_model, prompt_version=prompt_version)
        lat["llm_ms"] = (time.perf_counter() - t0) * 1000

        if llm.insufficient_context or not llm.answer.strip():
            return self._respond(
                status="insufficient_context", answer=INSUFFICIENT_ANSWER,
                claims=[], grounding_score=0.0, claims_total=0, claims_supported=0,
                sources=[], citations=[], query=query, rewritten=rewritten,
                config=config, retrieval=retrieval_block, latency=lat, t_start=t_start, pl_lat=pl_lat,
                answer_model=answer_model,
            )

        # ---- Grounding validator ----
        t0 = time.perf_counter()
        grounding = self._validator.validate(
            llm,
            final_chunks,
            grounding_threshold=config.grounding_threshold,
            semantic_threshold=settings.grounding_similarity_threshold,
            use_semantic=True,
        )
        lat["validate_ms"] = (time.perf_counter() - t0) * 1000

        # ---- Gate 2: Grounding ----
        if not grounding["grounded"]:
            return self._respond(
                status="grounding_failed", answer=GROUNDING_FAILED_ANSWER,
                claims=as_claims(grounding), grounding_score=grounding["grounding_score"],
                claims_total=grounding["claims_total"], claims_supported=grounding["claims_supported"],
                sources=[], citations=[], query=query, rewritten=rewritten,
                config=config, retrieval=retrieval_block, latency=lat, t_start=t_start, pl_lat=pl_lat,
                answer_model=answer_model,
            )

        # ---- Citations & sources ----
        chunks_by_id = {c.get("chunk_id", ""): c for c in final_chunks}
        referenced: List[str] = []
        for cl in llm.claims:
            referenced.extend(cl.chunk_ids)
        citations = build_citations(chunks_by_id, referenced, max_quote_chars=settings.answer_max_citation_chars)
        sources: List[AnswerSource] = []
        seen = set()
        for cid in referenced:
            c = chunks_by_id.get(cid)
            if c is not None and cid not in seen:
                sources.append(build_source(c))
                seen.add(cid)

        return self._respond(
            status="answered", answer=llm.answer,
            claims=as_claims(grounding), grounding_score=grounding["grounding_score"],
            claims_total=grounding["claims_total"], claims_supported=grounding["claims_supported"],
            sources=sources, citations=[c.model_dump() for c in citations],
            query=query, rewritten=rewritten, config=config, retrieval=retrieval_block,
            latency=lat, t_start=t_start, pl_lat=pl_lat, answer_model=answer_model,
        )

    # ------------------------------------------------------------------
    def _respond(self, **kw) -> Dict[str, Any]:
        status = kw["status"]
        claims = kw["claims"]
        lat = dict(kw["latency"])
        lat["total_ms"] = round((time.perf_counter() - kw["t_start"]) * 1000, 2)
        lat = {k: round(v, 2) for k, v in lat.items()}
        payload = {
            "status": status,
            "answer": kw["answer"],
            "original_query": kw["query"],
            "rewritten_query": kw["rewritten"],
            "sources": [s.model_dump() if hasattr(s, "model_dump") else s for s in kw["sources"]],
            "citations": kw["citations"],
            "claims": claims,
            "grounding": {
                "grounded": status == "answered",
                "grounding_score": kw["grounding_score"],
                "claims_total": kw["claims_total"],
                "claims_supported": kw["claims_supported"],
            },
            "retrieval": kw["retrieval"],
            "config": kw["config"].model_dump(mode="json"),
            "latency": lat,
        }
        if kw.get("answer_model"):
            payload["answer_model"] = kw["answer_model"]
        payload["prompt_version"] = runtime.effective_settings().answer_prompt_version
        if self._save:
            payload = persist_answer(payload, kw["config"])
        return payload


def as_claims(grounding: dict) -> List[dict]:
    out = []
    for cl in grounding.get("claims", []):
        out.append(cl.model_dump() if hasattr(cl, "model_dump") else cl)
    return out


def persist_answer(payload: dict, config: AnswerConfig) -> dict:
    rec = {
        "id": new_id("ans"),
        "query": payload["original_query"],
        "rewritten_query": payload["rewritten_query"],
        "collection_id": payload.get("retrieval", {}).get("collection_id"),
        "index_id": payload.get("retrieval", {}).get("index_id"),
        "strategy": payload.get("retrieval", {}).get("strategy"),
        "status": payload["status"],
        "answer": payload["answer"],
        "answer_model": payload.get("answer_model"),
        "relevance_score": payload.get("retrieval", {}).get("relevance_score"),
        "grounding_score": payload.get("grounding", {}).get("grounding_score"),
        "grounding_threshold": config.grounding_threshold,
        "relevance_threshold": config.answer_relevance_threshold,
        "claims_total": payload.get("grounding", {}).get("claims_total", 0),
        "claims_supported": payload.get("grounding", {}).get("claims_supported", 0),
        "prompt_version": payload.get("prompt_version"),
        "config": payload.get("config", {}),
        "sources": payload.get("sources", []),
        "citations": payload.get("citations", []),
        "claims": payload.get("claims", []),
        "retrieval": payload.get("retrieval"),
        "latency": payload.get("latency"),
    }
    row = answer_repo.create_answer(rec)
    payload["id"] = row["id"]
    return payload


answer_service = RagAnswerService()

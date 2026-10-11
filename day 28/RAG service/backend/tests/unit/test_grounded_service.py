"""Unit-тесты оркестрации grounded-ответа (service) с фейковым pipeline/LLM."""

from __future__ import annotations

import json

from app.schemas.rag import AnswerConfig, AnswerLLMOutput
from app.services.rag.answer_generator import AnswerGenerator
from app.services.rag.grounding_validator import GroundingValidator
from app.services.rag.rag_service import RagAnswerService, INSUFFICIENT_ANSWER, GROUNDING_FAILED_ANSWER


def _chunk(cid, text, sim=0.9, rerank=0.9, source="a.md", section="S"):
    return {
        "chunk_id": cid, "source": source, "section": section, "title": "a.md",
        "text": text, "retrieval_score": sim, "reranker_score": rerank,
    }


class FakePipeline:
    def __init__(self, final_chunks, rewritten=None):
        self._final = final_chunks
        self._rewritten = rewritten

    def run(self, query, config, collection_id=None, index_id=None, strategy=None):
        return {
            "original_query": query, "rewritten_query": self._rewritten,
            "final": {"results": self._final},
            "items": self._final,
            "retrieval": {"candidates": len(self._final), "collection_id": collection_id,
                          "index_id": index_id, "strategy": strategy},
            "latency": {"query_rewrite_ms": 1, "embedding_ms": 2, "retrieval_ms": 3,
                        "filtering_ms": 0, "reranking_ms": 0},
        }


def _service(pipeline, generator_fn):
    gen = AnswerGenerator(chat_fn=generator_fn)
    val = GroundingValidator(embed_fn=lambda t: None)  # только лексическая проверка
    return RagAnswerService(pipeline=pipeline, generator=gen, validator=val, save=False)


def test_insufficient_context_gate_skips_llm():
    pipeline = FakePipeline([_chunk("c1", "низкая релевантность текст", sim=0.1, rerank=None)])

    def should_not_call(model, sys_p, user):
        raise AssertionError("LLM не должен вызываться при провале relevance gate")

    svc = _service(pipeline, should_not_call)
    out = svc.answer("вопрос про погоду", AnswerConfig(
        answer_relevance_threshold=0.65, enable_reranker=False, enable_filter=False,
    ))
    assert out["status"] == "insufficient_context"
    assert out["sources"] == [] and out["citations"] == []
    assert out["grounding"]["grounded"] is False and out["grounding"]["grounding_score"] == 0.0
    assert out["answer"] == INSUFFICIENT_ANSWER
    assert out["retrieval"]["relevance_score"] == 0.1


def test_answered_with_sources_and_citations():
    pipeline = FakePipeline([
        _chunk("c1", "FAISS библиотека для поиска похожих векторов в большом корпусе"),
    ])
    svc = _service(pipeline, lambda m, s, u: json.dumps({
        "answer": "FAISS — библиотека для векторного поиска.",
        "claims": [{"text": "FAISS библиотека для поиска векторов", "chunk_ids": ["c1"]}],
        "insufficient_context": False,
    }))
    out = svc.answer("Что такое FAISS?", AnswerConfig(
        answer_relevance_threshold=0.65, grounding_threshold=0.7, enable_reranker=False,
    ))
    assert out["status"] == "answered"
    assert out["grounding"]["grounded"] is True
    assert out["grounding"]["claims_supported"] == 1
    assert out["sources"] and out["sources"][0]["chunk_id"] == "c1"
    assert out["citations"] and out["citations"][0]["chunk_id"] == "c1"
    # цитата — реальный фрагмент чанка
    chunk_text = pipeline._final[0]["text"]
    assert out["citations"][0]["quote"] in chunk_text
    assert out["claims"][0]["grounded"] is True


def test_grounding_failed_when_claim_unsupported():
    pipeline = FakePipeline([
        _chunk("c1", "FAISS библиотека для поиска похожих векторов в большом корпусе"),
    ])
    svc = _service(pipeline, lambda m, s, u: json.dumps({
        "answer": "Вчера в Берлине было солнечно.",
        "claims": [{"text": "Вчера в Берлине было солнечно", "chunk_ids": ["c1"]}],
        "insufficient_context": False,
    }))
    out = svc.answer("Погода?", AnswerConfig(
        answer_relevance_threshold=0.65, grounding_threshold=0.7, enable_reranker=False,
    ))
    assert out["status"] == "grounding_failed"
    assert out["answer"] == GROUNDING_FAILED_ANSWER
    assert out["sources"] == [] and out["citations"] == []
    assert out["grounding"]["grounded"] is False
    assert out["grounding"]["claims_supported"] == 0


def test_llm_insufficient_context_flag():
    pipeline = FakePipeline([_chunk("c1", "FAISS библиотека для поиска векторов", rerank=0.9)])
    svc = _service(pipeline, lambda m, s, u: json.dumps({
        "answer": "не знаю", "claims": [], "insufficient_context": True,
    }))
    out = svc.answer("Вопрос?", AnswerConfig(enable_reranker=False))
    assert out["status"] in ("insufficient_context",)
    assert out["answer"] == INSUFFICIENT_ANSWER

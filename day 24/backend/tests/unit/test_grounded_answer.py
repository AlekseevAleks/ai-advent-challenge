"""Unit-тесты grounded-ответа (без Ollama и больших моделей)."""

from __future__ import annotations

import json

import pytest

from app.schemas.rag import AnswerConfig, AnswerLLMOutput, RagAnswerRequest
from app.services.rag.answer_generator import AnswerGenerator
from app.services.rag.citation_builder import (
    build_citations,
    build_source,
    extract_quote,
    validate_quote,
)
from app.services.rag.grounding_validator import GroundingValidator, lexical_support_ratio
from app.services.rag.relevance_gate import evaluate as relevance_evaluate
from app.utils.errors import ConflictError


# ---------------------------------------------------------------------------
# Relevance gate
# ---------------------------------------------------------------------------

def _chunk(cid, rerank=None, sim=0.5):
    return {"chunk_id": cid, "retrieval_score": sim, "reranker_score": rerank}


def test_relevance_gate_pass_reranker():
    chunks = [_chunk("c1", rerank=0.91), _chunk("c2", rerank=0.7)]
    v = relevance_evaluate(chunks, threshold=0.65, min_supporting_chunks=1)
    assert v.passed is True
    assert v.relevance_score == pytest.approx(0.91)
    assert v.relevance_score >= v.threshold


def test_relevance_gate_fail_below_threshold():
    chunks = [_chunk("c1", rerank=0.64), _chunk("c2", rerank=0.3)]
    v = relevance_evaluate(chunks, threshold=0.65, min_supporting_chunks=1)
    assert v.passed is False
    assert v.relevance_score == pytest.approx(0.64)


def test_relevance_gate_uses_retrieval_when_no_reranker():
    chunks = [_chunk("c1", rerank=None, sim=0.8), _chunk("c2", rerank=None, sim=0.2)]
    v = relevance_evaluate(chunks, threshold=0.65, min_supporting_chunks=1)
    assert v.passed is True and v.relevance_score == pytest.approx(0.8)


def test_relevance_gate_empty():
    v = relevance_evaluate([], threshold=0.65, min_supporting_chunks=1)
    assert v.passed is False and v.relevance_score == 0.0


def test_relevance_gate_min_supporting_chunks():
    chunks = [_chunk("c1", rerank=0.9), _chunk("c2", rerank=0.7)]
    assert relevance_evaluate(chunks, 0.65, min_supporting_chunks=2).passed is True
    assert relevance_evaluate(chunks, 0.65, min_supporting_chunks=3).passed is False


# ---------------------------------------------------------------------------
# Citation & Source
# ---------------------------------------------------------------------------

def test_citation_valid_present_in_chunk():
    chunk_text = "FAISS is a library for efficient similarity search and clustering of dense vectors."
    quote = extract_quote(chunk_text)
    assert quote == chunk_text
    assert validate_quote(quote, chunk_text) is True


def test_citation_fake_not_in_chunk():
    chunk_text = "FAISS is a library for efficient similarity search."
    assert validate_quote("FAISS is the fastest vector database available.", chunk_text) is False


def test_citation_wrong_chunk_fails():
    chunk_text = "Python is a programming language."
    assert validate_quote("FAISS is a library.", chunk_text) is False


def test_extract_quote_is_substring_and_respects_limit():
    text = "Первое предложение про RAG. Второе предложение об эмбеддингах. Третье длинное."
    quote = extract_quote(text, max_chars=30)
    assert len(quote) <= 30
    assert quote in text
    assert quote.endswith(".") or quote.endswith("…")


def test_extract_quote_word_boundary():
    text = " ".join(["слово"] * 100)
    quote = extract_quote(text, max_chars=40)
    assert len(quote) <= 40 and quote in text


def test_build_citations_references_real_chunks():
    chunks = {
        "chunk_1": {"chunk_id": "chunk_1", "source": "a.md", "section": "S1",
                    "text": "Эмбеддинги — это векторные представления текста."},
        "chunk_2": {"chunk_id": "chunk_2", "source": "b.md", "section": None,
                    "text": "FAISS хранит векторы и выполняет поиск."},
    }
    cites = build_citations(chunks, ["chunk_1", "chunk_missing", "chunk_1"], max_quote_chars=200)
    assert len(cites) == 1
    assert cites[0].chunk_id == "chunk_1"
    assert validate_quote(cites[0].quote, chunks["chunk_1"]["text"]) is True
    src = build_source(chunks["chunk_2"])
    assert src.source == "b.md" and src.chunk_id == "chunk_2"


def test_source_from_existing_chunk():
    chunk = {"chunk_id": "chunk_x", "source": "docs/rag.md", "section": "Emb",
             "title": "rag.md", "page_start": 1, "page_end": 1}
    s = build_source(chunk)
    assert s.chunk_id == "chunk_x" and s.source == "docs/rag.md"
    assert s.page_start == 1 and s.section == "Emb"


# ---------------------------------------------------------------------------
# Grounding validator
# ---------------------------------------------------------------------------

def test_lexical_support():
    claim = "FAISS библиотека для поиска векторов"
    chunk = "FAISS это библиотека для эффективного поиска похожих векторов text"
    assert lexical_support_ratio(claim, chunk) >= 0.5


def test_grounding_supported_claim():
    v = GroundingValidator()
    llm = AnswerLLMOutput(
        answer="FAISS используется для поиска векторов.",
        claims=[{"text": "FAISS используется для поиска векторов.", "chunk_ids": ["c1"]}],
    )
    chunks = [{"chunk_id": "c1", "text": "FAISS используется для поиска похожих векторов в базе."}]
    g = v.validate(llm, chunks, grounding_threshold=0.70)
    assert g["claims_supported"] == 1 and g["grounding_score"] == 1.0
    assert g["grounded"] is True


def test_grounding_unsupported_claim():
    v = GroundingValidator()
    llm = AnswerLLMOutput(
        answer="Погода в Берлине сегодня солнечная.",
        claims=[{"text": "Погода в Берлине сегодня солнечная.", "chunk_ids": ["c1"]}],
    )
    chunks = [{"chunk_id": "c1", "text": "FAISS это библиотека для векторного поиска."}]
    g = v.validate(llm, chunks, grounding_threshold=0.70, use_semantic=False)
    assert g["claims_supported"] == 0 and g["grounding_score"] == 0.0
    assert g["grounded"] is False


def test_grounding_claim_with_missing_chunk():
    v = GroundingValidator()
    llm = AnswerLLMOutput(answer="ответ", claims=[{"text": "утверждение", "chunk_ids": ["not_exist"]}])
    g = v.validate(llm, [{"chunk_id": "c1", "text": "любой текст"}], grounding_threshold=0.5, use_semantic=False)
    assert g["claims_supported"] == 0


def test_grounding_no_claims_fails():
    v = GroundingValidator()
    llm = AnswerLLMOutput(answer="ответ без claims", claims=[])
    g = v.validate(llm, [{"chunk_id": "c1", "text": "text"}], grounding_threshold=0.5)
    assert g["grounded"] is False and g["grounding_score"] == 0.0


# ---------------------------------------------------------------------------
# AnswerGenerator (mock chat)
# ---------------------------------------------------------------------------

def test_answer_generator_parses_json():
    gen = AnswerGenerator(chat_fn=lambda model, sys_p, user: json.dumps(
        {"answer": "FAISS — библиотека поиска.",
         "claims": [{"text": "утверждение", "chunk_ids": ["c1"]}],
         "insufficient_context": False}))
    out = gen.generate("Что такое FAISS?", "context", model="llama3.2")
    assert out.answer and out.claims[0].chunk_ids == ["c1"]


def test_answer_generator_insufficient_context_flag():
    gen = AnswerGenerator(chat_fn=lambda m, s, u: json.dumps(
        {"answer": "не знаю", "claims": [], "insufficient_context": True}))
    out = gen.generate("q", "ctx")
    assert out.insufficient_context is True


def test_answer_generator_handles_json_wrapped_in_markdown():
    raw = '```json\n{"answer": "A.", "claims": [], "insufficient_context": false}\n```'
    gen = AnswerGenerator(chat_fn=lambda m, s, u: raw)
    out = gen.generate("q", "ctx")
    assert out.answer == "A."


def test_answer_generator_rejects_non_json():
    gen = AnswerGenerator(chat_fn=lambda m, s, u: "Просто текст без JSON")
    with pytest.raises(ConflictError, match="JSON"):
        gen.generate("q", "ctx")


def test_answer_generator_schema_validation():
    gen = AnswerGenerator(chat_fn=lambda m, s, u: json.dumps({"claims": [{"nope": 1}]}))
    with pytest.raises(ConflictError, match="валидац"):
        gen.generate("q", "ctx")


# ---------------------------------------------------------------------------
# AnswerConfig / schema
# ---------------------------------------------------------------------------

def test_answer_config_topk_validation():
    with pytest.raises(ValueError, match="initial_top_k"):
        AnswerConfig(initial_top_k=3, final_top_k=5)
    assert AnswerConfig(initial_top_k=5, final_top_k=5).final_top_k == 5


def test_rag_answer_request_schema():
    req = RagAnswerRequest(collection_id="c", query="вопрос", config=AnswerConfig())
    assert req.query and req.config.answer_relevance_threshold == 0.65

"""Unit-тесты модуля «Reranking & Filtering» (без Ollama и больших моделей)."""

from __future__ import annotations

import pytest

from app.schemas.rag import RetrievalConfig
from app.services.rag.metrics import (
    aggregate_metrics,
    compute_metrics,
    hit_at_k,
    mrr,
    precision_at_k,
    recall_at_k,
    relevant_keys,
)
from app.services.rag.query_rewriter import QueryRewriter
from app.services.rag.rerankers import (
    HeuristicReranker,
    RerankerUnavailable,
    SimilarityReranker,
    build_reranker,
)
from app.utils.errors import ConflictError


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------

def test_metrics_known_set():
    predicted = ["b", "a", "d", "c", "e"]     # top-5
    relevant = ["a", "d"]
    assert hit_at_k(predicted, relevant, k=5) == 1.0
    assert precision_at_k(predicted, relevant, k=5) == 2 / 5
    assert recall_at_k(predicted, relevant, k=5) == 1.0      # оба найдены
    assert mrr(predicted, relevant, k=5) == 0.5              # первый релевантный на месте 2


def test_metrics_hit_depends_on_k():
    predicted = ["x", "y", "relevant_chunk", "z"]
    relevant = ["relevant_chunk"]
    assert hit_at_k(predicted, relevant, k=2) == 0.0
    assert hit_at_k(predicted, relevant, k=3) == 1.0


def test_mrr_rank_of_first_relevant():
    assert mrr(["a", "b"], ["b"], k=5) == 0.5
    assert mrr(["a", "b"], ["b"], k=1) == 0.0
    assert mrr(["a"], ["b"], k=5) == 0.0


def test_metrics_empty_gt_or_predictions():
    assert precision_at_k(["a", "b"], [], k=3) == 0.0
    assert recall_at_k([], ["a"], k=3) == 0.0
    assert mrr(["a"], [], k=3) == 0.0
    m = compute_metrics([], ["a"], k=3)
    assert m["hit_at_k"] == 0.0 and m["precision_at_k"] == 0.0


def test_aggregate_metrics_empty():
    a = aggregate_metrics([], k=5)
    assert a["questions"] == 0 and a["hit_at_k"] == 0.0


def test_relevant_and_prediction_alphabet():
    keys = relevant_keys({"relevant_chunk_ids": ["c1"], "expected_sources": ["a.md"], "expected_sections": ["S"]})
    assert keys == ["c1", "s:a.md", "sec:S"]


# ---------------------------------------------------------------------------
# Top-K валидация
# ---------------------------------------------------------------------------

def test_topk_initial_greater_equal_final():
    with pytest.raises(ValueError, match="initial_top_k"):
        RetrievalConfig(initial_top_k=3, final_top_k=5)
    cfg = RetrievalConfig(initial_top_k=5, final_top_k=5)
    assert cfg.final_top_k == 5


def test_threshold_range():
    with pytest.raises(ValueError):
        RetrievalConfig(similarity_threshold=1.5)
    with pytest.raises(ValueError):
        RetrievalConfig(similarity_threshold=-0.1)
    assert RetrievalConfig(similarity_threshold=0.65).similarity_threshold == 0.65


# ---------------------------------------------------------------------------
# Реранкеры
# ---------------------------------------------------------------------------

def test_heuristic_reranker_can_change_order():
    """Ключевое свойство: reranker может изменить порядок retrieval.

    FAISS поставил Python выше, но keyword-сигнал сильнее для FAISS-чанка.
    """
    query = "FAISS vector search"
    docs = [
        "Python is a programming language with rich ecosystem.",   # retrieval-лидер, разговор
        "FAISS provides efficient vector similarity search index.",  # keyword-совпадения
    ]
    base = [0.9, 0.5]
    scores = HeuristicReranker(base_scores=base).rerank(query, docs)
    # 0.7*сема (0.9→1.0), но keyword по FAISS значительно выше → score должен быть выше
    assert scores[1] > scores[0]


def test_similarity_reranker_preserves_retrieval_order():
    scores = SimilarityReranker(base_scores=[0.9, 0.4]).rerank("q", ["a", "b"])
    assert scores == [1.0, 0.0]


def test_cross_encoder_unavailable_without_lib():
    """Без установленного sentence-transformers — понятная ошибка, не падение."""
    reranker = build_reranker("cross_encoder", model="BAAI/bge-reranker-base")
    with pytest.raises(RerankerUnavailable) as exc:
        reranker.rerank("q", ["doc"])
    assert "sentence-transformers" in str(exc.value) or "не удалось" in str(exc.value).lower()


def test_rerankers_status_no_crash():
    from app.services.rag.rerankers import rerankers_status

    st = rerankers_status("BAAI/bge-reranker-base")
    assert set(st) == {"heuristic", "cross_encoder", "similarity"}


def test_factory_unknown_kind():
    with pytest.raises(ValueError):
        build_reranker("unknown_kind")


# ---------------------------------------------------------------------------
# Query Rewriter (mock chat)
# ---------------------------------------------------------------------------

def _fake_rewriter(chat_fn):
    return QueryRewriter(chat_fn=chat_fn)


def test_query_rewrite_returns_string():
    rw = _fake_rewriter(lambda model, sys_p, user: "Как работает vector similarity search в FAISS?")
    res = rw.rewrite("как это работает?")
    assert isinstance(res.rewritten, str) and res.rewritten.strip()
    assert res.latency_ms >= 0


def test_query_rewrite_empty_result_is_error():
    rw = _fake_rewriter(lambda model, sys_p, user: "   ")
    with pytest.raises(ConflictError):
        rw.rewrite("q")


def test_query_rewrite_model_error_propagates():
    def boom(model, sys_p, user):
        raise RuntimeError("net")

    rw = _fake_rewriter(boom)
    with pytest.raises(RuntimeError):
        rw.rewrite("q")


def test_query_rewrite_empty_query():
    rw = _fake_rewriter(lambda model, sys_p, user: "x")
    with pytest.raises(ConflictError, match="Пустой запрос"):
        rw.rewrite("   ")


def test_query_rewrite_truncates_long_query():
    rw = _fake_rewriter(lambda model, sys_p, user: user[:10] + "!")
    long_q = "а" * 5000
    res = rw.rewrite(long_q)
    # системный лимит из настроек не даст уйти в запрос длиннее 2000 символов
    assert len(res.rewritten) <= 2000
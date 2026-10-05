"""Интеграционные тесты модуля «Reranking & Filtering» (HTTP API, фейковые клиенты)."""

from __future__ import annotations

import time

import pytest

from app.services.rag.query_rewriter import QueryRewriter, rewriter_holder


def _ready_index(client) -> dict:
    """Загрузить демо-документы и построить structural-индекс (fake embedder)."""
    docs = client.post("/api/documents/demo").json()["documents"]
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": ["structural"],
        "mode": "new_collection",
        "collection_name": "RAG-тест",
        "structural": {"max_chunk_size": 900, "min_chunk_size": 150},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        p = client.get(f"/api/indexing/jobs/{job_id}").json()
        if p["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(0.2)
    return client.get("/api/collections").json()[0]


@pytest.fixture()
def rag_collection(client):
    return _ready_index(client)


@pytest.fixture()
def fake_rewriter(client):
    """Подмена query rewriter'а на детерминированный (только для тестов)."""
    rw = QueryRewriter(chat_fn=lambda model, system, user: f"{user} векторы поиск")
    rewriter_holder.set_fake(rw)
    yield rw
    rewriter_holder.reset()


def _config(**over):
    base = dict(
        query_rewrite=False, initial_top_k=20, final_top_k=5,
        enable_filter=True, similarity_threshold=0.0,
        enable_reranker=True, reranker="heuristic",
    )
    base.update(over)
    return base


def _search(client, collection_id, query="чем полезна индексация для RAG", config=None):
    return client.post("/api/rag/search", json={
        "collection_id": collection_id, "strategy": "structural",
        "query": query, "config": config or _config(),
    })


# ---------------------------------------------------------------------------
# Отдельные этапы
# ---------------------------------------------------------------------------

def test_retrieve_endpoint(client, rag_collection):
    r = client.post("/api/rag/retrieve", json={
        "collection_id": rag_collection["id"], "strategy": "structural",
        "query": "чем полезна индексация для RAG", "top_k": 10,
    })
    assert r.status_code == 200
    j = r.json()
    assert j["retrieval"]["candidates"] > 0
    assert j["results"], "должны быть кандидаты retrieval"


def test_filter_boundary_api(client):
    """Правило: score >= threshold → оставлен; score < threshold → отброшен."""
    r = client.post("/api/rag/filter", json={"scores": [0.91, 0.65, 0.64, 0.1], "threshold": 0.65})
    j = r.json()
    assert j["passed"] == 2 and j["filtered"] == 2
    assert j["kept_positions"] == [0, 1]  # 0.65 проходит (>=), 0.64 — нет
    assert client.post("/api/rag/filter", json={"scores": [0.5, 0.4], "threshold": 1.0}).json()["passed"] == 0
    assert client.post("/api/rag/filter", json={"scores": [0.5, 0.4], "threshold": 0.0}).json()["passed"] == 2


def test_rerank_endpoint(client):
    r = client.post("/api/rag/rerank", json={
        "query": "FAISS vector search",
        "documents": ["FAISS provides efficient vector similarity search",
                      "Python is a programming language"],
        "reranker": "heuristic", "base_scores": [0.9, 0.1],
    })
    assert r.status_code == 200
    j = r.json()
    assert j["reranker"] == "heuristic"
    assert len(j["scores"]) == len(j["reranked_positions"]) == 2


# ---------------------------------------------------------------------------
# Полный pipeline
# ---------------------------------------------------------------------------

def test_search_baseline_vs_filter(client, rag_collection):
    cid = rag_collection["id"]
    q = "чем полезна индексация для RAG"

    j1 = _search(client, cid, q, _config(enable_filter=False, enable_reranker=False)).json()
    assert j1["filtering"]["enabled"] is False
    assert j1["final"]["count"] == 5

    # порог 1.0 отбрасывает (почти) всех кандидатов: score == 1.0 теоретически возможно
    j2 = _search(client, cid, q, _config(similarity_threshold=1.0, enable_reranker=False)).json()
    assert j2["filtering"]["filtered"] >= j2["retrieval"]["candidates"] - 1
    assert j2["filtering"]["passed"] + j2["filtering"]["filtered"] == j2["retrieval"]["candidates"]
    if j2["filtering"]["filtered"] == j2["retrieval"]["candidates"]:
        assert j2["final"]["count"] == 0

    # порог 0.0 отсекает только кандидатов с отрицательным similarity (косинус может быть < 0)
    j3 = _search(client, cid, q, _config(similarity_threshold=0.0, enable_reranker=False)).json()
    negatives = sum(1 for it in j3["items"] if it["retrieval_score"] < 0.0)
    assert j3["filtering"]["filtered"] == negatives
    assert j3["filtering"]["passed"] == len(j3["items"]) - negatives


def test_search_reranking_scores_and_consistency(client, rag_collection):
    j = _search(client, rag_collection["id"], config=_config()).json()
    assert j["reranking"]["reranker"] == "heuristic"
    kept = [it for it in j["items"] if it["status"] == "kept"]
    assert all(it["reranker_score"] is not None for it in kept)
    final_scores = [it["reranker_score"] for it in j["final"]["results"]]
    assert final_scores == sorted(final_scores, reverse=True)
    assert j["reranking"]["n_reranked"] > 0


def test_search_rewrite_roundtrip(client, fake_rewriter, rag_collection):
    cfg = _config(query_rewrite=True, enable_reranker=False, enable_filter=False)
    j = _search(client, rag_collection["id"], "чем полезна индексация", cfg).json()
    assert j["rewrite"]["enabled"] is True
    assert j["rewritten_query"] and "векторы поиск" in j["rewritten_query"]


def test_query_rewrite_endpoint(client, fake_rewriter):
    r = client.post("/api/rag/query-rewrite", json={"query": "как это работает?"})
    assert r.status_code == 200
    j = r.json()
    assert j["original_query"] == "как это работает?"
    assert "векторы поиск" in j["rewritten_query"]


def test_reranker_unavailable_message(client, rag_collection):
    cfg = _config(enable_reranker=True, reranker="cross_encoder")
    r = _search(client, rag_collection["id"], "чем полезна индексация", cfg)
    assert r.status_code == 409
    detail = r.json()["detail"].lower()
    assert "установить" in detail or "heuristic" in detail


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _make_dataset(client, questions):
    r = client.post("/api/evaluation/datasets", json={"name": "Сравнение режимов", "items": questions})
    assert r.status_code == 201
    return r.json()


def test_evaluation_dataset_crud(client):
    ds = _make_dataset(client, [
        {"question": "Что такое RAG?", "expected_sources": ["rag_principles.md"]},
        {"question": "Что такое FAISS?", "expected_sources": ["faiss_and_search.md"]},
    ])
    assert len(ds["items"]) == 2
    assert any(d["id"] == ds["id"] for d in client.get("/api/evaluation/datasets").json())
    assert client.get(f"/api/evaluation/datasets/{ds['id']}").status_code == 200
    assert client.delete(f"/api/evaluation/datasets/{ds['id']}").status_code == 204


def test_evaluation_run_comparison(client, fake_rewriter, rag_collection):
    ds = _make_dataset(client, [
        {"question": "чем полезна индексация для RAG?", "expected_sources": ["rag_principles.md"]},
        {"question": "что такое FAISS?", "expected_sources": ["faiss_and_search.md"]},
    ])
    r = client.post(f"/api/evaluation/datasets/{ds['id']}/run", json={
        "collection_id": rag_collection["id"], "strategy": "structural",
        "modes": ["baseline", "filter", "rerank", "rewrite", "rewrite_rerank", "full"],
        "base_config": _config(similarity_threshold=0.0, reranker="heuristic"),
        "name": "Запуск 1",
    })
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "completed", run.get("message")
    assert set(run["results"].keys()) == {"baseline", "filter", "rerank", "rewrite", "rewrite_rerank", "full"}
    for mode, res in run["results"].items():
        assert res["metrics"]["questions"] == 2
        assert "latency" in res
    assert run["metrics"]["baseline"]["k"] == 5
    jexp = client.get(f"/api/evaluation/runs/{run['id']}/export?format=json").json()
    assert jexp["results"]
    csvs = client.get(f"/api/evaluation/runs/{run['id']}/export?format=csv").text
    assert "question" in csvs


def test_experiment_save_export_compare(client, rag_collection):
    cid = rag_collection["id"]
    cfg = _config()
    res = _search(client, cid, "чем полезна индексация для RAG", cfg).json()
    exp = client.post("/api/experiments", json={
        "name": "Эксперимент 1", "query": "чем полезна индексация для RAG",
        "config": cfg, "collection_id": cid, "strategy": "structural", "result": res,
    })
    assert exp.status_code == 201
    eid = exp.json()["id"]
    got = client.get(f"/api/experiments/{eid}").json()
    assert got["query"] and got["result"]["final"]["count"] == 5
    assert client.get(f"/api/experiments/{eid}/export?format=json").json()["experiment_id"] == eid
    assert "chunk_id" in client.get(f"/api/experiments/{eid}/export?format=csv").text

    exp2 = client.post("/api/experiments", json={
        "name": "Эксперимент 2", "query": "чем полезна индексация для RAG",
        "config": _config(enable_filter=False), "collection_id": cid,
        "strategy": "structural", "result": res,
    }).json()["id"]
    cmp = client.post(f"/api/experiments/{eid}/compare?other_id={exp2}")
    assert cmp.status_code == 200
    assert cmp.json()["current"]["id"] == eid and cmp.json()["compared"]["id"] == exp2
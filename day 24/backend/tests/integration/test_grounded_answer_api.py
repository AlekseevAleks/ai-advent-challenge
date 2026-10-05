"""Интеграционные тесты grounded-ответа (HTTP API, фейковые клиенты и LLM)."""

from __future__ import annotations

import re
import time

import pytest

from app.schemas.rag import AnswerLLMOutput
from app.services.rag.answer_generator import answer_generator_holder


def _ready_index(client) -> dict:
    docs = client.post("/api/documents/demo").json()["documents"]
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": ["structural"],
        "mode": "new_collection",
        "collection_name": "RAG-тест-grounded",
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
def grounded_collection(client):
    return _ready_index(client)


class FakeAnswerGenerator:
    """Детерминированный ответ: ссылается на первый чанк из контекста.

    Claim содержит реальный фрагмент текста чанка → лексический grounding проходит.
    """

    def __init__(self, phrasing: str):
        self._phrasing = phrasing  # 'grounded' | 'unsupported' | 'abstain'

    def generate(self, query, context, model=None, prompt_version=None):
        m = re.search(r"\[chunk_id=([^\]\s]+)\]\s*(.*?)(?=\n\s*\[chunk_id=|\Z)", context, re.S)
        if self._phrasing == "abstain" or not m:
            return AnswerLLMOutput(answer="недостаточно", claims=[], insufficient_context=True)
        cid = m.group(1)
        body_lines = [l for l in m.group(2).splitlines()
                      if not l.strip().startswith(("source=", "section="))]
        body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
        if self._phrasing == "unsupported":
            claim_text = "Погода в Берлине сегодня солнечная и тёплая"
        else:
            claim_text = body[:70] or "ответ"
        return AnswerLLMOutput(
            answer="Ответ основан на найденном документе.",
            claims=[{"text": claim_text, "chunk_ids": [cid]}],
            insufficient_context=False,
        )


@pytest.fixture()
def fake_answer_generator():
    def _apply(kind):
        gen = FakeAnswerGenerator(kind)
        answer_generator_holder.set_fake(gen)
        yield gen
        answer_generator_holder.reset()
    # fixture wrapper form
    manager = _apply("grounded")
    yield next(manager)


_CONFIG = {
    "query_rewrite": False, "initial_top_k": 20, "final_top_k": 5,
    "enable_filter": True, "similarity_threshold": 0.0,
    "enable_reranker": True, "reranker": "heuristic",
    "answer_relevance_threshold": 0.0,  # deterministic pass
    "grounding_threshold": 0.5,
}


def _answer(client, cid, query="чем полезна индексация для RAG", config=None):
    return client.post("/api/rag/answer", json={
        "collection_id": cid, "strategy": "structural", "query": query,
        "config": config or _CONFIG,
    })


def test_grounded_answer_answered(client, grounded_collection, fake_answer_generator):
    r = _answer(client, grounded_collection["id"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "answered"
    assert j["answer"]
    assert j["sources"], "должны быть источники"
    assert j["citations"], "должны быть цитаты"
    assert j["citations"][0]["quote"]
    assert j["grounding"]["grounded"] is True
    assert j["grounding"]["claims_supported"] >= 1
    # response schema обязательные поля
    for k in ("answer", "sources", "citations", "claims", "grounding"):
        assert k in j


def test_grounded_answer_history(client, grounded_collection, fake_answer_generator):
    j = _answer(client, grounded_collection["id"]).json()
    ans_id = j["id"]
    lst = client.get("/api/rag/answers").json()
    assert any(a["id"] == ans_id for a in lst)
    got = client.get(f"/api/rag/answers/{ans_id}").json()
    assert got["status"] == "answered" and got["query"]
    assert client.delete(f"/api/rag/answers/{ans_id}").status_code == 204
    assert client.get(f"/api/rag/answers/{ans_id}").status_code == 404


def test_grounded_answer_insufficient_context_from_llm(client, grounded_collection):
    answer_generator_holder.set_fake(FakeAnswerGenerator("abstain"))
    try:
        r = _answer(client, grounded_collection["id"])
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "insufficient_context"
        assert j["sources"] == [] and j["citations"] == []
        assert j["grounding"]["grounded"] is False
        assert "Не знаю" in j["answer"]
    finally:
        answer_generator_holder.reset()


def test_grounded_eval_run_completes(client, grounded_collection, fake_answer_generator):
    ds = client.post("/api/rag/evaluation/dataset").json()
    assert len(ds["items"]) == 10
    r = client.post("/api/rag/evaluation/run", json={
        "dataset_id": ds["id"], "collection_id": grounded_collection["id"],
        "strategy": "structural", "name": "Grounded прогон", "base_config": _CONFIG,
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "completed", j.get("message")
    assert j["metrics"]["questions"] == 10
    for k in ("source_coverage", "citation_coverage", "citation_validity",
              "grounding_accuracy", "abstention_accuracy"):
        assert k in j["metrics"]
    assert len(j["per_question"]) == 10
    # история запусков
    assert any(x["id"] == j["id"] for x in client.get("/api/rag/evaluation/runs").json())
    assert client.get(f"/api/rag/evaluation/runs/{j['id']}").status_code == 200

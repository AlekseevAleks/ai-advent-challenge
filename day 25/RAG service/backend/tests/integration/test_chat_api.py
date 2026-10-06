"""Интеграционные тесты чата (полный pipeline: история + Task Memory + RAG)."""

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
        "collection_name": "RAG-тест-chat",
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


class FakeAnswerGenerator:
    def generate(self, query, context, model=None, prompt_version=None):
        m = re.search(r"\[chunk_id=([^\]\s]+)\]\s*(.*?)(?=\n\s*\[chunk_id=|\Z)", context, re.S)
        if not m:
            return AnswerLLMOutput(answer="недостаточно", claims=[], insufficient_context=True)
        cid = m.group(1)
        body_lines = [l for l in m.group(2).splitlines()
                      if not l.strip().startswith(("source=", "section="))]
        body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
        return AnswerLLMOutput(
            answer="Ответ основан на найденном документе.",
            claims=[{"text": (body[:70] or "ответ"), "chunk_ids": [cid]}],
            insufficient_context=False,
        )


@pytest.fixture()
def chat_collection(client):
    return _ready_index(client)


@pytest.fixture()
def low_gate(client):
    # чтобы сценарий давал «answered»-ответы, а не абстракции
    client.patch("/api/settings", json={
        "default_relevance_threshold": 0.0, "default_grounding_threshold": 0.5,
    })
    yield
    client.patch("/api/settings", json={
        "default_relevance_threshold": 0.65, "default_grounding_threshold": 0.7,
    })


@pytest.fixture()
def fake_llm():
    answer_generator_holder.set_fake(FakeAnswerGenerator())
    yield
    answer_generator_holder.reset()


def test_chat_conversation_flow(client, chat_collection, low_gate, fake_llm):
    cid = chat_collection["id"]
    r = client.post("/api/chat", json={
        "message": "Мне нужно создать учебный RAG-сервис.",
        "collection_id": cid, "strategy": "structural",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    conv_id = j["conversation_id"]
    assert conv_id
    assert j["message_id"]
    assert j["status"] in ("answered", "insufficient_context", "grounding_failed")
    assert "RAG" in j.get("task_state", {}).get("goal", "")

    # продолжение диалога: второй вопрос использует тот же conversation
    r2 = client.post("/api/chat", json={
        "conversation_id": conv_id,
        "message": "Используем FAISS для vector search.",
        "collection_id": cid, "strategy": "structural",
    })
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["conversation_id"] == conv_id
    assert j2.get("task_state", {}).get("decisions")

    # история и state
    got = client.get(f"/api/chat/{conv_id}").json()
    assert got["conversation_id"] == conv_id
    assert len(got["messages"]) >= 4  # user+assistant, user+assistant
    st = client.get(f"/api/chat/{conv_id}/state").json()
    assert st["version"] >= 2


def test_chat_new_conversation_isolated(client, chat_collection, low_gate, fake_llm):
    n = client.post("/api/chat/new").json()
    conv_id = n["conversation_id"]
    # новая беседа не наследует state
    st = client.get(f"/api/chat/{conv_id}/state").json()
    assert st["goal"] == "" and st["version"] == 1


def test_chat_scenario1_evaluation(client, chat_collection, low_gate, fake_llm):
    r = client.post("/api/chat/evaluation/run", json={
        "scenario": "1", "collection_id": chat_collection["id"], "strategy": "structural",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["messages"] == 12
    assert len(j["per_message"]) == 12
    m = j["metrics"]
    assert m["rag_call_coverage"] == 100.0
    for k in ("reranking_coverage", "source_coverage", "citation_coverage",
              "grounding_accuracy", "contextual_query_accuracy"):
        assert k in m
    assert "goal_retention" in j["retention"]
    # финальный state сохраняет цель
    assert "RAG" in (j.get("final_task_state") or {}).get("goal", "") or \
           (j.get("final_task_state") or {}).get("goal", "") == ""


def test_chat_scenario2_supersedes_faiss(client, chat_collection, low_gate, fake_llm):
    r = client.post("/api/chat/evaluation/run", json={
        "scenario": "2", "collection_id": chat_collection["id"], "strategy": "structural",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["messages"] == 13
    st = j.get("final_task_state") or {}
    decisions = st.get("decisions", []) or []
    active = {d["key"]: (d["value"] or "").lower() for d in decisions if d.get("status") == "active"}
    assert active.get("vector_store") == "chroma"
    superseded = {(d["key"], d.get("value", "").lower()) for d in decisions if d.get("status") == "superseded"}
    assert ("vector_store", "faiss") in superseded

"""Unit-тесты чата: Task Memory, извлечение состояния, контекстный запрос."""

from __future__ import annotations

from app.services.chat.contextual_query import build_contextual_query
from app.services.chat.task_memory import TaskState
from app.services.chat.task_state_extractor import (
    apply_task_update,
    extract_task_update,
)


# ---------------------------------------------------------------------------
# Task Memory базовые операции
# ---------------------------------------------------------------------------

def test_goal_and_constraints():
    st = TaskState()
    st.set_goal("создать учебный RAG-сервис")
    st.add_constraint("работать локально")
    assert st.goal == "создать учебный RAG-сервис"
    assert "работать локально" in st.constraints
    assert st.version >= 2


def test_constraint_dedup():
    st = TaskState()
    st.add_constraint("локально")
    st.add_constraint("локально")
    assert st.constraints == ["локально"]


def test_decision_active_then_superseded():
    st = TaskState()
    st.add_decision("vector_store", "faiss")
    assert st.active_decision("vector_store").value == "faiss"
    v1 = st.version
    st.add_decision("vector_store", "chroma")
    assert st.active_decision("vector_store").value == "chroma"
    faiss = [d for d in st.decisions if d.value == "faiss"][0]
    assert faiss.status == "superseded"
    assert st.version > v1  # версия изменилась


def test_no_duplicate_active_decision():
    st = TaskState()
    st.add_decision("reranker", "bge")
    v = st.version
    st.add_decision("reranker", "bge")
    assert st.version == v
    assert sum(1 for d in st.decisions if d.status == "active") == 1


def test_roundtrip_json():
    st = TaskState()
    st.set_goal("g")
    st.add_constraint("c")
    st.add_decision("vector_store", "faiss")
    d = st.to_dict()
    st2 = TaskState.from_dict(d)
    assert st2.goal == "g"
    assert st2.active_decision("vector_store").value == "faiss"
    assert st2.version == st.version


# ---------------------------------------------------------------------------
# Извлечение состояния из сообщений
# ---------------------------------------------------------------------------

def test_extract_goal_constraints_decisions():
    st = TaskState()
    upd = extract_task_update("Мне нужно создать учебный RAG-сервис.", st)
    apply_task_update(st, upd)
    assert "RAG" in st.goal

    upd = extract_task_update("Он должен работать локально.", st)
    apply_task_update(st, upd)
    assert "работать локально" in st.constraints

    upd = extract_task_update("Для vector search используем FAISS.", st)
    apply_task_update(st, upd)
    assert st.active_decision("vector_store").value == "faiss"


def test_scenario2_faiss_to_chroma():
    st = TaskState()
    for msg in ["Хочу сделать поиск по документам.",
                "Используем FAISS.",
                "Я передумал насчёт FAISS.",
                "Используем Chroma."]:
        apply_task_update(st, extract_task_update(msg, st))
    assert st.active_decision("vector_store").value == "chroma"
    faiss = [d for d in st.decisions if d.value == "faiss"]
    assert faiss and faiss[0].status == "superseded"


def test_scenario2_chunk_and_overlap():
    st = TaskState()
    apply_task_update(st, extract_task_update("Пусть chunk будет 500 токенов.", st))
    apply_task_update(st, extract_task_update("Overlap — 100 токенов.", st))
    assert st.active_decision("chunk_size").value == "500 токенов"
    assert st.active_decision("overlap").value == "100 токенов"


def test_extract_document_pdf_decision():
    st = TaskState()
    apply_task_update(st, extract_task_update("Документы будут PDF.", st))
    assert st.active_decision("document_format").value == "pdf"


def test_extract_focus_reranker():
    st = TaskState()
    apply_task_update(st, extract_task_update("Добавим reranking.", st))
    assert st.current_focus == "reranker"


# ---------------------------------------------------------------------------
# Contextual query
# ---------------------------------------------------------------------------

def test_contextual_query_enriches_pronoun():
    st = TaskState()
    st.set_goal("создать учебный RAG-сервис")
    st.set_focus("reranker")
    st.add_decision("reranker", "bge")
    q = build_contextual_query("А какой лучше?", st, [])
    assert q != "А какой лучше?"
    assert "reranker" in q.lower() or "rerank" in q.lower()
    assert "в контексте" in q


def test_contextual_query_preserves_meaning():
    st = TaskState()
    st.set_focus("reranker")
    q = build_contextual_query("Что такое reranking?", st, [])
    assert q.startswith("Что такое reranking")


def test_contextual_query_short_why():
    st = TaskState()
    st.set_focus("reranker")
    q = build_contextual_query("Почему?", st, [])
    assert q != "Почему?"
    assert "reranker" in q.lower()
